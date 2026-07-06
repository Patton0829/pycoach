export type MessageRole = "questioner" | "student" | "critic" | "system";

export interface TimelineMessage {
  id: string;
  role: MessageRole;
  contentMarkdown: string;
  createdAt?: string;
  deliveryStatus?: "sending" | "streaming" | "sent" | "failed";
}

export interface GraphNode {
  id: string;
  label: string;
  displayStatus: string;
}

export interface ApiMessage {
  id: string;
  role: MessageRole;
  content_markdown: string;
  created_at: string;
}

export interface KnowledgeNodeSummary {
  node_id: string;
  name: string;
  display_status: string;
}

export interface ErrorNodeSummary {
  error_id: string;
  name: string;
  display_status: string;
}

export interface CurrentQuestion {
  question_id: string;
  markdown: string;
  input_hint: string | null;
}

export interface ChapterQuestionSetSummary {
  chapter_id: string;
  chapter_title: string;
  target_question_count: number;
  current_question_slot: number;
  learner_level: "novice" | "intermediate" | "advanced";
  average_mastery: number;
}

export type SessionState =
  | "SESSION_CREATED"
  | "QUESTION_GENERATING"
  | "QUESTION_ACTIVE"
  | "USER_MESSAGE_RECEIVED"
  | "CRITIC_PROCESSING"
  | "FEEDBACK_DISCUSSION"
  | "ROUND_FINALIZING"
  | "NEXT_QUESTION_READY"
  | "QUESTION_INVALID"
  | "QUESTION_GENERATION_FAILED"
  | "CRITIC_OUTPUT_INVALID"
  | "CANDIDATE_STALE"
  | "SESSION_ENDED";

export interface LearningSessionResponse {
  session_id: string;
  state: SessionState;
  messages: ApiMessage[];
  current_question_id: string | null;
  current_question: CurrentQuestion | null;
  knowledge_graph: KnowledgeNodeSummary[];
  error_graph: ErrorNodeSummary[];
  completed_question_count: number;
  chapter_question_set: ChapterQuestionSetSummary | null;
}

export interface MessageAcceptedResponse {
  message_id: string;
  status: "processing";
  session_state: "CRITIC_PROCESSING";
}

export type SessionSocketEvent =
  | { type: "connection_ready"; session_id: string }
  | {
      type: "question_ready";
      session_id: string;
      payload: {
        question_id: string;
        markdown: string;
        input_hint: string | null;
      };
    }
  | {
      type: "question_invalid";
      session_id: string;
      payload: { student_visible_reason_markdown: string };
    }
  | {
      type: "critic_reply_ready";
      session_id: string;
      payload: {
        message: ApiMessage;
        session_state: SessionState;
        stream_id?: string | null;
      };
    }
  | {
      type: "message_stream_started";
      session_id: string;
      payload: {
        stream_id: string;
        role: "critic";
      };
    }
  | {
      type: "message_stream_delta";
      session_id: string;
      payload: {
        stream_id: string;
        role: "critic";
        delta: string;
      };
    }
  | {
      type: "message_stream_reset";
      session_id: string;
      payload: {
        stream_id: string;
        role: "critic";
      };
    }
  | {
      type: "candidate_question_ready" | "candidate_question_stale";
      session_id: string;
    }
  | {
      type: "session_summary_ready";
      session_id: string;
      payload: {
        completed_question_count: number;
        graphs_changed: boolean;
      };
    };

export function toTimelineMessage(message: ApiMessage): TimelineMessage {
  return {
    id: message.id,
    role: message.role,
    contentMarkdown: message.content_markdown,
    createdAt: message.created_at,
    deliveryStatus: "sent",
  };
}

export function selectCurrentRoundMessages(
  messages: TimelineMessage[],
): TimelineMessage[] {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === "questioner") {
      return messages.slice(index);
    }
  }
  return messages;
}

export function toKnowledgeGraphNode(
  node: KnowledgeNodeSummary,
): GraphNode {
  return {
    id: node.node_id,
    label: node.name,
    displayStatus: node.display_status,
  };
}

export function toErrorGraphNode(node: ErrorNodeSummary): GraphNode {
  return {
    id: node.error_id,
    label: node.name,
    displayStatus: node.display_status,
  };
}
