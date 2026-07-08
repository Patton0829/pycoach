import { useEffect, useRef, useState, type KeyboardEvent } from "react";

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

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
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
  }

  function handleKeyUp(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
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
      onChange={(event) => setContent(event.target.value)}
      onKeyDown={handleKeyDown}
      onKeyUp={handleKeyUp}
      onCompositionStart={() => {
        isComposing.current = true;
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
