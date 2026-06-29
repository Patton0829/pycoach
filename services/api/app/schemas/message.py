from datetime import datetime
from typing import Literal, Optional, Union
from uuid import UUID

from pydantic import Field

from app.schemas.base import StrictModel
from app.schemas.session import SessionState


class StudentMessageRequest(StrictModel):
    content: str = Field(min_length=1, max_length=20_000)
    client_message_id: Optional[UUID] = None


class StudentVisibleMessage(StrictModel):
    id: UUID
    role: Literal["questioner", "student", "critic", "system"]
    content_markdown: str
    created_at: datetime


class MessageAcceptedResponse(StrictModel):
    message_id: UUID
    status: Literal["processing"]
    session_state: SessionState


class ConnectionReadyEvent(StrictModel):
    type: Literal["connection_ready"] = "connection_ready"
    session_id: UUID


class QuestionReadyPayload(StrictModel):
    question_id: UUID
    markdown: str
    input_hint: Optional[str] = None


class QuestionReadyEvent(StrictModel):
    type: Literal["question_ready"] = "question_ready"
    session_id: UUID
    payload: QuestionReadyPayload


class QuestionInvalidPayload(StrictModel):
    student_visible_reason_markdown: str


class QuestionInvalidEvent(StrictModel):
    type: Literal["question_invalid"] = "question_invalid"
    session_id: UUID
    payload: QuestionInvalidPayload


class CriticReplyReadyPayload(StrictModel):
    message: StudentVisibleMessage
    session_state: SessionState
    stream_id: Optional[UUID] = None


class CriticReplyReadyEvent(StrictModel):
    type: Literal["critic_reply_ready"] = "critic_reply_ready"
    session_id: UUID
    payload: CriticReplyReadyPayload


class CandidateQuestionStatusEvent(StrictModel):
    type: Literal["candidate_question_ready", "candidate_question_stale"]
    session_id: UUID


class MessageStreamStartedPayload(StrictModel):
    stream_id: UUID
    role: Literal["critic"]


class MessageStreamStartedEvent(StrictModel):
    type: Literal["message_stream_started"] = "message_stream_started"
    session_id: UUID
    payload: MessageStreamStartedPayload


class MessageStreamDeltaPayload(StrictModel):
    stream_id: UUID
    role: Literal["critic"]
    delta: str = Field(min_length=1)


class MessageStreamDeltaEvent(StrictModel):
    type: Literal["message_stream_delta"] = "message_stream_delta"
    session_id: UUID
    payload: MessageStreamDeltaPayload


class MessageStreamResetPayload(StrictModel):
    stream_id: UUID
    role: Literal["critic"]


class MessageStreamResetEvent(StrictModel):
    type: Literal["message_stream_reset"] = "message_stream_reset"
    session_id: UUID
    payload: MessageStreamResetPayload


class SessionSummaryReadyPayload(StrictModel):
    completed_question_count: int = Field(ge=0)
    graphs_changed: bool


class SessionSummaryReadyEvent(StrictModel):
    type: Literal["session_summary_ready"] = "session_summary_ready"
    session_id: UUID
    payload: SessionSummaryReadyPayload


SessionSocketEvent = Union[
    ConnectionReadyEvent,
    QuestionReadyEvent,
    QuestionInvalidEvent,
    CriticReplyReadyEvent,
    CandidateQuestionStatusEvent,
    MessageStreamStartedEvent,
    MessageStreamDeltaEvent,
    MessageStreamResetEvent,
    SessionSummaryReadyEvent,
]
