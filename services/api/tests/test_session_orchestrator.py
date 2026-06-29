import asyncio
import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.llm.base import LLMProviderError
from app.llm.mock import DemoMockLLMProvider
from app.models.base import Base
from app.models.entities import (
    GraphUpdateEvent,
    LearnerErrorNode,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    QuestionReviewRecord,
)
from app.schemas.session import CreateSessionRequest, SessionState
from app.seed import seed_database
from app.services.candidate_question_service import CandidateQuestionService
from app.services.session_orchestrator import (
    InvalidSessionTransitionError,
    LearningSessionOrchestrator,
    transition_session,
)
from app.services.critic_service import SAFE_CRITIC_FAILURE_REPLY

CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


class RecordingWebSocketManager:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, session_id: str, event) -> None:
        self.events.append(event.model_dump(mode="json"))


async def settle(orchestrator: LearningSessionOrchestrator) -> None:
    while orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))
        await asyncio.sleep(0)


class CriticTimeoutProvider(DemoMockLLMProvider):
    async def generate_structured(self, messages, schema):
        if schema.__name__ == "CriticTurnResult":
            raise LLMProviderError("LLM request timed out after 75 seconds")
        return await super().generate_structured(messages, schema)


class RejectingQuestionReviewProvider(DemoMockLLMProvider):
    def _question_review(self, context: dict) -> dict:
        return {
            "status": "invalid",
            "quality_score": 0.1,
            "issues": ["Rejected by test provider."],
            "grading_notes": "Force candidate fallback.",
        }


class SessionStateMachineTests(unittest.TestCase):
    def test_allows_expected_transition(self) -> None:
        from app.models.entities import LearningSession

        session = LearningSession(
            learner_id="demo_user",
            status=SessionState.SESSION_CREATED.value,
        )
        transition_session(session, SessionState.QUESTION_GENERATING)
        self.assertEqual(session.status, SessionState.QUESTION_GENERATING.value)

    def test_rejects_illegal_transition(self) -> None:
        from app.models.entities import LearningSession

        session = LearningSession(
            learner_id="demo_user",
            status=SessionState.SESSION_CREATED.value,
        )
        with self.assertRaises(InvalidSessionTransitionError):
            transition_session(session, SessionState.FEEDBACK_DISCUSSION)


class SessionOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        with self.factory() as database:
            seed_database(database, CURRICULUM_DIR)
        self.provider = DemoMockLLMProvider()
        self.websocket = RecordingWebSocketManager()
        self.orchestrator = LearningSessionOrchestrator(
            provider=self.provider,
            websocket_manager=self.websocket,
            session_factory=self.factory,
        )

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_mock_end_to_end_round_with_follow_up(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(self.orchestrator)
            first_question_id = str(created.current_question_id)

            accepted = self.orchestrator.accept_message(
                str(created.session_id),
                "iter(iterator)",
            )
            self.assertEqual(accepted.status, "processing")
            self.assertEqual(
                accepted.session_state,
                SessionState.CRITIC_PROCESSING,
            )
            await settle(self.orchestrator)

            feedback = self.orchestrator.get_session_response(
                str(created.session_id)
            )
            self.assertEqual(
                feedback.state,
                SessionState.FEEDBACK_DISCUSSION,
            )

            with self.factory() as database:
                provisional_mastery = database.scalar(
                    select(LearnerKnowledgeNode).where(
                        LearnerKnowledgeNode.learner_id == "demo_user",
                        LearnerKnowledgeNode.knowledge_node_id
                        == "python.iterator.next",
                    )
                )
                provisional_events = database.scalars(
                    select(GraphUpdateEvent)
                ).all()
                self.assertAlmostEqual(provisional_mastery.mastery, 0.42)
                self.assertEqual(provisional_events, [])
                candidates = database.scalars(
                    select(Question).where(
                        Question.session_id == str(created.session_id),
                        Question.status == "candidate_provisional",
                    )
                ).all()
                self.assertEqual(len(candidates), 1)

            self.orchestrator.accept_message(
                str(created.session_id),
                "为什么不能用 iter？",
            )
            await settle(self.orchestrator)
            discussion = self.orchestrator.get_session_response(
                str(created.session_id)
            )
            self.assertEqual(
                discussion.state,
                SessionState.FEEDBACK_DISCUSSION,
            )

            self.orchestrator.accept_message(
                str(created.session_id),
                "下一题",
            )
            await settle(self.orchestrator)

            completed = self.orchestrator.get_session_response(
                str(created.session_id)
            )
            self.assertEqual(completed.state, SessionState.QUESTION_ACTIVE)
            self.assertEqual(completed.completed_question_count, 1)
            self.assertNotEqual(
                str(completed.current_question_id),
                first_question_id,
            )
            self.assertNotIn(
                "critic_content",
                str(completed.model_dump(mode="json")),
            )

            with self.factory() as database:
                mastery = database.scalar(
                    select(LearnerKnowledgeNode).where(
                        LearnerKnowledgeNode.learner_id == "demo_user",
                        LearnerKnowledgeNode.knowledge_node_id
                        == "python.iterator.next",
                    )
                )
                error = database.scalar(
                    select(LearnerErrorNode).where(
                        LearnerErrorNode.learner_id == "demo_user",
                        LearnerErrorNode.error_type_id == "iter_vs_next",
                    )
                )
                events = database.scalars(select(GraphUpdateEvent)).all()
                self.assertAlmostEqual(mastery.mastery, 0.34)
                self.assertAlmostEqual(error.severity, 0.546)
                self.assertEqual(len(events), 2)

            event_types = [event["type"] for event in self.websocket.events]
            self.assertIn("critic_reply_ready", event_types)
            self.assertIn("candidate_question_ready", event_types)
            self.assertIn("session_summary_ready", event_types)
            self.assertIn("question_ready", event_types)

        asyncio.run(scenario())

    def test_critic_timeout_restores_session_and_broadcasts_safe_reply(self) -> None:
        async def scenario():
            orchestrator = LearningSessionOrchestrator(
                provider=CriticTimeoutProvider(),
                websocket_manager=self.websocket,
                session_factory=self.factory,
            )
            created = await orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(orchestrator)

            orchestrator.accept_message(
                str(created.session_id),
                "我不确定",
            )
            await settle(orchestrator)

            recovered = orchestrator.get_session_response(
                str(created.session_id)
            )
            self.assertEqual(recovered.state, SessionState.QUESTION_ACTIVE)
            self.assertEqual(
                recovered.messages[-1]["content_markdown"],
                SAFE_CRITIC_FAILURE_REPLY,
            )
            critic_events = [
                event
                for event in self.websocket.events
                if event["type"] == "critic_reply_ready"
            ]
            self.assertTrue(critic_events)
            self.assertEqual(
                critic_events[-1]["payload"]["session_state"],
                SessionState.QUESTION_ACTIVE.value,
            )

        asyncio.run(scenario())

    def test_diagnosis_change_preserves_ready_candidate_and_guides_following_candidate(
        self,
    ) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(self.orchestrator)
            session_id = str(created.session_id)

            self.orchestrator.accept_message(session_id, "iter(iterator)")
            await settle(self.orchestrator)
            with self.factory() as database:
                first_candidate = database.scalar(
                    select(Question).where(
                        Question.session_id == session_id,
                        Question.status == "candidate_provisional",
                    )
                )
                first_candidate_id = first_candidate.id

            self.orchestrator.accept_message(
                session_id,
                "这道题是不是有问题",
            )
            await settle(self.orchestrator)

            with self.factory() as database:
                preserved = database.get(Question, first_candidate_id)
                self.assertEqual(preserved.status, "candidate_provisional")

            self.orchestrator.accept_message(session_id, "下一题")
            await settle(self.orchestrator)

            with self.factory() as database:
                promoted = database.get(Question, first_candidate_id)
                following_candidate = database.scalar(
                    select(Question).where(
                        Question.session_id == session_id,
                        Question.status == "candidate_provisional",
                    )
                )
                self.assertIn(promoted.status, {"active", "approved"})
                self.assertIsNotNone(following_candidate)
                self.assertNotEqual(following_candidate.id, first_candidate_id)

            questioner_contexts = [
                messages[1]["content"]
                for schema_name, messages in self.provider.calls
                if schema_name == "QuestionPacket"
            ]
            self.assertTrue(
                all(
                    "这道题是不是有问题" not in context
                    for context in questioner_contexts
                )
            )
            event_types = [event["type"] for event in self.websocket.events]
            self.assertIn("question_ready", event_types)

        asyncio.run(scenario())

    def test_invalid_question_replacement_does_not_update_graphs(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(self.orchestrator)
            session_id = str(created.session_id)
            old_question_id = str(created.current_question_id)
            old_markdown = created.current_question["markdown"]

            with self.factory() as database:
                review = database.scalar(
                    select(QuestionReviewRecord).where(
                        QuestionReviewRecord.question_id == old_question_id
                    )
                )
                review.status = "invalid"
                review.quality_score = 0.1
                review.issues_json = ["Ambiguous question."]
                database.commit()

            self.orchestrator.accept_message(session_id, "next(iterator)")
            await settle(self.orchestrator)
            response = self.orchestrator.get_session_response(session_id)

            self.assertEqual(response.state, SessionState.QUESTION_ACTIVE)
            self.assertNotEqual(
                str(response.current_question_id),
                old_question_id,
            )
            self.assertNotEqual(
                response.current_question["markdown"],
                old_markdown,
            )
            with self.factory() as database:
                events = database.scalars(select(GraphUpdateEvent)).all()
                self.assertEqual(events, [])

        asyncio.run(scenario())

    def test_processing_failure_recovers_to_feedback_discussion(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(self.orchestrator)
            session_id = str(created.session_id)

            with self.factory() as database:
                session = database.get(LearningSession, session_id)
                round_record = database.scalar(
                    select(LearningRound).where(
                        LearningRound.session_id == session_id,
                        LearningRound.finalized_at.is_(None),
                    )
                )
                session.status = SessionState.CRITIC_PROCESSING.value
                round_record.state = SessionState.CRITIC_PROCESSING.value
                database.commit()

            await self.orchestrator.recover_processing_failure(session_id)
            recovered = self.orchestrator.get_session_response(session_id)

            self.assertEqual(recovered.state, SessionState.FEEDBACK_DISCUSSION)
            self.assertIn(
                "下一题暂时没有准备好",
                recovered.messages[-1]["content_markdown"],
            )

        asyncio.run(scenario())

    def test_next_question_waits_for_candidate_before_recovering(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(self.orchestrator)
            session_id = str(created.session_id)

            with self.factory() as database:
                session = database.get(LearningSession, session_id)
                round_record = database.scalar(
                    select(LearningRound).where(
                        LearningRound.session_id == session_id,
                        LearningRound.finalized_at.is_(None),
                    )
                )
                candidates = database.scalars(
                    select(Question).where(
                        Question.session_id == session_id,
                        Question.round_id == round_record.id,
                        Question.status.in_(
                            ["candidate_provisional", "candidate_ready"]
                        ),
                    )
                ).all()
                for candidate in candidates:
                    database.delete(candidate)
                session.status = SessionState.ROUND_FINALIZING.value
                round_record.state = SessionState.ROUND_FINALIZING.value
                database.commit()
                round_id = round_record.id

            key = (session_id, round_id)
            self.orchestrator._candidate_generation_keys.add(key)

            async def release_generation_lock() -> None:
                await asyncio.sleep(0.01)
                self.orchestrator._candidate_generation_keys.discard(key)

            asyncio.create_task(release_generation_lock())
            await self.orchestrator.finalize_round(session_id)
            await settle(self.orchestrator)

            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(response.state, SessionState.QUESTION_ACTIVE)
            self.assertEqual(response.completed_question_count, 1)
            self.assertNotIn(
                "下一题暂时没有准备好",
                "\n".join(message["content_markdown"] for message in response.messages),
            )
            self.assertIn(
                "question_ready",
                [event["type"] for event in self.websocket.events],
            )

        asyncio.run(scenario())

    def test_candidate_generation_uses_seed_fallback_when_review_rejects_model(
        self,
    ) -> None:
        async def scenario():
            with self.factory() as database:
                session = LearningSession(
                    learner_id="demo_user",
                    status=SessionState.FEEDBACK_DISCUSSION.value,
                )
                database.add(session)
                database.flush()
                learning_round = LearningRound(
                    session_id=session.id,
                    state=SessionState.FEEDBACK_DISCUSSION.value,
                )
                database.add(learning_round)
                database.flush()
                session_id = session.id
                round_id = learning_round.id

                candidate = await CandidateQuestionService(
                    RejectingQuestionReviewProvider()
                ).generate(
                    database,
                    session,
                    learning_round,
                    critic_summary={},
                )

                self.assertIsNotNone(candidate)
                self.assertEqual(candidate.status, "candidate_provisional")
                self.assertEqual(candidate.session_id, session_id)
                self.assertEqual(candidate.round_id, round_id)
                review = database.scalar(
                    select(QuestionReviewRecord).where(
                        QuestionReviewRecord.question_id == candidate.id
                    )
                )
                self.assertIsNotNone(review)
                self.assertEqual(review.status, "approved")

        asyncio.run(scenario())

    def test_can_complete_ten_consecutive_rounds(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(
                CreateSessionRequest(
                    learner_id="demo_user",
                    module="python_iterator",
                )
            )
            await settle(self.orchestrator)
            session_id = str(created.session_id)

            for _ in range(10):
                self.orchestrator.accept_message(session_id, "错误答案")
                await settle(self.orchestrator)
                self.orchestrator.accept_message(session_id, "下一题")
                await settle(self.orchestrator)

            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(response.state, SessionState.QUESTION_ACTIVE)
            self.assertEqual(response.completed_question_count, 10)
            questioner_messages = [
                message
                for message in response.messages
                if message["role"] == "questioner"
            ]
            self.assertEqual(len(questioner_messages), 11)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
