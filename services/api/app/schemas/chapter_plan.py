from typing import Literal

from pydantic import Field

from app.schemas.base import StrictModel
from app.schemas.question import QuestionType

LearnerLevel = Literal["novice", "intermediate", "advanced"]


class ActiveErrorPriority(StrictModel):
    error_id: str
    severity: float = Field(ge=0.0, le=1.0)
    status: str


class ChapterQuestionBlueprintItem(StrictModel):
    slot: int = Field(ge=1, le=50)
    question_type: QuestionType
    difficulty: int = Field(ge=1, le=5)
    cognitive_goal: str = Field(min_length=1)
    target_knowledge_node_ids: list[str] = Field(min_length=1, max_length=2)
    target_error_ids: list[str] = Field(default_factory=list, max_length=2)
    pedagogical_strategy: str = Field(min_length=1)
    prompt_brief: str = Field(min_length=1)
    quality_checks: list[str] = Field(default_factory=list)


class ChapterQuestionSetPlan(StrictModel):
    chapter_id: str
    chapter_title: str
    question_count: int = Field(default=10, ge=1, le=50)
    learner_level: LearnerLevel
    average_mastery: float = Field(ge=0.0, le=1.0)
    active_error_priorities: list[ActiveErrorPriority] = Field(default_factory=list)
    core_principles: list[str] = Field(default_factory=list)
    questions: list[ChapterQuestionBlueprintItem] = Field(min_length=1, max_length=50)
    set_level_quality_checks: list[str] = Field(default_factory=list)


class ChapterQuestionSetSummary(StrictModel):
    chapter_id: str
    chapter_title: str
    target_question_count: int = Field(ge=1, le=50)
    current_question_slot: int = Field(ge=1, le=50)
    learner_level: LearnerLevel
