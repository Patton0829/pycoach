from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.llm.base import LLMProvider
from app.models.entities import LearningRound, LearningSession, Question
from app.repositories.question_review_repository import QuestionReviewRepository
from app.repositories.session_repository import SessionRepository
from app.schemas.critic import QuestionReview, QuestionReviewContext
from app.schemas.question import QuestionGenerationResult, QuestionPacket
from app.schemas.question import RecentQuestion
from app.services.critic_service import CriticQuestionReviewService
from app.services.question_service import QuestionContextBuilder, QuestionService


class CandidateQuestionService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(
        self,
        database: Session,
        session: LearningSession,
        learning_round: LearningRound,
        critic_summary: Dict[str, Any],
    ) -> Optional[Question]:
        repository = SessionRepository(database)
        recent_records = repository.list_recent_formal_questions(session.id)
        recent_questions = [
            RecentQuestion(
                question_id=record.id,
                question_type=record.question_type,
                markdown=record.student_content_json["markdown"],
                knowledge_node_ids=record.knowledge_node_ids,
            )
            for record in recent_records
        ]
        context = QuestionContextBuilder(database).build(
            learner_id=session.learner_id,
            recent_questions=recent_questions,
            critic_summary=critic_summary,
        )
        question_service = QuestionService(self.provider)
        result = await question_service.generate_next_question(context)
        candidate = await self._create_reviewed_candidate(
            database,
            session,
            learning_round,
            result,
            recent_questions,
        )
        if candidate is not None:
            return candidate

        prepared_context = question_service.prepare_context(context)
        fallback_packet = question_service.select_seed_fallback(
            prepared_context.candidate_constraints
        )
        return self._create_trusted_seed_candidate(
            database,
            session,
            learning_round,
            fallback_packet,
        )

    async def _create_reviewed_candidate(
        self,
        database: Session,
        session: LearningSession,
        learning_round: LearningRound,
        result: QuestionGenerationResult,
        recent_questions: list[RecentQuestion],
    ) -> Optional[Question]:
        packet = result.packet
        question = Question(
            id=str(packet.question_id),
            session_id=session.id,
            round_id=learning_round.id,
            question_type=packet.question_type,
            difficulty=packet.difficulty,
            student_content_json=packet.student_content.model_dump(mode="json"),
            critic_content_json=packet.critic_content.model_dump(mode="json"),
            knowledge_node_ids=packet.knowledge_node_ids,
            target_error_ids=packet.target_error_ids,
            pedagogical_strategy=packet.pedagogical_strategy,
            status="candidate_provisional",
        )
        database.add(question)
        database.flush()

        review_service = CriticQuestionReviewService(self.provider)
        review_execution = await review_service.review_question(
            QuestionReviewContext(
                question_packet=result.packet,
                expected_knowledge_node_ids=result.packet.knowledge_node_ids,
                expected_difficulty_min=max(1, result.packet.difficulty - 1),
                expected_difficulty_max=min(5, result.packet.difficulty + 1),
                recent_questions=recent_questions,
            )
        )
        if review_execution.status == "failed":
            question.status = "candidate_failed"
            database.commit()
            return None

        QuestionReviewRepository(database).save(
            question,
            review_execution.review,
            update_question_status=False,
        )
        if review_execution.review.status == "invalid":
            question.status = "candidate_failed"
            database.commit()
            return None

        database.commit()
        return question

    def _create_trusted_seed_candidate(
        self,
        database: Session,
        session: LearningSession,
        learning_round: LearningRound,
        packet: QuestionPacket,
    ) -> Question:
        question = Question(
            id=str(packet.question_id),
            session_id=session.id,
            round_id=learning_round.id,
            question_type=packet.question_type,
            difficulty=packet.difficulty,
            student_content_json=packet.student_content.model_dump(mode="json"),
            critic_content_json=packet.critic_content.model_dump(mode="json"),
            knowledge_node_ids=packet.knowledge_node_ids,
            target_error_ids=packet.target_error_ids,
            pedagogical_strategy=packet.pedagogical_strategy,
            status="candidate_provisional",
        )
        database.add(question)
        database.flush()
        QuestionReviewRepository(database).save(
            question,
            QuestionReview(
                status="approved",
                quality_score=1.0,
                issues=[],
                grading_notes="Trusted curriculum seed fallback.",
            ),
            update_question_status=False,
        )
        database.commit()
        return question

    @staticmethod
    def mark_stale(question: Question) -> None:
        question.status = "candidate_stale"

    @staticmethod
    def mark_ready(question: Question) -> None:
        question.status = "candidate_ready"
