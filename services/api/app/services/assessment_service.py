"""Deterministic final assessment accounting; this service does not call an LLM."""

from datetime import datetime
from hashlib import sha256
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    AssessmentEvidence,
    BankQuestionRevision,
    ConversationMessage,
    GraphUpdateEvent,
    KnowledgeNode,
    Learner,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    QuestionKnowledgeMapping,
)
from app.schemas.assessment import SCORE_POLICY_VERSION, assessment_metrics
from app.schemas.critic import KnowledgeAssessment


class AssessmentContextError(ValueError):
    """The requested evidence does not belong to this learner, round or target."""


class AssessmentService:
    """Save evidence, counts and audit events in the caller's finalization transaction.

    Locking the learner row serializes all assessment writes for that learner on MySQL.
    Unique evidence/counting keys additionally protect idempotence at the database level.
    This service flushes but never commits, so final summaries and error updates remain atomic.
    """

    def __init__(self, database: Session) -> None:
        self.database = database

    def commit_assessment(
        self,
        learner_id: str,
        round_id: str,
        assessment: KnowledgeAssessment,
        *,
        basis_message_id: Optional[str] = None,
        assistance: Literal["none", "hint", "answer_visible"] = "none",
        question_valid: bool = True,
    ) -> AssessmentEvidence:
        assessment = KnowledgeAssessment.model_validate(assessment)
        if assistance not in {"none", "hint", "answer_visible"}:
            raise AssessmentContextError("Unknown assessment assistance")
        self.database.flush()
        learner = self.database.scalar(
            select(Learner).where(Learner.id == learner_id).with_for_update()
        )
        if learner is None:
            raise AssessmentContextError("Learner not found")
        learning_round = self.database.get(LearningRound, round_id)
        session = (
            self.database.get(LearningSession, learning_round.session_id)
            if learning_round is not None else None
        )
        if session is None or session.learner_id != learner_id:
            raise AssessmentContextError("Round does not belong to learner")
        if learning_round.finalized_at is None and learning_round.state not in {
            "ROUND_FINALIZING", "NEXT_QUESTION_READY", "SESSION_ENDED",
        }:
            raise AssessmentContextError("Knowledge assessments require a finalized round")
        question = self.database.get(Question, learning_round.question_id)
        if (
            question is None
            or question.session_id != session.id
            or question.round_id != learning_round.id
        ):
            raise AssessmentContextError("Round has no matching question")
        if self.database.get(KnowledgeNode, assessment.node_id) is None:
            raise AssessmentContextError("Unknown knowledge node")
        if assessment.node_id not in question.knowledge_node_ids:
            raise AssessmentContextError("Knowledge node is not an assessment target")

        existing = self.database.scalar(
            select(AssessmentEvidence).where(
                AssessmentEvidence.round_id == round_id,
                AssessmentEvidence.knowledge_node_id == assessment.node_id,
            ).with_for_update()
        )
        if existing is not None:
            return existing

        basis_message = (
            self.database.get(ConversationMessage, str(basis_message_id))
            if basis_message_id is not None else None
        )
        if basis_message_id is not None and (
            basis_message is None
            or basis_message.role != "student"
            or basis_message.round_id != round_id
            or basis_message.session_id != session.id
        ):
            raise AssessmentContextError("Assessment basis must be a student message in this round")

        revision = (
            self.database.get(BankQuestionRevision, question.bank_question_revision_id)
            if question.bank_question_revision_id else None
        )
        if question.bank_question_revision_id and revision is None:
            raise AssessmentContextError("Question references a missing bank revision")
        if revision is not None:
            mapping = self.database.scalar(select(QuestionKnowledgeMapping).where(
                QuestionKnowledgeMapping.bank_question_revision_id == revision.id,
                QuestionKnowledgeMapping.knowledge_node_id == assessment.node_id,
                QuestionKnowledgeMapping.role == "assessed",
            ))
            if mapping is None:
                raise AssessmentContextError("Prerequisite knowledge must not be assessed")

        # Version changes do not turn the same original question into a new sample.
        identity = (
            f"bank:{revision.bank_question_id}" if revision is not None
            else "content:" + sha256(
                question.student_content_json["markdown"].strip().encode("utf-8")
            ).hexdigest()
        )
        counting_key = sha256(
            f"{learner.id}\0{assessment.node_id}\0{identity}".encode("utf-8")
        ).hexdigest()
        previous = self.database.scalar(select(AssessmentEvidence).where(
            AssessmentEvidence.counted_question_key == counting_key,
        ).with_for_update())
        is_repeat = previous is not None
        if revision is not None and not is_repeat:
            # A previous hint/solution exposure cannot become a fresh independent sample
            # just by starting a new round or by correcting the original's typography.
            previous_exposure = self.database.scalar(select(AssessmentEvidence.id).where(
                AssessmentEvidence.learner_id == learner_id,
                AssessmentEvidence.bank_question_id == revision.bank_question_id,
                AssessmentEvidence.round_id != round_id,
                (
                    AssessmentEvidence.basis_message_id.is_not(None)
                    | (AssessmentEvidence.assistance != "none")
                ),
            ).limit(1).with_for_update())
            is_repeat = previous_exposure is not None
        exclusion_reason = None
        if (
            not question_valid or question.status == "invalid"
            or (revision is not None and revision.review_status == "invalid")
        ):
            exclusion_reason = "invalid_question"
        elif revision is not None and revision.review_status != "approved":
            exclusion_reason = "unreviewed_question"
        elif basis_message is None:
            exclusion_reason = "no_answer"
        elif assistance != "none":
            exclusion_reason = "assisted_answer"
        elif assessment.outcome == "unassessable":
            exclusion_reason = "unassessable"
        elif is_repeat:
            exclusion_reason = "repeat_question"
        counted = exclusion_reason is None

        learner_node = self.database.scalar(
            select(LearnerKnowledgeNode).where(
                LearnerKnowledgeNode.learner_id == learner_id,
                LearnerKnowledgeNode.knowledge_node_id == assessment.node_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
        before_n = (learner_node.evaluated_question_count or 0) if learner_node else 0
        before_c = (learner_node.correct_question_count or 0) if learner_node else 0
        before = assessment_metrics(before_n, before_c)
        after_n = before_n + int(counted)
        after_c = before_c + int(counted and assessment.outcome == "correct")
        after = assessment_metrics(after_n, after_c)
        now = datetime.utcnow()
        if counted:
            if learner_node is None:
                learner_node = LearnerKnowledgeNode(
                    learner_id=learner_id,
                    knowledge_node_id=assessment.node_id,
                )
                self.database.add(learner_node)
            old_status = learner_node.status
            learner_node.evaluated_question_count = after_n
            learner_node.correct_question_count = after_c
            learner_node.mastery = after.assessment_score
            learner_node.score_policy_version = SCORE_POLICY_VERSION
            learner_node.status = (
                "mastered" if after_n >= 20 and after.assessment_score >= 0.8
                else "needs_review" if old_status == "mastered" and assessment.outcome != "correct"
                else "weak" if after.accuracy is not None and after.accuracy < 0.5
                else "learning"
            )
            learner_node.last_practiced_at = now
            learner_node.updated_at = now

        evidence = AssessmentEvidence(
            learner_id=learner_id,
            round_id=round_id,
            question_id=question.id,
            bank_question_id=revision.bank_question_id if revision else None,
            bank_question_revision_id=revision.id if revision else None,
            knowledge_node_id=assessment.node_id,
            basis_message_id=basis_message.id if basis_message else None,
            outcome=assessment.outcome,
            assistance=assistance,
            is_repeat=is_repeat,
            counted=counted,
            counted_question_key=counting_key if counted else None,
            exclusion_reason=exclusion_reason,
            reason=assessment.reason,
            score_policy_version=SCORE_POLICY_VERSION,
            finalized_at=now,
        )
        self.database.add(evidence)
        self.database.flush()
        self.database.add(GraphUpdateEvent(
            learner_id=learner_id,
            round_id=round_id,
            graph_type="knowledge",
            node_id=assessment.node_id,
            before_value=before.assessment_score,
            after_value=after.assessment_score,
            assessment_evidence_id=evidence.id,
            before_evaluated_count=before_n,
            after_evaluated_count=after_n,
            before_correct_count=before_c,
            after_correct_count=after_c,
            reason=assessment.reason + (
                f" [excluded: {exclusion_reason}]" if exclusion_reason else ""
            ),
        ))
        self.database.flush()
        return evidence
