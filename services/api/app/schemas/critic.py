from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import StrictModel
from app.schemas.question import QuestionPacket, RecentQuestion

Intent = Literal[
    "answer_attempt",
    "student_uncertain",
    "clarification_question",
    "challenge_evaluation",
    "request_example",
    "concept_extension",
    "acknowledgement",
    "next_question",
    "answer_and_question",
    "request_summary",
    "end_session",
    "off_topic",
    "ambiguous",
]


class QuestionReview(StrictModel):
    status: Literal["approved", "needs_revision", "invalid"]
    quality_score: float = Field(ge=0.0, le=1.0)
    issues: List[str]
    grading_notes: Optional[str] = None

    @model_validator(mode="after")
    def require_issues_when_not_approved(self) -> "QuestionReview":
        if self.status != "approved" and not self.issues:
            raise ValueError("needs_revision and invalid reviews require at least one issue")
        return self


class QuestionReviewContext(StrictModel):
    question_packet: QuestionPacket
    expected_knowledge_node_ids: List[str] = Field(default_factory=list)
    expected_difficulty_min: int = Field(default=1, ge=1, le=5)
    expected_difficulty_max: int = Field(default=5, ge=1, le=5)
    recent_questions: List[RecentQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_difficulty_range(self) -> "QuestionReviewContext":
        if self.expected_difficulty_min > self.expected_difficulty_max:
            raise ValueError("expected_difficulty_min must not exceed max")
        return self


class QuestionReviewExecution(StrictModel):
    status: Literal["completed", "failed"]
    review: Optional[QuestionReview] = None
    retry_count: int = Field(ge=0, le=1)
    error: Optional[str] = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "QuestionReviewExecution":
        if self.status == "completed" and self.review is None:
            raise ValueError("completed review execution requires review")
        if self.status == "failed" and not self.error:
            raise ValueError("failed review execution requires error")
        return self


class QuestionReviewDecision(StrictModel):
    question_id: UUID
    review_status: Literal["approved", "needs_revision", "invalid", "review_failed"]
    question_status: Literal[
        "active",
        "active_with_review_notes",
        "invalid",
        "review_failed",
    ]
    action: Literal[
        "continue_question",
        "continue_with_review_notes",
        "replace_question",
        "explain_invalid_and_replace",
        "pause_for_review_retry",
    ]
    allow_graph_updates: bool
    should_generate_replacement: bool
    student_visible_reply_markdown: Optional[str] = None


class KnowledgeGraphUpdate(StrictModel):
    node_id: str
    evidence: Literal["positive", "partial", "negative", "none"]
    strength: float = Field(ge=0.0, le=1.0)
    reason: str


class ErrorGraphUpdate(StrictModel):
    error_id: str
    action: Literal["activate", "strengthen", "weaken", "resolve", "relapse", "none"]
    strength: float = Field(ge=0.0, le=1.0)
    reason: str


class CriticConversationMessage(StrictModel):
    role: Literal["questioner", "student", "critic", "system"]
    content_markdown: str = Field(min_length=1)
    critic_intent: Optional[Intent] = None


class CriticTurnContext(StrictModel):
    session_state: Literal["QUESTION_ACTIVE", "FEEDBACK_DISCUSSION"]
    question_packet: QuestionPacket
    question_review: QuestionReview
    conversation_history: List[CriticConversationMessage] = Field(default_factory=list)
    student_message: str = Field(min_length=1, max_length=20_000)
    previous_critic_result: Optional["CriticTurnResult"] = None
    candidate_question_status: Optional[
        Literal["generating", "provisional", "ready", "stale", "failed"]
    ] = None


class CriticTurnResult(StrictModel):
    intent: Intent
    intent_confidence: float = Field(ge=0.0, le=1.0)
    student_visible_reply_markdown: str = Field(min_length=1)
    verdict: Literal[
        "correct",
        "partially_correct",
        "incorrect",
        "student_uncertain",
        "critic_uncertain",
        "invalid_question",
        "not_applicable",
    ]
    round_action: Literal[
        "wait_for_answer",
        "continue_discussion",
        "show_feedback",
        "finalize_round",
        "replace_question",
        "end_session",
    ]
    provisional_knowledge_updates: List[KnowledgeGraphUpdate]
    provisional_error_updates: List[ErrorGraphUpdate]
    should_prepare_next_question: bool
    should_invalidate_candidate_question: bool

    @model_validator(mode="after")
    def validate_safe_update_rules(self) -> "CriticTurnResult":
        if self.verdict in {"critic_uncertain", "invalid_question", "not_applicable"}:
            if self.provisional_knowledge_updates or self.provisional_error_updates:
                raise ValueError(
                    "uncertain, invalid, and not-applicable results cannot update graphs"
                )
        if self.intent == "student_uncertain":
            if self.verdict != "student_uncertain":
                raise ValueError("student_uncertain intent requires matching verdict")
            if any(
                update.evidence not in {"none"}
                for update in self.provisional_knowledge_updates
            ):
                raise ValueError(
                    "student uncertainty cannot be treated as negative knowledge evidence"
                )
            if any(
                update.action not in {"none"}
                for update in self.provisional_error_updates
            ):
                raise ValueError(
                    "student uncertainty cannot activate a specific error"
                )
        if self.intent == "next_question" and self.round_action != "finalize_round":
            raise ValueError("next_question intent must finalize the round")
        if self.round_action == "finalize_round" and self.intent != "next_question":
            raise ValueError("only next_question intent can finalize the round")
        if self.intent == "end_session" and self.round_action != "end_session":
            raise ValueError("end_session intent must end the session")
        return self


class CriticTurnExecution(StrictModel):
    status: Literal["completed", "failed"]
    result: CriticTurnResult
    retry_count: int = Field(ge=0, le=1)
    error: Optional[str] = None

    @model_validator(mode="after")
    def require_error_for_failed_turn(self) -> "CriticTurnExecution":
        if self.status == "failed" and not self.error:
            raise ValueError("failed turn execution requires error")
        return self


class DiscussionSummary(StrictModel):
    question_id: UUID
    original_verdict: Literal[
        "correct",
        "partially_correct",
        "incorrect",
        "student_uncertain",
        "critic_uncertain",
        "invalid_question",
        "not_applicable",
    ]
    final_verdict: Literal[
        "correct",
        "partially_correct",
        "incorrect",
        "student_uncertain",
        "critic_uncertain",
        "invalid_question",
        "not_applicable",
    ]
    diagnosis_changed: bool
    discussion_resolved: bool
    confirmed_knowledge: List[str]
    remaining_knowledge_gaps: List[str]
    active_errors: List[str]
    resolved_errors: List[str]
    final_knowledge_updates: List[KnowledgeGraphUpdate]
    final_error_updates: List[ErrorGraphUpdate]
    next_question_guidance: Dict[str, Any]

    @model_validator(mode="after")
    def validate_summary_updates(self) -> "DiscussionSummary":
        if self.final_verdict in {
            "critic_uncertain",
            "invalid_question",
            "not_applicable",
        } and (self.final_knowledge_updates or self.final_error_updates):
            raise ValueError("unreliable final verdict cannot update graphs")
        if self.diagnosis_changed and self.original_verdict == self.final_verdict:
            raise ValueError("diagnosis_changed requires a different final verdict")
        return self


class DiscussionSummaryContext(StrictModel):
    question_packet: QuestionPacket
    question_review: QuestionReview
    conversation_history: List[CriticConversationMessage]
    turn_results: List[CriticTurnResult]
    provisional_candidate_question: Optional[QuestionPacket] = None


class DiscussionSummaryExecution(StrictModel):
    status: Literal["completed", "failed"]
    summary: Optional[DiscussionSummary] = None
    retry_count: int = Field(ge=0, le=1)
    error: Optional[str] = None

    @model_validator(mode="after")
    def validate_summary_execution(self) -> "DiscussionSummaryExecution":
        if self.status == "completed" and self.summary is None:
            raise ValueError("completed summary execution requires summary")
        if self.status == "failed" and not self.error:
            raise ValueError("failed summary execution requires error")
        return self
