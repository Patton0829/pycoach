"""Validated progress values derived from finalized, countable assessment evidence."""

from typing import Literal, Optional

from pydantic import Field

from app.schemas.base import StrictModel

SCORE_POLICY_VERSION = "correct_over_max_20_v1"
ASSESSMENT_SAMPLE_TARGET = 20


class AssessmentMetrics(StrictModel):
    evaluated_question_count: int = Field(ge=0)
    correct_question_count: int = Field(ge=0)
    assessment_stage: Literal["unassessed", "collecting", "sample_ready"]
    assessment_score: float = Field(ge=0.0, le=1.0)
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sample_coverage: float = Field(ge=0.0, le=1.0)


def assessment_metrics(evaluated_count: int, correct_count: int) -> AssessmentMetrics:
    """The pre-20 score includes sample progress; accuracy remains separately visible."""
    if evaluated_count < 0 or not 0 <= correct_count <= evaluated_count:
        raise ValueError("Assessment counts must satisfy 0 <= correct <= evaluated")
    return AssessmentMetrics(
        evaluated_question_count=evaluated_count,
        correct_question_count=correct_count,
        assessment_stage=(
            "unassessed" if evaluated_count == 0
            else "collecting" if evaluated_count < ASSESSMENT_SAMPLE_TARGET
            else "sample_ready"
        ),
        assessment_score=correct_count / max(ASSESSMENT_SAMPLE_TARGET, evaluated_count),
        accuracy=correct_count / evaluated_count if evaluated_count else None,
        sample_coverage=min(evaluated_count / ASSESSMENT_SAMPLE_TARGET, 1.0),
    )
