"""Explicit allowlist of question information that may reach a student."""

from typing import Literal

from pydantic import Field

from app.schemas.base import StrictModel


class PublicKnowledgePoint(StrictModel):
    id: str
    name: str


class PublicQuestionSource(StrictModel):
    title: str
    document_type: Literal["sample_exam", "past_exam"]
    exam_year: int | None = None
    question_number: str
    pdf_pages: list[int]


class PublicQuestionMetadata(StrictModel):
    difficulty: int = Field(ge=1, le=5)
    knowledge_points: list[PublicKnowledgePoint] = Field(default_factory=list)
    source: PublicQuestionSource | None = None
