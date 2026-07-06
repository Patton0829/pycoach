import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createLearningSession,
  getLearningSession,
  submitStudentMessage,
} from "../api/client";
import type {
  GraphNode,
  ChapterQuestionSetSummary,
  LearningSessionResponse,
  SessionSocketEvent,
  SessionState,
  TimelineMessage,
} from "../types/session";
import {
  selectCurrentRoundMessages,
  toErrorGraphNode,
  toKnowledgeGraphNode,
  toTimelineMessage,
} from "../types/session";
import { useSessionSocket } from "./useSessionSocket";

const SESSION_STORAGE_KEY = "pycoach.session_id";
const streamMessageId = (streamId: string) => `stream-${streamId}`;
const SUBMITTING_STATES: SessionState[] = [
  "USER_MESSAGE_RECEIVED",
  "CRITIC_PROCESSING",
  "ROUND_FINALIZING",
];

function shouldReuseStoredSession(session: LearningSessionResponse): boolean {
  const hasStudentOrCriticMessage = session.messages.some(
    (message) => message.role === "student" || message.role === "critic",
  );
  return (
    session.state === "QUESTION_ACTIVE" &&
    session.chapter_question_set != null &&
    session.completed_question_count === 0 &&
    !hasStudentOrCriticMessage
  );
}

function statePlaceholder(state: SessionState | null): string {
  if (
    state === "QUESTION_INVALID" ||
    state === "QUESTION_GENERATING" ||
    state === "QUESTION_GENERATION_FAILED"
  ) {
    return "正在替换题目，请稍等……";
  }
  if (
    state === "FEEDBACK_DISCUSSION" ||
    state === "ROUND_FINALIZING" ||
    state === "NEXT_QUESTION_READY"
  ) {
    return "继续提问，或者输入“下一题”……";
  }
  if (state === "SESSION_ENDED") {
    return "本次学习已结束。";
  }
  return "输入答案，也可以说“我不确定”或提出疑问……";
}

function appendUnique(
  messages: TimelineMessage[],
  message: TimelineMessage,
): TimelineMessage[] {
  if (messages.some((item) => item.id === message.id)) return messages;
  const latest = messages.at(-1);
  if (
    latest?.role === message.role &&
    latest.contentMarkdown === message.contentMarkdown
  ) {
    return messages;
  }
  return [...messages, message];
}

export function useLearningSession() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [state, setState] = useState<SessionState | null>(null);
  const [messages, setMessages] = useState<TimelineMessage[]>([]);
  const [knowledgeNodes, setKnowledgeNodes] = useState<GraphNode[]>([]);
  const [errorNodes, setErrorNodes] = useState<GraphNode[]>([]);
  const [completedQuestionCount, setCompletedQuestionCount] = useState(0);
  const [chapterQuestionSet, setChapterQuestionSet] =
    useState<ChapterQuestionSetSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [statusText, setStatusText] = useState("请选择测试开始");
  const [error, setError] = useState<string | null>(null);

  const applySession = useCallback((session: LearningSessionResponse) => {
    setSessionId(session.session_id);
    setState(session.state);
    if (!SUBMITTING_STATES.includes(session.state)) {
      setIsSubmitting(false);
    }
    setMessages(
      selectCurrentRoundMessages(session.messages.map(toTimelineMessage)),
    );
    setKnowledgeNodes(session.knowledge_graph.map(toKnowledgeGraphNode));
    setErrorNodes(session.error_graph.map(toErrorGraphNode));
    setCompletedQuestionCount(session.completed_question_count);
    setChapterQuestionSet(session.chapter_question_set ?? null);
  }, []);

  const clearSessionView = useCallback(() => {
    setSessionId(null);
    setState(null);
    setMessages([]);
    setKnowledgeNodes([]);
    setErrorNodes([]);
    setCompletedQuestionCount(0);
    setChapterQuestionSet(null);
    setIsSubmitting(false);
    setIsConnected(false);
  }, []);

  const refreshProgress = useCallback(
    async (targetSessionId?: string) => {
      const id = targetSessionId ?? sessionId;
      if (!id) return;
      const session = await getLearningSession(id);
      setKnowledgeNodes(session.knowledge_graph.map(toKnowledgeGraphNode));
      setErrorNodes(session.error_graph.map(toErrorGraphNode));
      setCompletedQuestionCount(session.completed_question_count);
      setChapterQuestionSet(session.chapter_question_set ?? null);
    },
    [sessionId],
  );

  const synchronizeSession = useCallback(
    async (targetSessionId?: string) => {
      const id = targetSessionId ?? sessionId;
      if (!id) return;
      const session = await getLearningSession(id);
      applySession(session);
      if (session.state === "QUESTION_ACTIVE") {
        setStatusText("新题已准备好");
      } else if (session.state === "FEEDBACK_DISCUSSION") {
        setStatusText("下一题暂时未发布，可以重试");
      }
    },
    [applySession, sessionId],
  );

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      setIsLoading(true);
      setError(null);
      try {
        const storedSessionId = window.localStorage.getItem(SESSION_STORAGE_KEY);
        if (storedSessionId) {
          try {
            const session = await getLearningSession(storedSessionId);
            if (shouldReuseStoredSession(session)) {
              if (cancelled) return;
              applySession(session);
              setStatusText("题目已准备好");
            } else {
              window.localStorage.removeItem(SESSION_STORAGE_KEY);
              if (cancelled) return;
              clearSessionView();
              setStatusText("请选择测试开始");
            }
          } catch {
            window.localStorage.removeItem(SESSION_STORAGE_KEY);
            if (cancelled) return;
            clearSessionView();
            setStatusText("请选择测试开始");
          }
        } else {
          clearSessionView();
          setStatusText("请选择测试开始");
        }
      } catch (reason) {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : "无法恢复学习会话");
        setStatusText("后端连接失败");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void initialize();
    return () => {
      cancelled = true;
    };
  }, [applySession, clearSessionView]);

  useEffect(() => {
    if (
      (state !== "ROUND_FINALIZING" && state !== "CRITIC_PROCESSING")
      || !sessionId
    ) {
      return;
    }
    const timeout = window.setTimeout(() => {
      void synchronizeSession(sessionId).catch(() => {
        setStatusText("会话同步失败，可刷新页面重试");
      });
    }, state === "CRITIC_PROCESSING" ? 5000 : 2500);
    return () => window.clearTimeout(timeout);
  }, [sessionId, state, synchronizeSession]);

  const handleSocketEvent = useCallback(
    (event: SessionSocketEvent) => {
      switch (event.type) {
        case "connection_ready":
          setStatusText((current) =>
            current.includes("Questioner") ? current : "实时连接已建立",
          );
          break;
        case "message_stream_started": {
          const streamingMessage: TimelineMessage = {
            id: streamMessageId(event.payload.stream_id),
            role: "critic",
            contentMarkdown: "",
            deliveryStatus: "streaming",
          };
          setMessages((current) =>
            appendUnique(current, streamingMessage),
          );
          setStatusText("Critic 正在输出…");
          break;
        }
        case "message_stream_delta":
          setMessages((current) =>
            current.map((message) =>
              message.id === streamMessageId(event.payload.stream_id)
                ? {
                    ...message,
                    contentMarkdown:
                      message.contentMarkdown + event.payload.delta,
                  }
                : message,
            ),
          );
          break;
        case "message_stream_reset":
          setMessages((current) =>
            current.map((message) =>
              message.id === streamMessageId(event.payload.stream_id)
                ? { ...message, contentMarkdown: "" }
                : message,
            ),
          );
          setStatusText("模型正在修正输出格式…");
          break;
        case "critic_reply_ready":
          setMessages((current) => {
            const withoutStream = event.payload.stream_id
              ? current.filter(
                  (message) =>
                    message.id !== streamMessageId(event.payload.stream_id!),
                )
              : current;
            return appendUnique(
              withoutStream,
              toTimelineMessage(event.payload.message),
            );
          });
          setState(event.payload.session_state);
          setIsSubmitting(false);
          setStatusText("Critic 已回复");
          break;
        case "candidate_question_ready":
          setStatusText("下一题已准备");
          window.setTimeout(() => {
            void synchronizeSession(event.session_id).catch(() => {
              setStatusText("会话同步失败，可刷新页面重试");
            });
          }, 500);
          break;
        case "candidate_question_stale":
          setStatusText("诊断已变化，正在重新准备下一题");
          break;
        case "question_invalid":
          setMessages((current) =>
            appendUnique(current, {
              id: `invalid-${crypto.randomUUID()}`,
              role: "critic",
              contentMarkdown: event.payload.student_visible_reason_markdown,
            }),
          );
          setState("QUESTION_GENERATING");
          setIsSubmitting(false);
          setStatusText("题目已撤销，正在替换");
          break;
        case "session_summary_ready":
          setCompletedQuestionCount(event.payload.completed_question_count);
          setStatusText("学习记录已更新");
          void refreshProgress(event.session_id).catch(() => {
            setStatusText("图谱刷新失败，可刷新页面重试");
          });
          break;
        case "question_ready":
          setMessages([
            {
              id: event.payload.question_id,
              role: "questioner",
              contentMarkdown: event.payload.markdown,
              deliveryStatus: "sent",
            },
          ]);
          setState("QUESTION_ACTIVE");
          setIsSubmitting(false);
          setStatusText("新题已准备好");
          break;
      }
    },
    [refreshProgress, synchronizeSession],
  );

  const handleConnectionChange = useCallback((connected: boolean) => {
    setIsConnected(connected);
    if (!connected) setStatusText("实时连接已断开，正在等待恢复");
  }, []);

  useSessionSocket(sessionId, handleSocketEvent, handleConnectionChange);

  const sendStudentMessage = useCallback(
    async (contentMarkdown: string) => {
      if (!sessionId || isSubmitting) return;
      const messageId = crypto.randomUUID();
      const optimisticMessage: TimelineMessage = {
        id: messageId,
        role: "student",
        contentMarkdown,
        createdAt: new Date().toISOString(),
        deliveryStatus: "sending",
      };
      setMessages((current) => appendUnique(current, optimisticMessage));
      setIsSubmitting(true);
      setState("CRITIC_PROCESSING");
      setStatusText("Critic 正在思考…");
      setError(null);

      try {
        await submitStudentMessage(sessionId, contentMarkdown, messageId);
        setMessages((current) =>
          current.map((message) =>
            message.id === messageId
              ? { ...message, deliveryStatus: "sent" }
              : message,
          ),
        );
      } catch (reason) {
        setMessages((current) =>
          current.map((message) =>
            message.id === messageId
              ? { ...message, deliveryStatus: "failed" }
              : message,
          ),
        );
        setIsSubmitting(false);
        setError(reason instanceof Error ? reason.message : "消息发送失败");
        setStatusText("消息发送失败");
      }
    },
    [isSubmitting, sessionId],
  );

  const startSession = useCallback(
    async (moduleId: string) => {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
      clearSessionView();
      setIsLoading(true);
      setError(null);
      setStatusText("正在准备测试…");
      try {
        const session = await createLearningSession(moduleId);
        window.localStorage.setItem(SESSION_STORAGE_KEY, session.session_id);
        applySession(session);
        setStatusText("题目已准备好");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "无法创建学习会话");
        setStatusText("后端连接失败");
      } finally {
        setIsLoading(false);
      }
    },
    [applySession, clearSessionView],
  );

  const restartSession = useCallback(async () => {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    clearSessionView();
    setIsLoading(false);
    setError(null);
    setStatusText("请选择测试开始");
  }, [clearSessionView]);

  const placeholder = useMemo(() => statePlaceholder(state), [state]);
  const composerDisabled =
    isLoading ||
    isSubmitting ||
    !sessionId ||
    state === "SESSION_ENDED" ||
    state === "QUESTION_INVALID" ||
    state === "QUESTION_GENERATING" ||
    state === "QUESTION_GENERATION_FAILED" ||
    state === "ROUND_FINALIZING";

  return {
    sessionId,
    state,
    messages,
    knowledgeNodes,
    errorNodes,
    completedQuestionCount,
    chapterQuestionSet,
    isLoading,
    isSubmitting,
    isConnected,
    statusText,
    error,
    placeholder,
    composerDisabled,
    startSession,
    sendStudentMessage,
    restartSession,
  };
}
