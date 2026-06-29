import asyncio
import unittest
from pathlib import Path
from typing import Dict, List, Type
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.llm.base import LLMProvider, SchemaT
from app.llm.mock import MockLLMProvider
from app.models.base import Base
from app.models.entities import (
    LearningRound,
    LearningSession,
    Question,
    QuestionReviewRecord,
)
from app.schemas.critic import QuestionReviewContext
from app.schemas.question import QuestionPacket
from app.seed import seed_database
from app.services.critic_service import CriticQuestionReviewService
from tests.test_schemas import valid_question

CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


def review_context(packet: QuestionPacket | None = None) -> QuestionReviewContext:
    return QuestionReviewContext(
        question_packet=packet or QuestionPacket.model_validate(valid_question()),
        expected_knowledge_node_ids=["python.iterator.next"],
        expected_difficulty_min=1,
        expected_difficulty_max=3,
        recent_questions=[],
    )


class BlockingReviewProvider(LLMProvider):
    def __init__(self, response: dict) -> None:
        self.response = response
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        self.started.set()
        await self.release.wait()
        return schema.model_validate(self.response)


class CriticReviewTests(unittest.TestCase):
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
        self.database: Session = self.factory()
        seed_database(self.database, CURRICULUM_DIR)

    def tearDown(self) -> None:
        self.database.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_review_starts_without_blocking_question_delivery(self) -> None:
        async def scenario():
            provider = BlockingReviewProvider(
                {
                    "status": "approved",
                    "quality_score": 0.95,
                    "issues": [],
                    "grading_notes": None,
                }
            )
            service = CriticQuestionReviewService(provider)
            task = service.start_review(review_context())

            await provider.started.wait()
            self.assertFalse(task.done())
            student_markdown = review_context().question_packet.student_content.markdown
            self.assertTrue(student_markdown)

            provider.release.set()
            result = await task
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.review.status, "approved")

        asyncio.run(scenario())

    def test_invalid_ambiguous_question_is_replaced_before_answer(self) -> None:
        provider = MockLLMProvider(
            [
                {
                    "status": "invalid",
                    "quality_score": 0.2,
                    "issues": [
                        "题干没有说明选择一个还是多个答案，且 A、B 都可能成立。"
                    ],
                    "grading_notes": None,
                }
            ]
        )
        service = CriticQuestionReviewService(provider)

        execution = asyncio.run(service.review_question(review_context()))
        decision = service.decide_handling(
            execution,
            review_context().question_packet.question_id,
            student_has_answered=False,
        )

        self.assertEqual(decision.action, "replace_question")
        self.assertFalse(decision.allow_graph_updates)
        self.assertTrue(decision.should_generate_replacement)
        self.assertIsNone(decision.student_visible_reply_markdown)

    def test_invalid_question_after_answer_explains_and_skips_graph_updates(self) -> None:
        provider = MockLLMProvider(
            [
                {
                    "status": "invalid",
                    "quality_score": 0.1,
                    "issues": ["参考答案与 Python 迭代器协议不一致。"],
                    "grading_notes": None,
                }
            ]
        )
        service = CriticQuestionReviewService(provider)

        execution = asyncio.run(service.review_question(review_context()))
        decision = service.decide_handling(
            execution,
            review_context().question_packet.question_id,
            student_has_answered=True,
        )

        self.assertEqual(decision.action, "explain_invalid_and_replace")
        self.assertFalse(decision.allow_graph_updates)
        self.assertIn("不会影响你的学习记录", decision.student_visible_reply_markdown)

    def test_needs_revision_continues_with_internal_grading_notes(self) -> None:
        provider = MockLLMProvider(
            [
                {
                    "status": "needs_revision",
                    "quality_score": 0.72,
                    "issues": ["评分标准应补充等价中文答案。"],
                    "grading_notes": "接受说明 next() 推进状态的同义表达。",
                }
            ]
        )
        service = CriticQuestionReviewService(provider)

        execution = asyncio.run(service.review_question(review_context()))
        decision = service.decide_handling(
            execution,
            review_context().question_packet.question_id,
            student_has_answered=False,
        )

        self.assertEqual(decision.action, "continue_with_review_notes")
        self.assertTrue(decision.allow_graph_updates)
        self.assertFalse(decision.should_generate_replacement)

    def test_invalid_schema_retries_once_then_returns_review_failed(self) -> None:
        provider = MockLLMProvider(
            [
                {
                    "status": "invalid",
                    "quality_score": 0.2,
                    "issues": [],
                    "grading_notes": None,
                },
                {"status": "unknown"},
            ]
        )
        service = CriticQuestionReviewService(provider)

        execution = asyncio.run(service.review_question(review_context()))
        decision = service.decide_handling(
            execution,
            review_context().question_packet.question_id,
            student_has_answered=False,
        )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.retry_count, 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("上一次输出未通过", provider.calls[1][-1]["content"])
        self.assertEqual(decision.action, "pause_for_review_retry")
        self.assertFalse(decision.allow_graph_updates)

    def test_valid_review_is_persisted_and_updates_question_status(self) -> None:
        packet = QuestionPacket.model_validate(valid_question())
        session = LearningSession(
            id=str(uuid4()),
            learner_id="demo_user",
            status="QUESTION_ACTIVE",
        )
        learning_round = LearningRound(
            id=str(uuid4()),
            session_id=session.id,
            state="QUESTION_ACTIVE",
        )
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
            status="active",
        )
        self.database.add(session)
        self.database.flush()
        self.database.add(learning_round)
        self.database.flush()
        self.database.add(question)
        self.database.commit()

        provider = MockLLMProvider(
            [
                {
                    "status": "approved",
                    "quality_score": 0.94,
                    "issues": [],
                    "grading_notes": "Accept exact next(iterator) expression.",
                }
            ]
        )
        service = CriticQuestionReviewService(provider)
        execution = asyncio.run(
            service.review_and_persist(review_context(packet), self.database)
        )

        record = self.database.scalar(select(QuestionReviewRecord))
        self.assertEqual(execution.status, "completed")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "approved")
        self.assertEqual(question.status, "approved")


if __name__ == "__main__":
    unittest.main()
