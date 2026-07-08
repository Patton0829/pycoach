import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

interface ChatComposerProps {
  placeholder: string;
  onSend: (content: string) => boolean | void | Promise<boolean | void>;
  disabled?: boolean;
}

export function ChatComposer({
  placeholder,
  onSend,
  disabled = false,
}: ChatComposerProps) {
  const [content, setContent] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isComposing = useRef(false);
  const enterSubmittedOnKeyDown = useRef(false);
  const allowLineBreak = useRef(false);
  const shouldSubmitAfterComposition = useRef(false);
  const shouldRestoreFocus = useRef(false);

  useEffect(() => {
    if (!disabled && shouldRestoreFocus.current) {
      inputRef.current?.focus();
      shouldRestoreFocus.current = false;
    }
  }, [disabled]);

  async function send(value = inputRef.current?.value ?? content) {
    const normalized = value.trim();
    if (!normalized || disabled) return;
    shouldRestoreFocus.current = true;
    const accepted = await onSend(normalized);
    if (accepted === false) {
      shouldRestoreFocus.current = false;
      inputRef.current?.focus();
      return;
    }
    setContent("");
    window.setTimeout(() => {
      if (!inputRef.current?.disabled) {
        inputRef.current?.focus();
        shouldRestoreFocus.current = false;
      }
    }, 0);
  }

  function handleBeforeInput(event: FormEvent<HTMLTextAreaElement>) {
    const nativeEvent = event.nativeEvent as InputEvent;
    if (
      nativeEvent.inputType !== "insertLineBreak" &&
      nativeEvent.inputType !== "insertParagraph"
    ) {
      return;
    }
    if (
      allowLineBreak.current ||
      isComposing.current ||
      nativeEvent.isComposing
    ) {
      return;
    }
    event.preventDefault();
    void send();
  }

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    const nextValue = event.target.value;
    if (!allowLineBreak.current && /[\r\n]/.test(nextValue)) {
      const valueWithoutBreaks = nextValue.replace(/[\r\n]+/g, "").trim();
      setContent(valueWithoutBreaks);
      if (valueWithoutBreaks && !isComposing.current) {
        void send(valueWithoutBreaks);
      }
      return;
    }
    setContent(nextValue);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter") return;
    if (event.shiftKey) {
      allowLineBreak.current = true;
      return;
    }
    allowLineBreak.current = false;
    enterSubmittedOnKeyDown.current = false;
    if (
      isComposing.current ||
      event.nativeEvent.isComposing ||
      event.keyCode === 229
    ) {
      shouldSubmitAfterComposition.current = true;
      return;
    }
    event.preventDefault();
    enterSubmittedOnKeyDown.current = true;
    void send();
  }

  function handleKeyUp(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter") return;
    if (event.shiftKey) {
      allowLineBreak.current = false;
      return;
    }
    allowLineBreak.current = false;
    if (enterSubmittedOnKeyDown.current) {
      enterSubmittedOnKeyDown.current = false;
      return;
    }
    if (isComposing.current || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void send();
  }

  return (
    <textarea
      ref={inputRef}
      className="composer"
      value={content}
      rows={2}
      placeholder={placeholder}
      aria-label="学习输入"
      disabled={disabled}
      onBeforeInput={handleBeforeInput}
      onChange={handleChange}
      onKeyDown={handleKeyDown}
      onKeyUp={handleKeyUp}
      onPaste={() => {
        allowLineBreak.current = true;
        window.setTimeout(() => {
          allowLineBreak.current = false;
        }, 0);
      }}
      onCompositionStart={() => {
        isComposing.current = true;
        allowLineBreak.current = false;
        shouldSubmitAfterComposition.current = false;
      }}
      onCompositionEnd={() => {
        isComposing.current = false;
        if (shouldSubmitAfterComposition.current) {
          shouldSubmitAfterComposition.current = false;
          enterSubmittedOnKeyDown.current = true;
          window.setTimeout(() => void send(), 0);
        }
      }}
    />
  );
}
