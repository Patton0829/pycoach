import { MessageBubble } from "./MessageBubble";
import type { TimelineMessage } from "../types/session";

export function ConversationTimeline({
  messages,
}: {
  messages: TimelineMessage[];
}) {
  return (
    <section className="timeline" aria-live="polite">
      {messages.length === 0 ? (
        <div className="empty-state">正在准备第一道题…</div>
      ) : (
        messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))
      )}
    </section>
  );
}
