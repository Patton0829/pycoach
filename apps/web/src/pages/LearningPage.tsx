import { useEffect, useRef } from "react";
import { ChatComposer } from "../components/ChatComposer";
import { ConversationTimeline } from "../components/ConversationTimeline";
import { ErrorGraph } from "../components/ErrorGraph";
import { PersonalKnowledgeGraph } from "../components/PersonalKnowledgeGraph";
import { useLearningSession } from "../hooks/useLearningSession";

const learnerLevelLabels = {
  novice: "基础强化",
  intermediate: "进阶巩固",
  advanced: "综合提升",
};

const assessmentOptions = [
  {
    moduleId: "python_foundation_diagnostic",
    title: "Python 综合能力诊断",
    meta: "35 题 / 第 3-9 章",
    scope: "入门、控制流、数据结构、模块、输入输出、异常、类",
  },
  {
    moduleId: "python_iterator",
    title: "Python 迭代器章节测试",
    meta: "10 题 / 迭代器",
    scope: "可迭代对象、iter()、next()、状态、耗尽、StopIteration",
  },
  {
    moduleId: "python_tutorial_ch3",
    title: "第 3 章：Python 入门",
    meta: "10 题 / 章节测试",
    scope: "数字、文本、列表、索引切片、赋值与可变性",
  },
  {
    moduleId: "python_tutorial_ch4",
    title: "第 4 章：控制流",
    meta: "10 题 / 章节测试",
    scope: "if、for、range、break/continue、函数、参数",
  },
  {
    moduleId: "python_tutorial_ch5",
    title: "第 5 章：数据结构",
    meta: "10 题 / 章节测试",
    scope: "列表方法、推导式、元组、集合、字典、循环技巧",
  },
  {
    moduleId: "python_tutorial_ch6",
    title: "第 6 章：模块",
    meta: "10 题 / 章节测试",
    scope: "import、脚本执行、搜索路径、dir()、包",
  },
  {
    moduleId: "python_tutorial_ch7",
    title: "第 7 章：输入输出",
    meta: "10 题 / 章节测试",
    scope: "格式化、str/repr、文件模式、with、JSON",
  },
  {
    moduleId: "python_tutorial_ch8",
    title: "第 8 章：错误与异常",
    meta: "10 题 / 章节测试",
    scope: "语法错误、异常、try/except、raise、finally、自定义异常",
  },
  {
    moduleId: "python_tutorial_ch9",
    title: "第 9 章：类",
    meta: "10 题 / 章节测试",
    scope: "命名空间、类、实例方法、类变量、继承",
  },
];

export function LearningPage() {
  const conversationRef = useRef<HTMLDivElement>(null);
  const {
    sessionId,
    messages,
    knowledgeNodes,
    errorNodes,
    completedQuestionCount,
    chapterQuestionSet,
    isLoading,
    isConnected,
    statusText,
    error,
    placeholder,
    composerDisabled,
    startSession,
    restartSession,
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
          <span>当前模块：{chapterQuestionSet?.chapter_title ?? "请选择测试"}</span>
          {sessionId && (
            <button type="button" onClick={() => void restartSession()}>
              重新选择测试
            </button>
          )}
        </div>
      </header>
      {!sessionId ? (
        <section className="assessment-selector">
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
          <div className="assessment-grid">
            {assessmentOptions.map((option) => (
              <article className="assessment-card" key={option.moduleId}>
                <div>
                  <strong>{option.title}</strong>
                  <span>{option.meta}</span>
                </div>
                <p>{option.scope}</p>
                <button
                  type="button"
                  aria-label={`开始 ${option.title}`}
                  onClick={() => void startSession(option.moduleId)}
                  disabled={isLoading}
                >
                  开始测试
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : (
      <div className="workspace">
        <aside className="sidebar">
          <div className="progress">本次已完成 {completedQuestionCount} 题</div>
          {chapterQuestionSet && (
            <div className="chapter-plan">
              <span>{chapterQuestionSet.chapter_title}</span>
              <strong>
                第 {chapterQuestionSet.current_question_slot} /{" "}
                {chapterQuestionSet.target_question_count} 题
              </strong>
              <small>
                {learnerLevelLabels[chapterQuestionSet.learner_level]}
              </small>
            </div>
          )}
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
      )}
    </main>
  );
}
