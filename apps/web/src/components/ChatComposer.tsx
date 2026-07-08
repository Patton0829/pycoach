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
  const compositionJustEnded = useRef(false);
  const shouldRestoreFocus = useRef(false);

  useEffect(() => {
    if (!disabled && shouldRestoreFocus.current) {
      inputRef.current?.focus();
      shouldRestoreFocus.current = false;
    }
  }, [disabled]);

  async function send() {
    const normalized = content.trim();
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
    if (
      isComposing.current ||
      compositionJustEnded.current ||
      event.nativeEvent.isComposing ||
      event.keyCode === 229
    ) {
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
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
      onCompositionStart={() => {
        isComposing.current = true;
      }}
      onCompositionEnd={() => {
        isComposing.current = false;
        compositionJustEnded.current = true;
        window.setTimeout(() => {
          compositionJustEnded.current = false;
        }, 0);
      }}
    />
  );
}
