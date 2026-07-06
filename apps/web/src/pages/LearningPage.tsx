import { useEffect, useRef, useState } from "react";
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
    title: "Python 综合能力测试",
    meta: "35 题 / 第 3-9 章",
  },
  {
    moduleId: "python_iterator",
    title: "Python 迭代器章节测试",
    meta: "10 题 / 迭代器",
  },
  {
    moduleId: "python_tutorial_ch3",
    title: "第 3 章：Python 入门",
    meta: "10 题 / 章节测试",
  },
  {
    moduleId: "python_tutorial_ch4",
    title: "第 4 章：控制流",
    meta: "10 题 / 章节测试",
  },
  {
    moduleId: "python_tutorial_ch5",
    title: "第 5 章：数据结构",
    meta: "10 题 / 章节测试",
  },
  {
    moduleId: "python_tutorial_ch6",
    title: "第 6 章：模块",
    meta: "10 题 / 章节测试",
  },
  {
    moduleId: "python_tutorial_ch7",
    title: "第 7 章：输入输出",
    meta: "10 题 / 章节测试",
  },
  {
    moduleId: "python_tutorial_ch8",
    title: "第 8 章：错误与异常",
    meta: "10 题 / 章节测试",
  },
  {
    moduleId: "python_tutorial_ch9",
    title: "第 9 章：类",
    meta: "10 题 / 章节测试",
  },
];

type ActiveView = "learning" | "knowledge" | "errors";

function navButtonClass(isActive: boolean): string {
  return `nav-button${isActive ? " nav-button--active" : ""}`;
}

export function LearningPage() {
  const conversationRef = useRef<HTMLDivElement>(null);
  const [activeView, setActiveView] = useState<ActiveView>("learning");
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

  const currentTitle =
    activeView === "knowledge"
      ? "个人知识图谱"
      : activeView === "errors"
        ? "个人错误图谱"
        : chapterQuestionSet?.chapter_title ?? "请选择测试";

  async function handleStart(moduleId: string) {
    setActiveView("learning");
    await startSession(moduleId);
  }

  async function handleRestart() {
    setActiveView("learning");
    await restartSession();
  }

  const foundationOption = assessmentOptions[0];
  const iteratorOption = assessmentOptions[1];
  const chapterOptions = assessmentOptions.slice(2);

  return (
    <main className="shell">
      <header className="topbar">
        <strong>PyCoach Lab</strong>
        <div className="topbar__actions">
          <span>当前模块：{currentTitle}</span>
          {sessionId && (
            <button type="button" onClick={() => void handleRestart()}>
              重新选择测试
            </button>
          )}
        </div>
      </header>
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

          <nav className="side-nav" aria-label="学习导航">
            <section className="nav-group">
              <h2>综合测试</h2>
              <button
                type="button"
                className={navButtonClass(
                  activeView === "learning" &&
                    chapterQuestionSet?.chapter_id === foundationOption.moduleId,
                )}
                onClick={() => void handleStart(foundationOption.moduleId)}
                disabled={isLoading}
                aria-label={`开始 ${foundationOption.title}`}
              >
                <span>{foundationOption.title}</span>
                <small>{foundationOption.meta}</small>
              </button>
            </section>

            <section className="nav-group">
              <h2>章节测试</h2>
              <button
                type="button"
                className={navButtonClass(
                  activeView === "learning" &&
                    chapterQuestionSet?.chapter_id === iteratorOption.moduleId,
                )}
                onClick={() => void handleStart(iteratorOption.moduleId)}
                disabled={isLoading}
                aria-label={`开始 ${iteratorOption.title}`}
              >
                <span>{iteratorOption.title}</span>
                <small>{iteratorOption.meta}</small>
              </button>
              {chapterOptions.map((option) => (
                <button
                  type="button"
                  className={navButtonClass(
                    activeView === "learning" &&
                      chapterQuestionSet?.chapter_id === option.moduleId,
                  )}
                  key={option.moduleId}
                  onClick={() => void handleStart(option.moduleId)}
                  disabled={isLoading}
                  aria-label={`开始 ${option.title}`}
                >
                  <span>{option.title}</span>
                  <small>{option.meta}</small>
                </button>
              ))}
            </section>

            <section className="nav-group">
              <h2>学习图谱</h2>
              <button
                type="button"
                className={navButtonClass(activeView === "knowledge")}
                onClick={() => setActiveView("knowledge")}
              >
                <span>个人知识图谱</span>
                <small>{knowledgeNodes.length} 个知识点</small>
              </button>
              <button
                type="button"
                className={navButtonClass(activeView === "errors")}
                onClick={() => setActiveView("errors")}
              >
                <span>个人错误图谱</span>
                <small>{errorNodes.length} 个错误类型</small>
              </button>
            </section>
          </nav>
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

          {activeView === "knowledge" ? (
            <div className="graph-detail">
              <PersonalKnowledgeGraph nodes={knowledgeNodes} />
            </div>
          ) : activeView === "errors" ? (
            <div className="graph-detail">
              <ErrorGraph nodes={errorNodes} />
            </div>
          ) : sessionId ? (
            <div className="conversation-scroll" ref={conversationRef}>
              <ConversationTimeline messages={messages} />
              <ChatComposer
                placeholder={isLoading ? "正在连接 PyCoach…" : placeholder}
                onSend={sendStudentMessage}
                disabled={composerDisabled}
              />
            </div>
          ) : (
            <section className="start-panel">
              <strong>请选择左侧测试开始</strong>
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
