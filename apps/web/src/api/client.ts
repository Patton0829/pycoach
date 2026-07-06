import type {
  LearningSessionResponse,
  MessageAcceptedResponse,
} from "../types/session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
      learner_id: "demo_user",
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
