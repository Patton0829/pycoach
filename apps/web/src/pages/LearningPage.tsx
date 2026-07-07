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
  displayTitle: string;
  meta: string;
  kind: "foundation" | "chapter" | "challenge";
  loadingLead: string;
  loadingTokens: string[];
  visualSteps: string[];
};

const foundationOption = {
  moduleId: "python_foundation_diagnostic",
  title: "Python 综合能力测试",
  displayTitle: "Python 综合能力测试",
  meta: "35 题 / 第 3-9 章",
  kind: "foundation",
  loadingLead: "正在从第 3-9 章抽取知识点，组装一套能看出你真实水平的诊断题。",
  loadingTokens: ["I", "love", "Python", "list", "dict", "class"],
  visualSteps: ["read()", "think()", "practice()"],
} satisfies AssessmentOption;

const chapterTestOptions = [
  {
    moduleId: "python_tutorial_ch3",
    title: "第 3 章：Python 入门",
    displayTitle: "第 3 章：Python 入门",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕数字、文本、列表、索引切片和可变性准备题目。",
    loadingTokens: ["17 // 5", "'Py'[0]", "nums[1:]", "append()"],
    visualSteps: ["numbers", "text", "lists"],
  },
  {
    moduleId: "python_tutorial_ch4",
    title: "第 4 章：控制流",
    displayTitle: "第 4 章：控制流",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕 if、for、range、break/continue 和函数参数准备题目。",
    loadingTokens: ["if", "for", "range()", "break", "def"],
    visualSteps: ["if", "for", "range()"],
  },
  {
    moduleId: "python_tutorial_ch5",
    title: "第 5 章：数据结构",
    displayTitle: "第 5 章：数据结构",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕列表方法、推导式、元组、集合、字典和循环技巧准备题目。",
    loadingTokens: ["list", "tuple", "set", "dict", "[x for x in xs]"],
    visualSteps: ["list", "dict", "set"],
  },
  {
    moduleId: "python_tutorial_ch6",
    title: "第 6 章：模块",
    displayTitle: "第 6 章：模块",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕 import、模块执行、搜索路径、dir() 和包准备题目。",
    loadingTokens: ["import", "module.py", "__name__", "dir()", "package"],
    visualSteps: ["import", "path", "package"],
  },
  {
    moduleId: "python_tutorial_ch7",
    title: "第 7 章：输入输出",
    displayTitle: "第 7 章：输入输出",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕格式化输出、str/repr、文件模式、with 和 JSON 准备题目。",
    loadingTokens: ["f-string", "repr()", "open()", "with", "json"],
    visualSteps: ["format", "file", "json"],
  },
  {
    moduleId: "python_tutorial_ch8",
    title: "第 8 章：错误与异常",
    displayTitle: "第 8 章：错误与异常",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕语法错误、异常捕获、raise、finally 和自定义异常准备题目。",
    loadingTokens: ["try", "except", "raise", "finally", "Error"],
    visualSteps: ["try", "except", "finally"],
  },
  {
    moduleId: "python_tutorial_ch9",
    title: "第 9 章：类",
    displayTitle: "第 9 章：类",
    meta: "10 题 / 章节测试",
    kind: "chapter",
    loadingLead: "围绕命名空间、类定义、self、类变量、实例变量和继承准备题目。",
    loadingTokens: ["class", "__init__", "self", "super()", "MRO"],
    visualSteps: ["class", "self", "inherit"],
  },
] satisfies AssessmentOption[];

const challengeOptions = chapterTestOptions.map((option) => ({
  ...option,
  moduleId: option.moduleId.replace("python_tutorial_", "python_challenge_"),
  meta: "单题闯关",
  kind: "challenge" as const,
  loadingLead: `${option.displayTitle}单题闯关正在准备。系统会优先挑选你还没完全掌握的知识点，一次只出一道题。`,
}));

const assessmentOptions = [
  foundationOption,
  ...chapterTestOptions,
  ...challengeOptions,
] satisfies AssessmentOption[];

const optionByModuleId = new Map(
  assessmentOptions.map((option) => [option.moduleId, option]),
);

const chapterKnowledgeNodeIds: Record<string, string[]> = {
  ch3: [
    "python.ch3.numbers",
    "python.ch3.text",
    "python.ch3.sequence_indexing",
    "python.ch3.lists",
    "python.ch3.assignment_mutability",
  ],
  ch4: [
    "python.ch4.if",
    "python.ch4.for_range",
    "python.ch4.loop_control",
    "python.ch4.functions",
    "python.ch4.arguments",
  ],
  ch5: [
    "python.ch5.list_methods",
    "python.ch5.comprehensions",
    "python.ch5.tuples_sequences",
    "python.ch5.sets_dicts",
    "python.ch5.looping_conditions",
  ],
  ch6: [
    "python.ch6.imports",
    "python.ch6.module_execution",
    "python.ch6.search_path",
    "python.ch6.dir",
    "python.ch6.packages",
  ],
  ch7: [
    "python.ch7.fstrings_format",
    "python.ch7.str_repr",
    "python.ch7.open_modes",
    "python.ch7.with_files",
    "python.ch7.json",
  ],
  ch8: [
    "python.ch8.syntax_vs_exception",
    "python.ch8.try_except",
    "python.ch8.raise",
    "python.ch8.finally_cleanup",
    "python.ch8.custom_exceptions",
  ],
  ch9: [
    "python.ch9.namespaces_scopes",
    "python.ch9.class_definition",
    "python.ch9.instance_methods",
    "python.ch9.class_instance_variables",
    "python.ch9.inheritance",
  ],
};

type ActiveView =
  | "learning"
  | "foundationIntro"
  | "chapters"
  | "challenge"
  | "knowledge"
  | "errors"
  | "about";

function navButtonClass(isActive: boolean): string {
  return `nav-button${isActive ? " nav-button--active" : ""}`;
}

function AssessmentOptionCard({
  option,
  startLabel,
  continueLabel,
  canContinue,
  disabled,
  onStart,
  onContinue,
}: {
  option: AssessmentOption;
  startLabel: string;
  continueLabel: string;
  canContinue: boolean;
  disabled: boolean;
  onStart: () => void;
  onContinue: () => void;
}) {
  return (
    <article
      className={`chapter-card${canContinue ? " chapter-card--active" : ""}`}
    >
      <div className="chapter-card__content">
        <span>{option.title}</span>
        <small>{option.meta}</small>
      </div>
      <div className="chapter-card__actions">
        <button
          type="button"
          className="chapter-card__action"
          onClick={onStart}
          disabled={disabled}
          aria-label={startLabel}
        >
          开始
        </button>
        {canContinue && (
          <button
            type="button"
            className="chapter-card__action chapter-card__action--primary"
            onClick={onContinue}
            disabled={disabled}
            aria-label={continueLabel}
          >
            继续
          </button>
        )}
      </div>
    </article>
  );
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

function FoundationDiagnosticIntro({
  onStart,
  onContinue,
  canContinue,
  disabled,
}: {
  onStart: () => void;
  onContinue: () => void;
  canContinue: boolean;
  disabled: boolean;
}) {
  return (
    <section className="diagnostic-intro" aria-labelledby="diagnostic-title">
      <div className="diagnostic-intro__hero">
        <span>{foundationOption.meta}</span>
        <h1 id="diagnostic-title">Python 综合能力测试</h1>
        <p>
          这不是一套为了打分而存在的考试，而是 AI Python Coach
          建立你个人学习画像的入口。它会从 Python 官方教程第 3-9
          章中抽取核心知识点，观察你对语义、推理、代码阅读和常见误区的真实掌握情况。
        </p>
        <div className="diagnostic-intro__actions">
          <button
            type="button"
            className="primary-action"
            onClick={onStart}
            disabled={disabled}
          >
            开始测评
          </button>
          {canContinue && (
            <button
              type="button"
              className="secondary-action"
              onClick={onContinue}
              disabled={disabled}
            >
              继续测评
            </button>
          )}
        </div>
      </div>

      <div className="diagnostic-intro__grid">
        <article className="diagnostic-card">
          <strong>覆盖范围</strong>
          <p>
            数字与运算符、文本与字符串、列表和切片、控制流、数据结构、模块、输入输出、
            错误与异常、类。
          </p>
        </article>
        <article className="diagnostic-card">
          <strong>题目方式</strong>
          <p>
            Questioner 会生成阅读代码、预测输出、填空、概念辨析和迁移应用题，
            用 35 道题建立初始水平画像。
          </p>
        </article>
        <article className="diagnostic-card">
          <strong>评估方式</strong>
          <p>
            Critic 会判断你的答案是否抓住关键规则，并把证据写入个人知识图谱和个人错误图谱。
          </p>
        </article>
      </div>
    </section>
  );
}

function challengeChapterKey(moduleId: string | undefined): string | null {
  if (!moduleId?.startsWith("python_challenge_")) return null;
  return moduleId.replace("python_challenge_", "");
}

function isChallengeChapterMastered(
  moduleId: string | undefined,
  knowledgeNodes: { id: string; displayStatus: string }[],
): boolean {
  const chapterKey = challengeChapterKey(moduleId);
  if (!chapterKey) return false;
  const targetNodeIds = chapterKnowledgeNodeIds[chapterKey] ?? [];
  if (targetNodeIds.length === 0) return false;
  const statusById = new Map(
    knowledgeNodes.map((node) => [node.id, node.displayStatus]),
  );
  return targetNodeIds.every(
    (nodeId) => statusById.get(nodeId) === "基本掌握",
  );
}

function ChallengeComplete({ title }: { title: string }) {
  return (
    <section className="challenge-complete" role="status" aria-live="polite">
      <div className="challenge-complete__visual" aria-hidden="true">
        <span>pass</span>
        <span>master</span>
        <span>Python</span>
      </div>
      <div className="challenge-complete__copy">
        <span>{title}</span>
        <strong>恭喜您，完成了{title}全部的知识点测试</strong>
        <p>
          在学习 Python 的道路上，您是我见过的最具天赋的种子型选手，您努力学习
          Python 的样子，我觉得十分美好。
        </p>
      </div>
    </section>
  );
}

function AboutCoach() {
  const learningPrinciples = [
    {
      title: "主动回忆",
      body: "真正的学习不是把答案看懂，而是在没有答案时把规则、步骤和判断依据从脑子里取出来。",
    },
    {
      title: "适宜难度",
      body: "题目不能一直太简单，也不能一上来就过载。AI Python Coach 会根据当前掌握度调整题目难度。",
    },
    {
      title: "及时反馈",
      body: "每次回答都会得到 Critic 的即时评价。答对时强化有效策略，答错时直接指出规则、误区和推理路径。",
    },
    {
      title: "交错练习",
      body: "知识点不会永远按固定顺序出现。系统会把相关概念交错出现，帮助你建立可迁移的 Python 理解。",
    },
    {
      title: "元认知",
      body: "学习不仅是做题，还要知道自己哪里会、哪里不会、为什么错、下一步应该练什么。",
    },
    {
      title: "高反馈循环",
      body: "一次答题会同时更新题目、评价、知识图谱和错误图谱，让学习路径越来越贴近你本人。",
    },
  ];

  return (
    <section className="about-page" aria-labelledby="about-title">
      <div className="about-hero">
        <span>About AI Python Coach</span>
        <h1 id="about-title">关于 AI Python Coach</h1>
        <p>
          AI Python Coach 是一个以高反馈学习为核心的 Python 多智能体学习系统。
          它不只给你题目和答案，而是把每一次作答、追问、错误和进步沉淀成个人学习画像，
          再用这个画像决定下一道题应该考什么、怎么考、考到什么难度。
        </p>
      </div>

      <div className="about-section">
        <h2>核心学习理念</h2>
        <p>
          这个系统借鉴《认知天性》《学习之道》《我的天才学习方法》等学习方法论中的通用原则：
          主动回忆、间隔复习、交错练习、及时反馈、适宜难度和元认知。它们共同指向一件事：
          学习不是被动接收信息，而是在不断尝试、犯错、修正和迁移中形成稳定能力。
        </p>
        <div className="principle-grid">
          {learningPrinciples.map((principle) => (
            <article className="principle-card" key={principle.title}>
              <strong>{principle.title}</strong>
              <p>{principle.body}</p>
            </article>
          ))}
        </div>
      </div>

      <div className="about-section">
        <h2>Questioner 依据什么出题</h2>
        <div className="about-two-column">
          <p>
            Questioner 不是随机出题。它会读取当前测试类型、章节核心知识点、你的个人知识图谱、
            近期答题记录和高频错误类型，然后生成一道对当前学习最有价值的问题。
          </p>
          <ul>
            <li>章节测试关注该章核心概念，保证覆盖识别、补全、推理、解释和迁移。</li>
            <li>综合测试覆盖 Python 第 3-9 章，用来建立整体水平画像。</li>
            <li>单题闯关优先挑选你还没有完全掌握的知识点，一次只推进一道题。</li>
          </ul>
        </div>
      </div>

      <div className="about-section">
        <h2>Critic 如何评估</h2>
        <div className="about-two-column">
          <p>
            Critic 会结合题目、参考答案、可接受答案、学生回答和历史对话判断意图。
            它不执行学生代码，而是直接理解 Python 语义并给出评价。
          </p>
          <ul>
            <li>答对时，先明确肯定，再解释关键依据，强化正确思路。</li>
            <li>答错时，不做空泛安慰，直接分析错因、规则和推理路径。</li>
            <li>回合结束后，Critic 会把可靠证据写入个人知识图谱和个人错误图谱。</li>
          </ul>
        </div>
      </div>

      <div className="about-section">
        <h2>图谱如何帮助学习</h2>
        <div className="about-two-column">
          <p>
            个人知识图谱记录你对知识点的掌握状态，个人错误图谱记录你反复出现的误区。
            它们不是展示用的装饰，而是下一轮出题和难度调整的依据。
          </p>
          <ul>
            <li>知识图谱回答：哪些知识点已经掌握，哪些还需要巩固。</li>
            <li>错误图谱回答：你经常在哪些规则、概念或推理环节出错。</li>
            <li>两个图谱共同决定：下一题应该练什么，以及应该用什么方式检验。</li>
          </ul>
        </div>
      </div>

      <div className="about-section">
        <h2>系统架构图</h2>
        <div className="coach-diagram" aria-label="AI Python Coach 交互流程架构图">
          <div className="diagram-phase diagram-phase--diagnostic">
            <span className="diagram-phase__tag">第一步：完成综合能力测试</span>
            <div className="diagram-node diagram-node--user">
              <strong>用户</strong>
              <span>完成 Python 综合能力测试，系统建立初始学习画像</span>
            </div>
            <div className="diagram-arrow">↓ 诊断结果沉淀为画像</div>
            <div className="diagram-row diagram-row--graphs">
              <div className="diagram-node diagram-node--knowledge">
                <strong>个人知识图谱</strong>
                <span>记录第 3-9 章各知识点的掌握度</span>
              </div>
              <div className="diagram-node diagram-node--error">
                <strong>个人错误图谱</strong>
                <span>记录常见误区、错误类型和薄弱推理链路</span>
              </div>
            </div>
          </div>

          <div className="diagram-flow-arrow">↓ 进入 Python 单题闯关</div>

          <div className="diagram-phase diagram-phase--challenge">
            <span className="diagram-phase__tag">第二步：单题闯关高反馈循环</span>
            <div className="diagram-input-grid">
              <div className="diagram-node diagram-node--knowledge">
                <strong>个人知识图谱</strong>
                <span>告诉 Questioner 哪些知识点已掌握、哪些还需要检验</span>
              </div>
              <div className="diagram-node diagram-node--error">
                <strong>个人错误图谱</strong>
                <span>暴露用户最容易混淆的规则、概念和推理误区</span>
              </div>
              <div className="diagram-node diagram-node--methods">
                <strong>学习方法引擎</strong>
                <span>提供主动回忆、交错练习、适宜难度和及时反馈原则</span>
              </div>
              <div className="diagram-node diagram-node--signal">
                <strong>上一题 Critic 评估</strong>
                <span>包含用户答题表现和本题出题质量反馈</span>
              </div>
            </div>
            <div className="diagram-arrow">↓ 汇入出题依据</div>
            <div className="diagram-node diagram-node--questioner diagram-node--center">
              <strong>Questioner</strong>
              <span>生成下一题，并把题目同时交给用户作答、交给 Critic 评估出题水平</span>
            </div>
            <div className="diagram-split-line">
              <span>↙ 题目给用户作答</span>
              <span>↘ 题目给 Critic 评估出题水平</span>
            </div>
            <div className="diagram-row diagram-row--interaction">
              <div className="diagram-node diagram-node--user">
                <strong>用户</strong>
                <span>提交答案、提出疑问或表达不确定</span>
              </div>
              <div className="diagram-node diagram-node--critic">
                <strong>Critic</strong>
                <span>评估用户答案与本题出题水平，解释错因并沉淀证据</span>
              </div>
            </div>
            <div className="diagram-arrow">↓ Critic 输出四路反馈</div>
            <div className="diagram-feedback-grid">
              <div className="diagram-node diagram-node--feedback">
                <strong>反馈给用户浏览</strong>
                <span>答对时强化信心，答错时直接讲清错误原因</span>
              </div>
              <div className="diagram-node diagram-node--feedback">
                <strong>反馈给 Questioner</strong>
                <span>作为下一题选点、难度和题型调整依据</span>
              </div>
              <div className="diagram-node diagram-node--knowledge">
                <strong>更新个人知识图谱</strong>
                <span>提升或降低相关知识点掌握度</span>
              </div>
              <div className="diagram-node diagram-node--error">
                <strong>更新个人错误图谱</strong>
                <span>记录本次暴露出的误区和错误类型</span>
              </div>
            </div>
            <div className="diagram-loopback">
              ↺ Questioner 根据最新评估、出题质量反馈、知识图谱和错误图谱酝酿下一题，进入下一轮
            </div>
          </div>
        </div>
      </div>

      <blockquote className="founder-note">
        <p>
          在AI Python Coach，我们从不强调Python多么重要，就像我们的高中数学老师总是强调得数学者得天下一样，那样会增长功利心，也就没法享受学习Python的乐趣，而做我们喜欢的事情，就不会觉得累，我们会乐此不疲，我们希望通过引入高反馈机制、好的学习方法、适宜的难度、大模型能力来做这样更懂用户的多智能体系统，帮助用户在学习Python的道路上略尽绵薄之力。
        </p>
        <footer>—PyCoach Lab</footer>
      </blockquote>
    </section>
  );
}

export function LearningPage() {
  const conversationRef = useRef<HTMLDivElement>(null);
  const restoredSessionActivatedRef = useRef(false);
  const [activeView, setActiveView] = useState<ActiveView>("about");
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
    sendStudentMessage,
  } = useLearningSession();

  const preparingOption =
    assessmentOptions.find((option) => option.moduleId === preparingModuleId) ??
    null;
  const activeSessionOption = chapterQuestionSet
    ? optionByModuleId.get(chapterQuestionSet.chapter_id)
    : null;
  const activeSessionTitle =
    activeSessionOption?.displayTitle ?? chapterQuestionSet?.chapter_title;
  const challengeComplete =
    activeView === "learning" &&
    chapterQuestionSet != null &&
    isChallengeChapterMastered(chapterQuestionSet.chapter_id, knowledgeNodes);
  const isActiveChallengeSession =
    chapterQuestionSet?.chapter_id.startsWith("python_challenge_") ?? false;

  useEffect(() => {
    const conversation = conversationRef.current;
    if (conversation) {
      conversation.scrollTop = conversation.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (!sessionId) {
      restoredSessionActivatedRef.current = false;
      return;
    }
    if (
      !isLoading &&
      chapterQuestionSet != null &&
      !restoredSessionActivatedRef.current
    ) {
      restoredSessionActivatedRef.current = true;
      if (activeView === "about") {
        setActiveView("learning");
      }
    }
  }, [activeView, chapterQuestionSet, isLoading, sessionId]);

  const currentTitle =
    activeView === "knowledge"
      ? "个人知识图谱"
      : activeView === "errors"
        ? "个人错误图谱"
        : activeView === "about"
          ? "关于 AI Python Coach"
          : activeView === "foundationIntro"
            ? foundationOption.displayTitle
          : preparingOption != null
            ? preparingOption.displayTitle
            : activeView === "chapters"
              ? "Python 章节测试"
              : activeView === "challenge"
                ? "Python 单题闯关"
                : activeSessionTitle != null
                  ? activeSessionTitle
                  : "请选择测试";

  async function handleStart(moduleId: string) {
    setPreparingModuleId(moduleId);
    setActiveView("learning");
    try {
      await startSession(moduleId);
    } finally {
      setPreparingModuleId(null);
    }
  }

  function handleContinue() {
    setPreparingModuleId(null);
    setActiveView("learning");
  }

  function canContinueModule(moduleId: string): boolean {
    return (
      sessionId != null &&
      chapterQuestionSet != null &&
      chapterQuestionSet.chapter_id === moduleId
    );
  }

  const isPreparingAssessment =
    activeView === "learning" &&
    isLoading &&
    sessionId == null &&
    preparingOption != null;
  const isChapterAssessmentActive =
    activeView === "chapters" ||
    chapterTestOptions.some((option) => option.moduleId === preparingModuleId) ||
    (activeView === "learning" &&
      chapterTestOptions.some(
        (option) => option.moduleId === chapterQuestionSet?.chapter_id,
      ));
  const isChallengeActive =
    activeView === "challenge" ||
    challengeOptions.some((option) => option.moduleId === preparingModuleId) ||
    (activeView === "learning" &&
      challengeOptions.some(
        (option) => option.moduleId === chapterQuestionSet?.chapter_id,
      ));

  return (
    <main className="shell">
      <header className="topbar">
        <strong>AI Python Coach</strong>
        <div className="topbar__actions">
          <span>当前模块：{currentTitle}</span>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <nav className="side-nav" aria-label="学习导航">
            <button
              type="button"
              className={navButtonClass(
                activeView === "foundationIntro" ||
                  (activeView === "learning" &&
                    (preparingModuleId === foundationOption.moduleId ||
                      chapterQuestionSet?.chapter_id === foundationOption.moduleId)),
              )}
              onClick={() => setActiveView("foundationIntro")}
              disabled={isLoading}
              aria-label={`查看 ${foundationOption.title}介绍`}
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
              className={navButtonClass(isChallengeActive)}
              onClick={() => setActiveView("challenge")}
            >
              <span>Python 单题闯关</span>
              <small>单题闯关</small>
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
            <button
              type="button"
              className={navButtonClass(activeView === "about")}
              onClick={() => setActiveView("about")}
            >
              <span>关于 AI Python Coach</span>
              <small>理念 / 架构 / 学习方法</small>
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
          {activeView === "learning" && chapterQuestionSet && !challengeComplete && (
            <div className="learning-summary" aria-label="当前测试进度">
              <span>本次已完成 {completedQuestionCount} 题</span>
              {isActiveChallengeSession ? (
                <strong>第 {completedQuestionCount + 1} 题</strong>
              ) : (
                <strong>
                  第 {chapterQuestionSet.current_question_slot} /{" "}
                  {chapterQuestionSet.target_question_count} 题
                </strong>
              )}
              <small>
                {isActiveChallengeSession
                  ? "单题闯关"
                  : learnerLevelLabels[chapterQuestionSet.learner_level]}
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
                {chapterTestOptions.map((option) => (
                  <AssessmentOptionCard
                    key={option.moduleId}
                    option={option}
                    startLabel={`开始 ${option.title}`}
                    continueLabel={`继续 ${option.title}`}
                    canContinue={canContinueModule(option.moduleId)}
                    disabled={isLoading}
                    onStart={() => void handleStart(option.moduleId)}
                    onContinue={handleContinue}
                  />
                ))}
              </div>
            </section>
          ) : activeView === "foundationIntro" ? (
            <FoundationDiagnosticIntro
              onStart={() => void handleStart(foundationOption.moduleId)}
              onContinue={handleContinue}
              canContinue={canContinueModule(foundationOption.moduleId)}
              disabled={isLoading}
            />
          ) : activeView === "challenge" ? (
            <section className="chapter-selector">
              <div className="view-header">
                <strong>Python 单题闯关</strong>
                <span>
                  选择章节后，每次只推进一道题；系统会围绕该章尚未完全掌握的知识点持续出题。
                </span>
              </div>
              <div className="chapter-grid">
                {challengeOptions.map((option) => (
                  <AssessmentOptionCard
                    key={option.moduleId}
                    option={option}
                    startLabel={`开始 ${option.title}单题闯关`}
                    continueLabel={`继续 ${option.title}单题闯关`}
                    canContinue={canContinueModule(option.moduleId)}
                    disabled={isLoading}
                    onStart={() => void handleStart(option.moduleId)}
                    onContinue={handleContinue}
                  />
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
          ) : activeView === "about" ? (
            <AboutCoach />
          ) : isPreparingAssessment ? (
            <PreparingAssessment option={preparingOption} />
          ) : challengeComplete ? (
            <ChallengeComplete title={activeSessionTitle ?? "本章"} />
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
