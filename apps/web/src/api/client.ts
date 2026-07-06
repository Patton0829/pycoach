import type {
  ErrorNodeSummary,
  KnowledgeNodeSummary,
  LearningSessionResponse,
  MessageAcceptedResponse,
} from "../types/session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const DEMO_LEARNER_ID = "demo_user";

interface KnowledgeGraphResponse {
  learner_id: string;
  nodes: KnowledgeNodeSummary[];
}

interface ErrorGraphResponse {
  learner_id: string;
  nodes: ErrorNodeSummary[];
}

async function requestJson<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      `API request failed (${response.status}): ${detail || response.statusText}`,
    );
  }
  return response.json() as Promise<T>;
}

export function createLearningSession(
  moduleId: string,
): Promise<LearningSessionResponse> {
  return requestJson("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      learner_id: DEMO_LEARNER_ID,
      module: moduleId,
    }),
  });
}

export function getLearningSession(
  sessionId: string,
): Promise<LearningSessionResponse> {
  return requestJson(`/api/sessions/${sessionId}`);
}

export function submitStudentMessage(
  sessionId: string,
  content: string,
  clientMessageId: string,
): Promise<MessageAcceptedResponse> {
  return requestJson(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
      client_message_id: clientMessageId,
    }),
  });
}

export function getKnowledgeGraph(
  learnerId = DEMO_LEARNER_ID,
): Promise<KnowledgeGraphResponse> {
  return requestJson(`/api/learners/${learnerId}/knowledge-graph`);
}

export function getErrorGraph(
  learnerId = DEMO_LEARNER_ID,
): Promise<ErrorGraphResponse> {
  return requestJson(`/api/learners/${learnerId}/error-graph`);
}
