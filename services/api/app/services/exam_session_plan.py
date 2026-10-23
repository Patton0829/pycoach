"""A fixed source pool for an explicitly selected exam session."""

from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ChapterQuestionSet, LearnerKnowledgeNode, LearningSession, QuestionKnowledgeMapping
from app.schemas.base import StrictModel
from app.services.chapter_questioning_service import EXAM_ASSESSMENT_ID


class ExamSessionPlan(StrictModel):
    mode: Literal["exam"] = "exam"
    source_document_id: str | None = None
    bank_revision_ids: list[str] = Field(min_length=1, max_length=50)
    knowledge_node_ids: list[str]
    selection_strategy: str = "unseen_then_sample_coverage_accuracy_and_difficulty"


def is_exam_session(database: Session, session_id: str) -> bool:
    return database.scalar(select(ChapterQuestionSet.chapter_id).where(
        ChapterQuestionSet.session_id == session_id,
    )) == EXAM_ASSESSMENT_ID


def create_exam_session_plan(
    database: Session, session: LearningSession, source_document_id: str | None,
) -> ChapterQuestionSet:
    from app.services.exam_practice_service import ExamPracticeService

    revisions = ExamPracticeService(database).approved_revisions(source_document_id)[:50]
    if not revisions:
        raise ValueError("当前试卷暂无已审核通过的真题，请选择其他试卷或稍后再试。")
    revision_ids = [revision.id for revision in revisions]
    target_ids = sorted(set(database.scalars(select(QuestionKnowledgeMapping.knowledge_node_id).where(
        QuestionKnowledgeMapping.bank_question_revision_id.in_(revision_ids),
        QuestionKnowledgeMapping.role == "assessed",
    )).all()))
    states = database.scalars(select(LearnerKnowledgeNode).where(
        LearnerKnowledgeNode.learner_id == session.learner_id,
        LearnerKnowledgeNode.knowledge_node_id.in_(target_ids),
    )).all()
    scores = {item.knowledge_node_id: item.correct_question_count / max(20, item.evaluated_question_count)
              for item in states}
    average = sum(scores.get(node_id, 0.0) for node_id in target_ids) / max(len(target_ids), 1)
    level = "novice" if average < 0.4 else "intermediate" if average < 0.75 else "advanced"
    plan = ExamSessionPlan(
        source_document_id=source_document_id, bank_revision_ids=revision_ids,
        knowledge_node_ids=target_ids,
    )
    record = ChapterQuestionSet(
        session_id=session.id, learner_id=session.learner_id,
        chapter_id=EXAM_ASSESSMENT_ID, chapter_title="真题测试",
        target_question_count=len(revisions), learner_level=level,
        average_mastery=average, blueprint_json=plan.model_dump(mode="json"),
    )
    database.add(record)
    database.flush()
    return record
