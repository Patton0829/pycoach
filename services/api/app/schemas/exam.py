"""Public exam catalogue; intentionally contains no answer or file location."""

from typing import Literal

from pydantic import Field

from app.schemas.base import StrictModel
from app.schemas.question_bank import BankQuestionType


class ExamPaperSummary(StrictModel):
    id: str
    title: str
    document_type: Literal["sample_exam", "past_exam"]
    exam_year: int | None = None
    available_question_count: int = Field(ge=0)
    excluded_question_count: int = Field(ge=0)
    question_types: list[BankQuestionType] = Field(default_factory=list)
