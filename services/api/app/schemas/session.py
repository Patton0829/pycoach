from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.base import StrictModel
from app.schemas.chapter_plan import ChapterQuestionSetSummary
from app.schemas.graph import ErrorNodeSummary, KnowledgeNodeSummary


class SessionState(str, Enum):
    SESSION_CREATED = "SESSION_CREATED"
    QUESTION_GENERATING = "QUESTION_GENERATING"
    QUESTION_ACTIVE = "QUESTION_ACTIVE"
    USER_MESSAGE_RECEIVED = "USER_MESSAGE_RECEIVED"
    CRITIC_PROCESSING = "CRITIC_PROCESSING"
    FEEDBACK_DISCUSSION = "FEEDBACK_DISCUSSION"
    ROUND_FINALIZING = "ROUND_FINALIZING"
    NEXT_QUESTION_READY = "NEXT_QUESTION_READY"
    QUESTION_INVALID = "QUESTION_INVALID"
    QUESTION_GENERATION_FAILED = "QUESTION_GENERATION_FAILED"
    CRITIC_OUTPUT_INVALID = "CRITIC_OUTPUT_INVALID"
    CANDIDATE_STALE = "CANDIDATE_STALE"
    SESSION_ENDED = "SESSION_ENDED"


class CandidateQuestionState(str, Enum):
    generating = "generating"
    provisional = "provisional"
    ready = "ready"
    stale = "stale"
    failed = "failed"


class CreateSessionRequest(StrictModel):
    learner_id: str
    module: str


class SessionResponse(StrictModel):
    session_id: UUID
    state: SessionState
    messages: List[dict]
    current_question_id: Optional[UUID] = None
    current_question: Optional[dict] = None
    knowledge_graph: List[KnowledgeNodeSummary] = Field(default_factory=list)
    error_graph: List[ErrorNodeSummary] = Field(default_factory=list)
    completed_question_count: int = 0
    chapter_question_set: Optional[ChapterQuestionSetSummary] = None
