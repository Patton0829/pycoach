import { useEffect, useRef } from "react";
import { ChatComposer } from "../components/ChatComposer";
import { ConversationTimeline } from "../components/ConversationTimeline";
import { ErrorGraph } from "../components/ErrorGraph";
import { PersonalKnowledgeGraph } from "../components/PersonalKnowledgeGraph";
import { useLearningSession } from "../hooks/useLearningSession";

export function LearningPage() {
  const conversationRef = useRef<HTMLDivElement>(null);
  const {
    messages,
    knowledgeNodes,
    errorNodes,
    completedQuestionCount,
    isLoading,
    isConnected,
    statusText,
    error,
    placeholder,
    composerDisabled,
    sendStudentMessage,
  } = useLearningSession();

  useEffect(() => {
    const conversation = conversationRef.current;
    if (conversation) {
      conversation.scrollTop = conversation.scrollHeight;
    }
  }, [messages]);

  return (
    <main className="shell">
      <header className="topbar">
        <strong>PyCoach Lab</strong>
        <div className="topbar__actions">
          <span>当前模块：Python 迭代器</span>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="progress">本次已完成 {completedQuestionCount} 题</div>
          <PersonalKnowledgeGraph nodes={knowledgeNodes} />
          <ErrorGraph nodes={errorNodes} />
        </aside>
        <div className="learning-area">
          <div className="session-status" role="status">
            <span
              className={`connection-dot ${
                isConnected ? "connection-dot--online" : ""
              }`}
              aria-hidden="true"
            />
            <span>{statusText}</span>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          <div className="conversation-scroll" ref={conversationRef}>
            <ConversationTimeline messages={messages} />
            <ChatComposer
              placeholder={isLoading ? "正在连接 PyCoach…" : placeholder}
              onSend={sendStudentMessage}
              disabled={composerDisabled}
            />
          </div>
        </div>
      </div>
    </main>
  );
}
