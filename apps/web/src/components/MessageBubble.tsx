import { MarkdownContent } from "./MarkdownContent";
import { QuestionMetadata } from "./QuestionMetadata";
import type { TimelineMessage } from "../types/session";

const roleLabels = {
  questioner: "Questioner",
  student: "Student",
  critic: "Critic",
  system: "System",
};

export function MessageBubble({ message }: { message: TimelineMessage }) {
  return (
    <article className={`message message--${message.role}`}>
      <div className="message__role">{roleLabels[message.role]}</div>
      {message.role === "questioner" && message.questionMetadata && (
        <QuestionMetadata metadata={message.questionMetadata} />
      )}
      <MarkdownContent content={message.contentMarkdown} />
      {message.deliveryStatus === "streaming" && (
        <span className="streaming-cursor" aria-label="正在流式输出" />
      )}
      {message.deliveryStatus === "sending" && (
        <small className="message__status">发送中…</small>
      )}
      {message.deliveryStatus === "failed" && (
        <small className="message__status message__status--error">
          发送失败
        </small>
      )}
    </article>
  );
}
