import { useRef, useState, type KeyboardEvent } from "react";

interface ChatComposerProps {
  placeholder: string;
  onSend: (content: string) => void;
  disabled?: boolean;
}

export function ChatComposer({
  placeholder,
  onSend,
  disabled = false,
}: ChatComposerProps) {
  const [content, setContent] = useState("");
  const isComposing = useRef(false);
  const compositionJustEnded = useRef(false);

  function send() {
    const normalized = content.trim();
    if (!normalized || disabled) return;
    onSend(normalized);
    setContent("");
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
      send();
    }
  }

  return (
    <textarea
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
