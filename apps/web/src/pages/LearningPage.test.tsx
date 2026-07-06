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
    chapter_id: "python_iterator",
    chapter_title: "Python 迭代器",
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

async function startIteratorTest() {
  const button = await screen.findByRole("button", {
    name: "开始 Python 迭代器章节测试",
  });
  await waitFor(() => expect(button).not.toBeDisabled());
  fireEvent.click(button);
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

  it("starts the Python foundation diagnostic from the selector", async () => {
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
      name: "开始 Python 综合能力诊断",
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    expect(await screen.findByText("Python 综合能力诊断（3-9 章）")).toBeInTheDocument();
    expect(await screen.findByText(/第 1 \/ 35 题/)).toBeInTheDocument();
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
    await startIteratorTest();

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    expect(screen.getByText("Python 迭代器")).toBeInTheDocument();
    expect(screen.getByText(/第 1 \/ 10 题/)).toBeInTheDocument();
    expect(screen.getByText("基础强化")).toBeInTheDocument();
    expect(screen.getByText("next()")).toBeInTheDocument();
    expect(screen.getByText("正在学习")).toBeInTheDocument();
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
      await screen.findByText("诊断已变化，正在重新准备下一题"),
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
    expect(await screen.findByText("基本掌握")).toBeInTheDocument();
    expect(screen.queryByText("需要巩固")).not.toBeInTheDocument();

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

  it("re-enables the composer when a missed question_ready is recovered by REST sync", async () => {
    const nextQuestionSession = {
      ...initialSession,
      state: "QUESTION_ACTIVE",
      messages: [
        {
          id: "81111111-1111-4111-8111-111111111111",
          role: "questioner",
          content_markdown: "REST 同步出来的新题",
          created_at: "2026-06-24T00:03:00Z",
        },
      ],
      current_question_id: "81111111-1111-4111-8111-111111111111",
      current_question: {
        question_id: "81111111-1111-4111-8111-111111111111",
        markdown: "REST 同步出来的新题",
        input_hint: null,
      },
      completed_question_count: 1,
    };
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
        return new Response(JSON.stringify(nextQuestionSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startIteratorTest();

    const input = await screen.findByLabelText("学习输入");
    fireEvent.change(input, { target: { value: "下一题" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: false });

    expect(input).toBeDisabled();
    const socket = MockWebSocket.instances[0];
    act(() => {
      socket.emit({
        type: "candidate_question_ready",
        session_id: initialSession.session_id,
      });
    });

    expect(await screen.findByText("REST 同步出来的新题")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("学习输入")).not.toBeDisabled());
  });

  it("recovers a prepared next question even if the local state is stale", async () => {
    const nextQuestionSession = {
      ...initialSession,
      state: "QUESTION_ACTIVE",
      messages: [
        {
          id: "81111111-1111-4111-8111-111111111111",
          role: "questioner",
          content_markdown: "候选题事件同步出的新题",
          created_at: "2026-06-24T00:03:00Z",
        },
      ],
      current_question_id: "81111111-1111-4111-8111-111111111111",
      current_question: {
        question_id: "81111111-1111-4111-8111-111111111111",
        markdown: "候选题事件同步出的新题",
        input_hint: null,
      },
      completed_question_count: 1,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/sessions") && init?.method === "POST") {
        return new Response(JSON.stringify(initialSession), { status: 200 });
      }
      if (url.includes("/api/sessions/") && !init?.method) {
        return new Response(JSON.stringify(nextQuestionSession), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<LearningPage />);
    await startIteratorTest();

    expect(await screen.findByText("请填写：")).toBeInTheDocument();
    const socket = MockWebSocket.instances[0];
    act(() => {
      socket.emit({
        type: "candidate_question_ready",
        session_id: initialSession.session_id,
      });
    });

    expect(await screen.findByText("候选题事件同步出的新题")).toBeInTheDocument();
  });

  it("returns to the assessment selector on refresh when the stored session has progressed", async () => {
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
        name: "开始 Python 综合能力诊断",
      }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("pycoach.session_id")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/sessions"),
      expect.objectContaining({ method: "POST" }),
    );
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
    await startIteratorTest();

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
