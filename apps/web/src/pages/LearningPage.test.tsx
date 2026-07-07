import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LearningPage } from "./LearningPage";

const initialSession = {
  session_id: "11111111-1111-4111-8111-111111111111",
  state: "QUESTION_ACTIVE",
  messages: [
    {
      id: "21111111-1111-4111-8111-111111111111",
      role: "questioner",
      content_markdown: "请填写：\n\n```python\nfirst = ________\n```",
      created_at: "2026-06-24T00:00:00Z",
    },
  ],
  current_question_id: "31111111-1111-4111-8111-111111111111",
  current_question: {
    question_id: "31111111-1111-4111-8111-111111111111",
    markdown: "请填写",
    input_hint: null,
  },
  knowledge_graph: [
    {
      node_id: "python.iterator.next",
      name: "next()",
      display_status: "正在学习",
    },
  ],
  error_graph: [
    {
      error_id: "iter_vs_next",
      name: "iter 与 next 混淆",
      display_status: "需要巩固",
    },
  ],
  completed_question_count: 0,
  chapter_question_set: {
    chapter_id: "python_tutorial_ch4",
    chapter_title: "控制流章节测试",
    target_question_count: 10,
    current_question_slot: 1,
    learner_level: "novice",
  },
  critic_content: {
    reference_answer: "绝不能显示",
  },
  provisional_knowledge_updates: ["绝不能显示"],
};

const refreshedSession = {
  ...initialSession,
  state: "QUESTION_ACTIVE",
  messages: [
    ...initialSession.messages,
    {
      id: "41111111-1111-4111-8111-111111111111",
      role: "student",
      content_markdown: "next(iterator)",
      created_at: "2026-06-24T00:01:00Z",
    },
    {
      id: "51111111-1111-4111-8111-111111111111",
      role: "critic",
      content_markdown: "回答正确。",
      created_at: "2026-06-24T00:01:01Z",
    },
  ],
  knowledge_graph: [
    {
      node_id: "python.iterator.next",
      name: "next()",
      display_status: "基本掌握",
    },
  ],
  error_graph: [],
  completed_question_count: 1,
  chapter_question_set: {
    ...initialSession.chapter_question_set,
    current_question_slot: 2,
  },
};

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }

  emit(data: unknown) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(data) }),
    );
  }

  close() {
    this.onclose?.();
  }
}

function deferredResponse() {
  let resolve: (response: Response) => void = () => {};
  const promise = new Promise<Response>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function openChapterSelector() {
  const button = await screen.findByRole("button", {
    name: /Python 章节测试/,
  });
  await waitFor(() => expect(button).not.toBeDisabled());
  fireEvent.click(button);
}

async function startControlFlowChapterTest() {
  await openChapterSelector();
  const chapterButton = await screen.findByRole("button", {
    name: "开始 第 4 章：控制流",
  });
  await waitFor(() => expect(chapterButton).not.toBeDisabled());
  fireEvent.click(chapterButton);
}

describe("LearningPage integration", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    window.localStorage.clear();
    vi.useRealTimers();
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal(
      "crypto",
      {
        randomUUID: vi
          .fn()
          .mockReturnValueOnce("61111111-1111-4111-8111-111111111111")
          .mockReturnValue("71111111-1111-4111-8111-111111111111"),
      },
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the AI Python Coach introduction by default after refresh", async () => {
    const fetchMock = vi.fn(async () => new Response("not found", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(screen.getByText("AI Python Coach")).toBeInTheDocument();
    expect(screen.getByText("当前模块：关于 AI Python Coach"))
      .toBeInTheDocument();
    expect(screen.getByText(/高反馈学习为核心/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("clears stored sessions on refresh and does not show continue controls", async () => {
    window.localStorage.setItem("pycoach.session_id", initialSession.session_id);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/api/sessions/${initialSession.session_id}`)) {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(screen.getByText("当前模块：关于 AI Python Coach"))
      .toBeInTheDocument();
    expect(screen.queryByText("请填写：")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes(`/api/sessions/${initialSession.session_id}`),
      ),
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /Python 章节测试/ }));
    expect(
      await screen.findByRole("button", { name: "开始 第 4 章：控制流" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "继续 第 4 章：控制流" }),
    ).not.toBeInTheDocument();
  });

  it("shows the Python foundation diagnostic intro before starting", async () => {
    const diagnosticSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_foundation_diagnostic",
        chapter_title: "Python 综合能力诊断（3-9 章）",
        target_question_count: 35,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toMatchObject({
          learner_id: "demo_user",
          module: "python_foundation_diagnostic",
        });
        return new Response(JSON.stringify(diagnosticSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    const button = await screen.findByRole("button", {
      name: "查看 Python 综合能力测试介绍",
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    expect(
      await screen.findByRole("heading", { name: "Python 综合能力测试" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/建立你个人学习画像/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "开始测评" }));

    expect(await screen.findByText("当前模块：Python 综合能力测试"))
      .toBeInTheDocument();
    expect(await screen.findByText(/第 1 \/ 35 题/)).toBeInTheDocument();
  });

  it("continues an active foundation diagnostic after viewing the graph", async () => {
    const diagnosticSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_foundation_diagnostic",
        chapter_title: "Python 综合能力诊断（3-9 章）",
        target_question_count: 35,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(diagnosticSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "查看 Python 综合能力测试介绍",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "开始测评" }));
    expect(await screen.findByText("请填写：")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /个人知识图谱/ }));
    expect(
      await screen.findByRole("heading", { name: "个人知识图谱" }),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "查看 Python 综合能力测试介绍",
      }),
    );
    expect(await screen.findByRole("button", { name: "继续测评" }))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续测评" }));

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    const createCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/sessions") && init?.method === "POST",
    );
    expect(createCalls).toHaveLength(1);
  });

  it("shows a Python-themed preparing state while foundation diagnostic is generated", async () => {
    const diagnosticSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_foundation_diagnostic",
        chapter_title: "Python 综合能力诊断（3-9 章）",
        target_question_count: 35,
      },
    };
    const pendingCreateSession = deferredResponse();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return pendingCreateSession.promise;
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    const button = await screen.findByRole("button", {
      name: "查看 Python 综合能力测试介绍",
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    expect(await screen.findByText(/建立你个人学习画像/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "开始测评" }));

    expect(await screen.findByText("正在生成综合能力诊断")).toBeInTheDocument();
    expect(screen.getByText("我爱 Python")).toBeInTheDocument();
    expect(screen.getByText('print("I love Python")')).toBeInTheDocument();

    await act(async () => {
      pendingCreateSession.resolve(
        new Response(JSON.stringify(diagnosticSession), { status: 200 }),
      );
    });

    expect(await screen.findByText("当前模块：Python 综合能力测试"))
      .toBeInTheDocument();
    expect(screen.queryByText("正在生成综合能力诊断")).not.toBeInTheDocument();
  });

  it("shows a chapter-specific preparing state while a chapter test is generated", async () => {
    const pendingCreateSession = deferredResponse();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toMatchObject({
          module: "python_tutorial_ch4",
        });
        return pendingCreateSession.promise;
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await openChapterSelector();
    fireEvent.click(screen.getByRole("button", { name: "开始 第 4 章：控制流" }));

    expect(await screen.findByText("正在生成第 4 章：控制流题目")).toBeInTheDocument();
    expect(screen.getAllByText("range()").length).toBeGreaterThan(0);
    expect(screen.getByText("围绕 if、for、range、break/continue 和函数参数准备题目。"))
      .toBeInTheDocument();

    await act(async () => {
      pendingCreateSession.resolve(
        new Response(JSON.stringify(initialSession), { status: 200 }),
      );
    });

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    expect(screen.queryByText("正在生成第 4 章：控制流题目")).not.toBeInTheDocument();
  });

  it("shows chapter choices on the right before starting a chapter test", async () => {
    const fetchMock = vi.fn(async () => new Response("not found", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await openChapterSelector();

    expect(
      await screen.findByRole("button", { name: "开始 第 3 章：Python 入门" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始 第 4 章：控制流" }))
      .toBeInTheDocument();
    expect(screen.queryByText("Python 迭代器章节测试")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows single-question challenge chapter choices on the right", async () => {
    const fetchMock = vi.fn(async () => new Response("not found", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    const challengeButton = await screen.findByRole("button", {
      name: /Python 单题闯关/,
    });
    fireEvent.click(challengeButton);

    expect((await screen.findAllByText("Python 单题闯关")).length)
      .toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "开始 第 5 章：数据结构单题闯关" }),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("starts a single-question challenge and keeps the topbar on the chapter title", async () => {
    const challengeSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_challenge_ch5",
        chapter_title: "第 5 章：数据结构单题闯关",
        target_question_count: 50,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toMatchObject({
          module: "python_challenge_ch5",
        });
        return new Response(JSON.stringify(challengeSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Python 单题闯关/ }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "开始 第 5 章：数据结构单题闯关",
      }),
    );

    expect(await screen.findByText("当前模块：第 5 章：数据结构"))
      .toBeInTheDocument();
    expect(await screen.findByText("第 1 题")).toBeInTheDocument();
    expect(screen.queryByText(/重新选择测试/)).not.toBeInTheDocument();
  });

  it("continues an active single-question challenge after viewing the graph", async () => {
    const challengeSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_challenge_ch3",
        chapter_title: "第 3 章：Python 入门单题闯关",
        target_question_count: 50,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(challengeSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Python 单题闯关/ }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "开始 第 3 章：Python 入门单题闯关",
      }),
    );
    expect(await screen.findByText("请填写：")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /个人知识图谱/ }));
    expect(
      await screen.findByRole("heading", { name: "个人知识图谱" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Python 单题闯关/ }));
    expect(
      await screen.findByRole("button", {
        name: "继续 第 3 章：Python 入门单题闯关",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "继续 第 3 章：Python 入门单题闯关",
      }),
    );

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    expect(screen.getByText("当前模块：第 3 章：Python 入门"))
      .toBeInTheDocument();
    const createCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/sessions") && init?.method === "POST",
    );
    expect(createCalls).toHaveLength(1);
  });

  it("shows the challenge completion animation when all chapter nodes are mastered", async () => {
    const masteredSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_challenge_ch5",
        chapter_title: "第 5 章：数据结构单题闯关",
        target_question_count: 50,
      },
      knowledge_graph: [
        {
          node_id: "python.ch5.list_methods",
          name: "列表方法",
          display_status: "基本掌握",
        },
        {
          node_id: "python.ch5.comprehensions",
          name: "列表推导式",
          display_status: "基本掌握",
        },
        {
          node_id: "python.ch5.tuples_sequences",
          name: "元组与序列",
          display_status: "基本掌握",
        },
        {
          node_id: "python.ch5.sets_dicts",
          name: "集合与字典",
          display_status: "基本掌握",
        },
        {
          node_id: "python.ch5.looping_conditions",
          name: "循环技巧与条件",
          display_status: "基本掌握",
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(masteredSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Python 单题闯关/ }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "开始 第 5 章：数据结构单题闯关",
      }),
    );

    expect(await screen.findByText("恭喜您，完成了第 5 章：数据结构全部的知识点测试"))
      .toBeInTheDocument();
    expect(
      screen.getByText(/您是我见过的最具天赋的种子型选手/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("学习输入")).not.toBeInTheDocument();
  });

  it("opens personal graph views from the left navigation", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/knowledge-graph")) {
        return new Response(
          JSON.stringify({
            learner_id: "demo_user",
            nodes: [
              {
                node_id: "python.ch3.lists",
                name: "列表基础",
                display_status: "尚未学习",
              },
            ],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/error-graph")) {
        return new Response(
          JSON.stringify({
            learner_id: "demo_user",
            nodes: [
              {
                error_id: "python.name_binding_confusion",
                name: "名称绑定混淆",
                display_status: "需要巩固",
              },
            ],
          }),
          { status: 200 },
        );
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    fireEvent.click(await screen.findByRole("button", { name: /个人知识图谱/ }));
    expect(
      await screen.findByRole("heading", { name: "个人知识图谱" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("列表基础")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /个人错误图谱/ }));
    expect(
      await screen.findByRole("heading", { name: "错误图谱" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("名称绑定混淆")).toBeInTheDocument();
  });

  it("opens the fixed AI Python Coach introduction page", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/knowledge-graph")) {
        return new Response(
          JSON.stringify({
            learner_id: "demo_user",
            nodes: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/error-graph")) {
        return new Response(
          JSON.stringify({
            learner_id: "demo_user",
            nodes: [],
          }),
          { status: 200 },
        );
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: /关于 AI Python Coach/ }),
    );

    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(screen.getByText("当前模块：关于 AI Python Coach")).toBeInTheDocument();
    expect(screen.getByText("主动回忆")).toBeInTheDocument();
    expect(screen.getByText("Questioner")).toBeInTheDocument();
    expect(screen.getByText("Critic")).toBeInTheDocument();
    expect(screen.getByText("第一步：完成综合能力测试")).toBeInTheDocument();
    expect(screen.getByText(/完成 Python 综合能力测试/)).toBeInTheDocument();
    expect(screen.getByText("第二步：单题闯关高反馈循环"))
      .toBeInTheDocument();
    expect(screen.getByText(/生成下一题，并把题目同时交给用户作答/))
      .toBeInTheDocument();
    expect(screen.getByText(/评估用户答案与本题出题水平/))
      .toBeInTheDocument();
    expect(screen.getByText(/Questioner 根据最新评估、出题质量反馈/))
      .toBeInTheDocument();
    expect(screen.getAllByText("个人错误图谱").length).toBeGreaterThan(0);
    expect(screen.getByText(/我们从不强调Python多么重要/))
      .toBeInTheDocument();
    expect(screen.getByText(/我们会乐此不疲/)).toBeInTheDocument();
    expect(screen.getByText("—PyCoach Lab")).toBeInTheDocument();
  });

  it("connects REST and WebSocket without exposing internal JSON", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      if (url.includes("/messages") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            message_id: "61111111-1111-4111-8111-111111111111",
            status: "processing",
            session_state: "CRITIC_PROCESSING",
          }),
          { status: 202 },
        );
      }
      if (url.includes("/api/sessions/") && !init?.method) {
        return new Response(JSON.stringify(refreshedSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    expect(screen.getByText("当前模块：第 4 章：控制流")).toBeInTheDocument();
    expect(screen.getByText(/第 1 \/ 10 题/)).toBeInTheDocument();
    expect(screen.getByText("基础强化")).toBeInTheDocument();
    expect(screen.queryByText("绝不能显示")).not.toBeInTheDocument();
    expect(screen.queryByText(/reference_answer/)).not.toBeInTheDocument();
    expect(screen.queryByText("QUESTION_ACTIVE")).not.toBeInTheDocument();

    const input = screen.getByLabelText("学习输入");
    expect(input.parentElement).toHaveClass("conversation-scroll");
    expect(
      screen.getByRole("article").compareDocumentPosition(input)
      & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.change(input, { target: { value: "next(iterator)" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    expect(screen.getByText("next(iterator)")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/messages"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    const socket = MockWebSocket.instances[0];
    expect(socket.url).toContain(initialSession.session_id);
    act(() => {
      socket.emit({
        type: "message_stream_started",
        session_id: initialSession.session_id,
        payload: {
          stream_id: "stream-critic-1",
          role: "critic",
        },
      });
      socket.emit({
        type: "message_stream_delta",
        session_id: initialSession.session_id,
        payload: {
          stream_id: "stream-critic-1",
          role: "critic",
          delta: "回答",
        },
      });
      socket.emit({
        type: "message_stream_delta",
        session_id: initialSession.session_id,
        payload: {
          stream_id: "stream-critic-1",
          role: "critic",
          delta: "正确。",
        },
      });
    });

    expect(await screen.findByText("回答正确。")).toBeInTheDocument();
    expect(screen.getByLabelText("正在流式输出")).toBeInTheDocument();

    act(() => {
      socket.emit({
        type: "critic_reply_ready",
        session_id: initialSession.session_id,
        payload: {
          stream_id: "stream-critic-1",
          message: {
            id: "51111111-1111-4111-8111-111111111111",
            role: "critic",
            content_markdown: "回答正确。",
            created_at: "2026-06-24T00:01:01Z",
          },
          session_state: "FEEDBACK_DISCUSSION",
        },
      });
    });

    expect(await screen.findByText("回答正确。")).toBeInTheDocument();
    expect(screen.queryByLabelText("正在流式输出")).not.toBeInTheDocument();
    expect(input).toHaveAttribute(
      "placeholder",
      "继续提问，或者输入“下一题”……",
    );

    act(() => {
      socket.emit({
        type: "candidate_question_stale",
        session_id: initialSession.session_id,
      });
    });
    expect(
      await screen.findByText("学习诊断已更新，正在重新准备后续题目"),
    ).toBeInTheDocument();

    act(() => {
      socket.emit({
        type: "session_summary_ready",
        session_id: initialSession.session_id,
        payload: {
          completed_question_count: 1,
          graphs_changed: true,
        },
      });
    });

    expect(await screen.findByText("本次已完成 1 题")).toBeInTheDocument();
    expect(await screen.findByText(/第 2 \/ 10 题/)).toBeInTheDocument();

    act(() => {
      socket.emit({
        type: "question_ready",
        session_id: initialSession.session_id,
        payload: {
          question_id: "81111111-1111-4111-8111-111111111111",
          markdown: "下一道正式题",
          input_hint: null,
        },
      });
    });
    expect(await screen.findByText("下一道正式题")).toBeInTheDocument();
    expect(screen.queryByText("请填写：")).not.toBeInTheDocument();
    expect(screen.queryByText("next(iterator)")).not.toBeInTheDocument();
    expect(screen.queryByText("回答正确。")).not.toBeInTheDocument();
  });

  it("does not advance when only a candidate next question is ready", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      if (url.includes("/messages") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            message_id: "61111111-1111-4111-8111-111111111111",
            status: "processing",
            session_state: "CRITIC_PROCESSING",
          }),
          { status: 202 },
        );
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();

    const input = await screen.findByLabelText("学习输入");
    fireEvent.change(input, { target: { value: "next(iterator)" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    const socket = MockWebSocket.instances[0];
    act(() => {
      socket.emit({
        type: "critic_reply_ready",
        session_id: initialSession.session_id,
        payload: {
          message: {
            id: "51111111-1111-4111-8111-111111111111",
            role: "critic",
            content_markdown: "答对了，这个判断很稳。",
            created_at: "2026-06-24T00:01:01Z",
          },
          session_state: "FEEDBACK_DISCUSSION",
        },
      });
    });

    act(() => {
      socket.emit({
        type: "candidate_question_ready",
        session_id: initialSession.session_id,
      });
    });

    expect(
      await screen.findByText("下一题已在后台准备好，输入“下一题”继续"),
    ).toBeInTheDocument();
    expect(screen.getByText("请填写：")).toBeInTheDocument();
    expect(screen.getByText("答对了，这个判断很稳。")).toBeInTheDocument();
    expect(screen.queryByText("候选题事件同步出的新题")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("学习输入")).not.toBeDisabled());
  });

  it("uses non-alarming wording when the socket is resynchronizing", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

    const socket = MockWebSocket.instances[0];
    act(() => {
      socket.close();
    });

    expect(await screen.findByText("学习服务正在同步")).toBeInTheDocument();
    expect(screen.queryByText(/实时连接已断开/)).not.toBeInTheDocument();
  });

  it("advances only after the official question_ready event", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      if (url.includes("/messages") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            message_id: "61111111-1111-4111-8111-111111111111",
            status: "processing",
            session_state: "CRITIC_PROCESSING",
          }),
          { status: 202 },
        );
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    const socket = MockWebSocket.instances[0];

    act(() => {
      socket.emit({
        type: "critic_reply_ready",
        session_id: initialSession.session_id,
        payload: {
          message: {
            id: "51111111-1111-4111-8111-111111111111",
            role: "critic",
            content_markdown: "答对了，这个判断很稳。",
            created_at: "2026-06-24T00:01:01Z",
          },
          session_state: "FEEDBACK_DISCUSSION",
        },
      });
    });

    const input = await screen.findByLabelText("学习输入");
    fireEvent.change(input, { target: { value: "下一题" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    act(() => {
      socket.emit({
        type: "question_ready",
        session_id: initialSession.session_id,
        payload: {
          question_id: "81111111-1111-4111-8111-111111111111",
          markdown: "正式发布的新题",
          input_hint: null,
        },
      });
    });

    expect(await screen.findByText("正式发布的新题")).toBeInTheDocument();
    expect(screen.queryByText("答对了，这个判断很稳。")).not.toBeInTheDocument();
  });

  it("returns to the left navigation on refresh when the stored session has progressed", async () => {
    window.localStorage.setItem("pycoach.session_id", initialSession.session_id);
    const progressedSession = {
      ...refreshedSession,
      state: "FEEDBACK_DISCUSSION",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes(`/api/sessions/${initialSession.session_id}`)) {
        return new Response(JSON.stringify(progressedSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    expect(
      await screen.findByRole("button", {
        name: "查看 Python 综合能力测试介绍",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not restore a stored foundation diagnostic question on refresh", async () => {
    window.localStorage.setItem("pycoach.session_id", initialSession.session_id);
    const foundationSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_foundation_diagnostic",
        chapter_title: "Python 综合能力诊断（3-9 章）",
        target_question_count: 35,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/api/sessions/${initialSession.session_id}`)) {
        return new Response(JSON.stringify(foundationSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    expect(
      await screen.findByRole("button", {
        name: "查看 Python 综合能力测试介绍",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("请填写：")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
  });

  it("returns to the left navigation when a stored legacy session has no module", async () => {
    window.localStorage.setItem("pycoach.session_id", initialSession.session_id);
    const legacySession = {
      ...initialSession,
      chapter_question_set: null,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/api/sessions/${initialSession.session_id}`)) {
        return new Response(JSON.stringify(legacySession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    expect(
      await screen.findByRole("button", {
        name: "查看 Python 综合能力测试介绍",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("请填写：")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
  });

  it("returns to chapter choices when the learner clicks chapter test again", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();
    expect(await screen.findByText("当前模块：第 4 章：控制流"))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Python 章节测试/ }));

    expect(
      await screen.findByRole("button", { name: "开始 第 5 章：数据结构" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/重新选择测试/)).not.toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
  });

  it("continues an active chapter test after viewing the graph", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();
    expect(await screen.findByText("请填写：")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /个人错误图谱/ }));
    expect(
      await screen.findByRole("heading", { name: "错误图谱" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Python 章节测试/ }));
    expect(
      await screen.findByRole("button", { name: "继续 第 4 章：控制流" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "继续 第 4 章：控制流" }),
    );

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    expect(screen.getByText("当前模块：第 4 章：控制流"))
      .toBeInTheDocument();
    const createCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input).endsWith("/api/sessions") && init?.method === "POST",
    );
    expect(createCalls).toHaveLength(1);
  });

  it("does not restore a stored iterator session removed from the test navigation", async () => {
    window.localStorage.setItem("pycoach.session_id", initialSession.session_id);
    const iteratorSession = {
      ...initialSession,
      chapter_question_set: {
        ...initialSession.chapter_question_set,
        chapter_id: "python_iterator",
        chapter_title: "Python 迭代器",
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/api/sessions/${initialSession.session_id}`)) {
        return new Response(JSON.stringify(iteratorSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);

    expect(
      await screen.findByRole("button", {
        name: "查看 Python 综合能力测试介绍",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "关于 AI Python Coach" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Python 迭代器")).not.toBeInTheDocument();
    expect(screen.queryByText("请选择左侧测试开始")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
  });

  it("keeps the composer disabled while an invalid question is being replaced", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startControlFlowChapterTest();

    const input = await screen.findByLabelText("学习输入");
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    const socket = MockWebSocket.instances[0];

    act(() => {
      socket.emit({
        type: "critic_reply_ready",
        session_id: initialSession.session_id,
        payload: {
          message: {
            id: "51111111-1111-4111-8111-111111111111",
            role: "critic",
            content_markdown: "这道题存在问题，我会为你换一道题。",
            created_at: "2026-06-24T00:01:01Z",
          },
          session_state: "QUESTION_INVALID",
        },
      });
    });

    expect(input).toBeDisabled();

    act(() => {
      socket.emit({
        type: "question_invalid",
        session_id: initialSession.session_id,
        payload: {
          student_visible_reason_markdown: "这道题存在问题，不会影响你的学习记录。",
        },
      });
    });

    expect(input).toBeDisabled();
    expect(input).toHaveAttribute("placeholder", "正在替换题目，请稍等……");

    act(() => {
      socket.emit({
        type: "question_ready",
        session_id: initialSession.session_id,
        payload: {
          question_id: "81111111-1111-4111-8111-111111111111",
          markdown: "替换后的新题",
          input_hint: null,
        },
      });
    });

    expect(await screen.findByText("替换后的新题")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("学习输入")).not.toBeDisabled());
  });

});
