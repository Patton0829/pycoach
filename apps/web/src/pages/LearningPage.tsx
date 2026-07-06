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

type AssessmentOption = {
  moduleId: string;
  title: string;
  meta: string;
  kind: "foundation" | "chapter";
  loadingLead: string;
  loadingTokens: string[];
  visualSteps: string[];
};

const assessmentOptions = [
  {
    moduleId: "python_foundation_diagnostic",
    title: "Python 综合能力测试",
    meta: "35 题 / 第 3-9 章",
    kind: "foundation",
    loadingLead: "正在从第 3-9 章抽取知识点，组装一套能看出你真实水平的诊断题。",
    loadingTokens: ["I", "love", "Python", "list", "dict", "class"],
    visualSteps: ["read()", "think()", "practice()"],
  },
  {
    moduleId: "python_tutorial_ch3",
    title: "第 3 章：Python 入门",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕数字、文本、列表、索引切片和可变性准备题目。",
    loadingTokens: ["17 // 5", "'Py'[0]", "nums[1:]", "append()"],
    visualSteps: ["numbers", "text", "lists"],
  },
  {
    moduleId: "python_tutorial_ch4",
    title: "第 4 章：控制流",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕 if、for、range、break/continue 和函数参数准备题目。",
    loadingTokens: ["if", "for", "range()", "break", "def"],
    visualSteps: ["if", "for", "range()"],
  },
  {
    moduleId: "python_tutorial_ch5",
    title: "第 5 章：数据结构",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕列表方法、推导式、元组、集合、字典和循环技巧准备题目。",
    loadingTokens: ["list", "tuple", "set", "dict", "[x for x in xs]"],
    visualSteps: ["list", "dict", "set"],
  },
  {
    moduleId: "python_tutorial_ch6",
    title: "第 6 章：模块",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕 import、模块执行、搜索路径、dir() 和包准备题目。",
    loadingTokens: ["import", "module.py", "__name__", "dir()", "package"],
    visualSteps: ["import", "path", "package"],
  },
  {
    moduleId: "python_tutorial_ch7",
    title: "第 7 章：输入输出",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕格式化输出、str/repr、文件模式、with 和 JSON 准备题目。",
    loadingTokens: ["f-string", "repr()", "open()", "with", "json"],
    visualSteps: ["format", "file", "json"],
  },
  {
    moduleId: "python_tutorial_ch8",
    title: "第 8 章：错误与异常",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕语法错误、异常捕获、raise、finally 和自定义异常准备题目。",
    loadingTokens: ["try", "except", "raise", "finally", "Error"],
    visualSteps: ["try", "except", "finally"],
  },
  {
    moduleId: "python_tutorial_ch9",
    title: "第 9 章：类",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕命名空间、类定义、self、类变量、实例变量和继承准备题目。",
    loadingTokens: ["class", "__init__", "self", "super()", "MRO"],
    visualSteps: ["class", "self", "inherit"],
  },
] satisfies AssessmentOption[];

type ActiveView = "learning" | "chapters" | "knowledge" | "errors";

function navButtonClass(isActive: boolean): string {
  return `nav-button${isActive ? " nav-button--active" : ""}`;
}

function PreparingAssessment({ option }: { option: AssessmentOption }) {
  const isFoundation = option.kind === "foundation";
  return (
    <section
      className={`preparing-panel preparing-panel--${option.moduleId}`}
      role="status"
      aria-live="polite"
    >
      <div className="preparing-visual" aria-hidden="true">
        {isFoundation ? (
          <div className="python-love-visual">
            <div className="python-love__line">def heart():</div>
            <div className="python-love__line python-love__line--indent">
              return "I love Python"
            </div>
            <strong>我爱 Python</strong>
            <div className="python-love__pulse">print("I love Python")</div>
          </div>
        ) : (
          <div className="chapter-flow-visual">
            {option.visualSteps.map((step, index) => (
              <div className="flow-step" key={step}>
                <span>{step}</span>
                {index < option.visualSteps.length - 1 && (
                  <i aria-hidden="true" />
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="preparing-copy">
        <span>{isFoundation ? "I love Python" : option.title}</span>
        <strong>
          {isFoundation ? "正在生成综合能力诊断" : `正在生成${option.title}题目`}
        </strong>
        <p>{option.loadingLead}</p>
        <div className="preparing-token-list" aria-hidden="true">
          {option.loadingTokens.map((token) => (
            <code key={token}>{token}</code>
          ))}
        </div>
      </div>
    </section>
  );
}

export function LearningPage() {
  const conversationRef = useRef<HTMLDivElement>(null);
  const [activeView, setActiveView] = useState<ActiveView>("learning");
  const [preparingModuleId, setPreparingModuleId] = useState<string | null>(null);
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

  const foundationOption = assessmentOptions[0];
  const chapterOptions = assessmentOptions.slice(1);
  const preparingOption =
    assessmentOptions.find((option) => option.moduleId === preparingModuleId) ??
    null;

  useEffect(() => {
    const conversation = conversationRef.current;
    if (conversation) {
      conversation.scrollTop = conversation.scrollHeight;
    }
  }, [messages]);

  const currentTitle =
    preparingOption != null
      ? preparingOption.title
      : activeView === "knowledge"
      ? "个人知识图谱"
      : activeView === "errors"
        ? "个人错误图谱"
        : activeView === "chapters"
          ? "Python 章节测试"
          : chapterQuestionSet?.chapter_title ?? "请选择测试";

  async function handleStart(moduleId: string) {
    setPreparingModuleId(moduleId);
    setActiveView("learning");
    try {
      await startSession(moduleId);
    } finally {
      setPreparingModuleId(null);
    }
  }

  async function handleRestart() {
    setPreparingModuleId(null);
    setActiveView("learning");
    await restartSession();
  }

  const isPreparingAssessment =
    activeView === "learning" &&
    isLoading &&
    sessionId == null &&
    preparingOption != null;
  const isChapterAssessmentActive =
    activeView === "chapters" ||
    chapterOptions.some((option) => option.moduleId === preparingModuleId) ||
    (activeView === "learning" &&
      chapterOptions.some(
        (option) => option.moduleId === chapterQuestionSet?.chapter_id,
      ));

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
          <nav className="side-nav" aria-label="学习导航">
            <button
              type="button"
              className={navButtonClass(
                activeView === "learning" &&
                  (preparingModuleId === foundationOption.moduleId ||
                    chapterQuestionSet?.chapter_id === foundationOption.moduleId),
              )}
              onClick={() => void handleStart(foundationOption.moduleId)}
              disabled={isLoading}
              aria-label={`开始 ${foundationOption.title}`}
            >
              <span>{foundationOption.title}</span>
              <small>{foundationOption.meta}</small>
            </button>
            <button
              type="button"
              className={navButtonClass(isChapterAssessmentActive)}
              onClick={() => setActiveView("chapters")}
            >
              <span>Python 章节测试</span>
              <small>第 3-9 章</small>
            </button>
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
          {activeView === "learning" && chapterQuestionSet && (
            <div className="learning-summary" aria-label="当前测试进度">
              <span>本次已完成 {completedQuestionCount} 题</span>
              <strong>
                第 {chapterQuestionSet.current_question_slot} /{" "}
                {chapterQuestionSet.target_question_count} 题
              </strong>
              <small>
                {learnerLevelLabels[chapterQuestionSet.learner_level]}
              </small>
            </div>
          )}

          {activeView === "chapters" ? (
            <section className="chapter-selector">
              <div className="view-header">
                <strong>Python 章节测试</strong>
                <span>选择一个章节后，右侧会直接开始该章节的 10 道自适应题。</span>
              </div>
              <div className="chapter-grid">
                {chapterOptions.map((option) => (
                  <button
                    type="button"
                    className="chapter-card"
                    key={option.moduleId}
                    onClick={() => void handleStart(option.moduleId)}
                    disabled={isLoading}
                    aria-label={`开始 ${option.title}`}
                  >
                    <span>{option.title}</span>
                    <small>{option.meta}</small>
                  </button>
                ))}
              </div>
            </section>
          ) : activeView === "knowledge" ? (
            <div className="graph-detail">
              <PersonalKnowledgeGraph nodes={knowledgeNodes} />
            </div>
          ) : activeView === "errors" ? (
            <div className="graph-detail">
              <ErrorGraph nodes={errorNodes} />
            </div>
          ) : isPreparingAssessment ? (
            <PreparingAssessment option={preparingOption} />
          ) : sessionId ? (
            <div className="conversation-scroll" ref={conversationRef}>
              <ConversationTimeline messages={messages} />
              <ChatComposer
                placeholder={isLoading ? "正在连接 PyCoach…" : placeholder}
                onSend={sendStudentMessage}
                disabled={composerDisabled}
              />
            </div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
