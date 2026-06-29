from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    ConversationMessage,
    CriticTurnResultRecord,
    Learner,
    LearningRound,
    LearningSession,
    Question,
    QuestionReviewRecord,
)
from app.schemas.critic import CriticTurnResult, QuestionReview
from app.schemas.question import QuestionPacket


class SessionRepository:
    def __init__(self, database: Session) -> None:
        self.database = database

    def learner_exists(self, learner_id: str) -> bool:
        return self.database.get(Learner, learner_id) is not None

    def get_session(self, session_id: str) -> Optional[LearningSession]:
        return self.database.get(LearningSession, session_id)

    def get_round(self, round_id: str) -> Optional[LearningRound]:
        return self.database.get(LearningRound, round_id)

    def get_current_round(self, session_id: str) -> Optional[LearningRound]:
        statement = (
            select(LearningRound)
            .where(
                LearningRound.session_id == session_id,
                LearningRound.finalized_at.is_(None),
            )
            .order_by(LearningRound.started_at.desc())
        )
        return self.database.scalar(statement)

    def get_question(self, question_id: str) -> Optional[Question]:
        return self.database.get(Question, question_id)

    def get_current_question(self, session: LearningSession) -> Optional[Question]:
        if not session.current_question_id:
            return None
        return self.get_question(session.current_question_id)

    def list_messages(
        self,
        session_id: str,
        round_id: Optional[str] = None,
    ) -> Sequence[ConversationMessage]:
        statement = select(ConversationMessage).where(
            ConversationMessage.session_id == session_id
        )
        if round_id:
            statement = statement.where(ConversationMessage.round_id == round_id)
        return self.database.scalars(
            statement.order_by(ConversationMessage.created_at, ConversationMessage.id)
        ).all()

    def get_message(self, message_id: str) -> Optional[ConversationMessage]:
        return self.database.get(ConversationMessage, message_id)

    def get_latest_question_review(
        self,
        question_id: str,
    ) -> Optional[QuestionReviewRecord]:
        statement = (
            select(QuestionReviewRecord)
            .where(QuestionReviewRecord.question_id == question_id)
            .order_by(QuestionReviewRecord.created_at.desc())
        )
        return self.database.scalar(statement)

    def get_latest_turn_result(
        self,
        round_id: str,
    ) -> Optional[CriticTurnResultRecord]:
        statement = (
            select(CriticTurnResultRecord)
            .join(
                ConversationMessage,
                ConversationMessage.id == CriticTurnResultRecord.message_id,
            )
            .where(ConversationMessage.round_id == round_id)
            .order_by(CriticTurnResultRecord.created_at.desc())
        )
        return self.database.scalar(statement)

    def list_turn_results(self, round_id: str) -> Sequence[CriticTurnResultRecord]:
        statement = (
            select(CriticTurnResultRecord)
            .join(
                ConversationMessage,
                ConversationMessage.id == CriticTurnResultRecord.message_id,
            )
            .where(ConversationMessage.round_id == round_id)
            .order_by(CriticTurnResultRecord.created_at)
        )
        return self.database.scalars(statement).all()

    def get_candidate_question(
        self,
        session_id: str,
        round_id: str,
        include_stale: bool = False,
    ) -> Optional[Question]:
        statuses = [
            "candidate_generating",
            "candidate_provisional",
            "candidate_ready",
        ]
        if include_stale:
            statuses.append("candidate_stale")
        statement = (
            select(Question)
            .where(
                Question.session_id == session_id,
                Question.round_id == round_id,
                Question.status.in_(statuses),
            )
            .order_by(Question.created_at.desc())
        )
        return self.database.scalar(statement)

    def list_recent_formal_questions(
        self,
        session_id: str,
        limit: int = 10,
    ) -> Sequence[Question]:
        statement = (
            select(Question)
            .where(
                Question.session_id == session_id,
                Question.status.in_(["active", "approved", "needs_revision", "completed"]),
            )
            .order_by(Question.created_at.desc())
            .limit(limit)
        )
        return self.database.scalars(statement).all()

    def count_completed_rounds(self, session_id: str) -> int:
        statement = select(func.count()).select_from(LearningRound).where(
            LearningRound.session_id == session_id,
            LearningRound.finalized_at.is_not(None),
        )
        return self.database.scalar(statement) or 0

    def add(self, entity: object) -> None:
        self.database.add(entity)

    @staticmethod
    def packet_from_question(question: Question) -> QuestionPacket:
        return QuestionPacket.model_validate(
            {
                "question_id": question.id,
                "question_type": question.question_type,
                "difficulty": question.difficulty,
                "knowledge_node_ids": question.knowledge_node_ids,
                "target_error_ids": question.target_error_ids,
                "pedagogical_strategy": question.pedagogical_strategy,
                "student_content": question.student_content_json,
                "critic_content": question.critic_content_json,
            }
        )

    @staticmethod
    def review_from_record(record: QuestionReviewRecord) -> QuestionReview:
        return QuestionReview(
            status=record.status,
            quality_score=record.quality_score,
            issues=record.issues_json,
            grading_notes=record.grading_notes,
        )

    @staticmethod
    def turn_result_from_record(
        record: CriticTurnResultRecord,
    ) -> CriticTurnResult:
        return CriticTurnResult.model_validate(record.result_json)
