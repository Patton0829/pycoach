from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.base import StrictModel

QuestionType = Literal[
    "multiple_choice",
    "code_blank",
    "output_prediction",
    "short_explanation",
]


class StudentQuestionContent(StrictModel):
    markdown: str = Field(min_length=1)
    input_hint: Optional[str] = None


class QuestionCriticContent(StrictModel):
    learning_objective: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    acceptable_answers: List[str]
    grading_rubric: Dict[str, str]
    expected_reasoning: str = Field(min_length=1)
    ambiguity_notes: Optional[str] = None


class QuestionPacket(StrictModel):
    question_id: UUID
    question_type: QuestionType
    difficulty: int = Field(ge=1, le=5)
    knowledge_node_ids: List[str] = Field(min_length=1, max_length=2)
    target_error_ids: List[str]
    pedagogical_strategy: str = Field(min_length=1)
    student_content: StudentQuestionContent
    critic_content: QuestionCriticContent


class PersonalKnowledgeState(StrictModel):
    node_id: str
    mastery: float = Field(ge=0.0, le=1.0)
    status: Literal[
        "not_started",
        "learning",
        "weak",
        "mastered",
        "needs_review",
    ]


class LearnerErrorState(StrictModel):
    error_id: str
    severity: float = Field(ge=0.0, le=1.0)
    status: Literal["new", "active", "improving", "resolved", "relapsed"]


class RecentQuestion(StrictModel):
    question_id: UUID
    question_type: QuestionType
    markdown: str
    knowledge_node_ids: List[str] = Field(default_factory=list)


class RecentAttempt(StrictModel):
    question_id: UUID
    verdict: str
    knowledge_node_ids: List[str] = Field(default_factory=list)
    target_error_ids: List[str] = Field(default_factory=list)


class CandidateConstraints(StrictModel):
    allowed_question_types: List[QuestionType] = Field(
        default_factory=lambda: [
            "multiple_choice",
            "code_blank",
            "output_prediction",
            "short_explanation",
        ],
        min_length=1,
    )
    preferred_question_type: Optional[QuestionType] = None
    allowed_knowledge_node_ids: List[str] = Field(default_factory=list)
    allowed_error_ids: List[str] = Field(default_factory=list)
    max_code_lines: int = Field(default=20, ge=1, le=20)
    max_knowledge_nodes: int = Field(default=2, ge=1, le=2)
    avoid_question_ids: List[UUID] = Field(default_factory=list)
    avoid_markdown: List[str] = Field(default_factory=list)


class QuestionerContext(StrictModel):
    global_knowledge_graph: Dict[str, Any]
    personal_knowledge_graph: List[PersonalKnowledgeState]
    error_graph: List[LearnerErrorState]
    recent_questions: List[RecentQuestion]
    recent_attempts: List[RecentAttempt]
    critic_summary: Dict[str, Any]
    teaching_policy: Dict[str, Any]
    candidate_constraints: CandidateConstraints


class QuestionGenerationResult(StrictModel):
    packet: QuestionPacket
    source: Literal["model", "seed_fallback"]
    retry_count: int = Field(ge=0, le=1)
