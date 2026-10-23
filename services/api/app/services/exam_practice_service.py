"""Select reviewed bank questions for an explicitly requested exam session.

This service is deterministic retrieval and persistence, not a runtime Agent.
It never generates a question or executes submitted/source Python code. Database
transactions, including these flushed snapshots, belong to the caller.
"""

from collections import defaultdict
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    AssessmentEvidence,
    BankQuestion,
    BankQuestionRevision,
    ChapterQuestionSet,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    QuestionKnowledgeMapping,
    QuestionReviewRecord,
    SourceDocument,
)
from app.schemas.assessment import assessment_metrics
from app.schemas.exam import ExamPaperSummary
from app.schemas.question import QuestionPacket

EXAM_MODULE_ID = "python_exam_practice"


class ExamPracticeService:
    def __init__(self, database: Session) -> None:
        self.database = database

    def _latest_revisions(self, source_document_id: str | None = None):
        latest = (
            select(
                BankQuestionRevision.bank_question_id.label("bank_question_id"),
                func.max(BankQuestionRevision.revision).label("revision"),
            )
            .group_by(BankQuestionRevision.bank_question_id)
            .subquery()
        )
        statement = (
            select(BankQuestionRevision, BankQuestion.source_document_id)
            .join(latest, and_(
                latest.c.bank_question_id == BankQuestionRevision.bank_question_id,
                latest.c.revision == BankQuestionRevision.revision,
            ))
            .join(BankQuestion, BankQuestion.id == BankQuestionRevision.bank_question_id)
            .order_by(BankQuestion.source_document_id, BankQuestionRevision.bank_question_id)
        )
        if source_document_id is not None:
            statement = statement.where(BankQuestion.source_document_id == source_document_id)
        return self.database.execute(statement).all()

    def _assessed_mappings(
        self, revisions: list[BankQuestionRevision]
    ) -> dict[str, list[QuestionKnowledgeMapping]]:
        result: dict[str, list[QuestionKnowledgeMapping]] = defaultdict(list)
        if not revisions:
            return result
        mappings = self.database.scalars(
            select(QuestionKnowledgeMapping)
            .where(
                QuestionKnowledgeMapping.bank_question_revision_id.in_(
                    [revision.id for revision in revisions]
                ),
                QuestionKnowledgeMapping.role == "assessed",
            )
            .order_by(
                QuestionKnowledgeMapping.is_primary.desc(),
                QuestionKnowledgeMapping.knowledge_node_id,
            )
        ).all()
        for mapping in mappings:
            result[mapping.bank_question_revision_id].append(mapping)
        return result

    def approved_revisions(
        self, source_document_id: str | None = None
    ) -> list[BankQuestionRevision]:
        """Only current, approved, mapped identities; revoked newer content wins."""
        if source_document_id is not None and self.database.get(
            SourceDocument, source_document_id
        ) is None:
            raise ValueError("Exam source document not found")
        revisions = [
            revision for revision, _ in self._latest_revisions(source_document_id)
            if revision.review_status == "approved"
        ]
        mappings = self._assessed_mappings(revisions)
        return [
            revision for revision in revisions
            if 1 <= len(mappings[revision.id]) <= 2
            and sum(mapping.is_primary for mapping in mappings[revision.id]) == 1
            and all(mapping.assessment_criterion.strip() for mapping in mappings[revision.id])
        ]

    def list_papers(self) -> list[ExamPaperSummary]:
        documents = self.database.scalars(
            select(SourceDocument).order_by(SourceDocument.created_at, SourceDocument.id)
        ).all()
        latest_by_source = defaultdict(list)
        for revision, source_id in self._latest_revisions():
            latest_by_source[source_id].append(revision)
        approved_ids = {revision.id for revision in self.approved_revisions()}
        summaries = []
        for document in documents:
            latest = latest_by_source[document.id]
            available = [revision for revision in latest if revision.id in approved_ids]
            summaries.append(ExamPaperSummary(
                id=document.id,
                title=document.title,
                document_type=document.document_type,
                exam_year=document.exam_year,
                available_question_count=len(available),
                excluded_question_count=len(latest) - len(available),
                question_types=sorted({revision.question_type for revision in available}),
            ))
        return summaries

    def create_question(
        self, session_id: str, round_id: str, status: str = "active"
    ) -> Question | None:
        """Create one snapshot from this session's fixed pool; return None at end."""
        session = self.database.scalar(
            select(LearningSession).where(LearningSession.id == session_id).with_for_update()
        )
        learning_round = self.database.get(LearningRound, round_id)
        if session is None or learning_round is None or learning_round.session_id != session_id:
            raise ValueError("Exam round does not belong to the session")
        plan = self.database.scalar(
            select(ChapterQuestionSet).where(ChapterQuestionSet.session_id == session_id)
        )
        if plan is None or plan.chapter_id != EXAM_MODULE_ID or plan.blueprint_json.get("mode") != "exam":
            raise ValueError("An explicit exam session plan is required")
        source_id = plan.blueprint_json.get("source_document_id")
        pool_ids = set(plan.blueprint_json.get("bank_revision_ids", []))
        candidates = [
            revision for revision in self.approved_revisions(source_id)
            if revision.id in pool_ids
        ]
        used_ids = set(self.database.scalars(
            select(BankQuestionRevision.bank_question_id)
            .join(Question, Question.bank_question_revision_id == BankQuestionRevision.id)
            .where(Question.session_id == session_id)
        ).all())
        candidates = [revision for revision in candidates if revision.bank_question_id not in used_ids]
        if not candidates:
            return None
        mappings = self._assessed_mappings(candidates)
        node_ids = {
            mapping.knowledge_node_id for values in mappings.values() for mapping in values
        }
        profiles = {
            profile.knowledge_node_id: profile for profile in self.database.scalars(
                select(LearnerKnowledgeNode).where(
                    LearnerKnowledgeNode.learner_id == session.learner_id,
                    LearnerKnowledgeNode.knowledge_node_id.in_(node_ids),
                )
            ).all()
        }
        previously_counted = set(self.database.scalars(
            select(AssessmentEvidence.bank_question_id).where(
                AssessmentEvidence.learner_id == session.learner_id,
                AssessmentEvidence.counted.is_(True),
                AssessmentEvidence.bank_question_id.is_not(None),
            )
        ).all())

        def priority(revision: BankQuestionRevision):
            needs = []
            target_difficulties = []
            counts = []
            for mapping in mappings[revision.id]:
                profile = profiles.get(mapping.knowledge_node_id)
                n = profile.evaluated_question_count if profile else 0
                c = profile.correct_question_count if profile else 0
                metrics = assessment_metrics(n, c)
                accuracy = metrics.accuracy
                needs.append(max(1 - metrics.sample_coverage, 1 - accuracy if accuracy is not None else 1))
                if accuracy is None:
                    target = 1
                elif n < 20:
                    target = 2 if accuracy >= 0.7 else 1
                elif accuracy >= 0.8:
                    target = 4
                elif accuracy >= 0.5:
                    target = 3
                else:
                    target = 1
                target_difficulties.append(target)
                counts.append(n)
            target_difficulty = sum(target_difficulties) / len(target_difficulties)
            return (
                revision.bank_question_id in previously_counted,
                -max(needs),
                abs(revision.difficulty - target_difficulty),
                sum(counts),
                revision.bank_question_id,
            )

        revision = min(candidates, key=priority)
        packet = QuestionPacket.model_validate({
            "question_id": uuid4(),
            "question_type": revision.question_type,
            "difficulty": revision.difficulty,
            "knowledge_node_ids": [mapping.knowledge_node_id for mapping in mappings[revision.id]],
            "target_error_ids": revision.target_error_ids,
            "pedagogical_strategy": "authentic_exam_practice",
            "student_content": revision.student_content_json,
            "critic_content": revision.critic_content_json,
        })
        question = Question(
            id=str(packet.question_id), session_id=session_id, round_id=round_id,
            bank_question_revision_id=revision.id,
            question_type=packet.question_type, difficulty=packet.difficulty,
            student_content_json=packet.student_content.model_dump(mode="json"),
            critic_content_json=packet.critic_content.model_dump(mode="json"),
            knowledge_node_ids=packet.knowledge_node_ids,
            target_error_ids=packet.target_error_ids,
            pedagogical_strategy=packet.pedagogical_strategy, status=status,
        )
        self.database.add(question)
        self.database.flush()
        self.database.add(QuestionReviewRecord(
            question_id=question.id, status="approved", quality_score=1.0,
            issues_json=[], grading_notes=packet.critic_content.ambiguity_notes,
        ))
        self.database.flush()
        return question
