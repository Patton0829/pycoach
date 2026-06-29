import asyncio
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.llm.mock import MockLLMProvider
from app.models.base import Base
from app.schemas.question import QuestionerContext
from app.seed import seed_database
from app.services.question_service import (
    QuestionContextBuilder,
    QuestionService,
    choose_preferred_question_type,
)
from tests.test_schemas import valid_question

CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


def question_context(
    *,
    preferred_question_type=None,
    recent_questions=None,
) -> QuestionerContext:
    return QuestionerContext.model_validate(
        {
            "global_knowledge_graph": {
                "module": "python_iterator",
                "knowledge_node_ids": [
                    "python.list",
                    "python.iterable",
                    "python.iterator",
                    "python.iterator.iter",
                    "python.iterator.next",
                    "python.iterator.state",
                    "python.iterator.exhaustion",
                    "python.stop_iteration",
                    "python.for_loop.protocol",
                    "python.generator.intro",
                ],
            },
            "personal_knowledge_graph": [
                {
                    "node_id": "python.list",
                    "mastery": 0.82,
                    "status": "mastered",
                },
                {
                    "node_id": "python.iterable",
                    "mastery": 0.48,
                    "status": "learning",
                },
                {
                    "node_id": "python.iterator",
                    "mastery": 0.38,
                    "status": "learning",
                },
                {
                    "node_id": "python.iterator.iter",
                    "mastery": 0.72,
                    "status": "learning",
                },
                {
                    "node_id": "python.iterator.next",
                    "mastery": 0.42,
                    "status": "learning",
                },
                {
                    "node_id": "python.iterator.state",
                    "mastery": 0.0,
                    "status": "not_started",
                },
                {
                    "node_id": "python.iterator.exhaustion",
                    "mastery": 0.0,
                    "status": "not_started",
                },
                {
                    "node_id": "python.stop_iteration",
                    "mastery": 0.0,
                    "status": "not_started",
                },
            ],
            "error_graph": [
                {
                    "error_id": "iter_vs_next",
                    "severity": 0.45,
                    "status": "active",
                },
                {
                    "error_id": "iterable_vs_iterator",
                    "severity": 0.2,
                    "status": "active",
                },
                {
                    "error_id": "iter_advances_state",
                    "severity": 0.2,
                    "status": "active",
                },
                {
                    "error_id": "stop_iteration_unrecognized",
                    "severity": 0.2,
                    "status": "active",
                },
            ],
            "recent_questions": recent_questions or [],
            "recent_attempts": [],
            "critic_summary": {},
            "teaching_policy": {},
            "candidate_constraints": {
                "preferred_question_type": preferred_question_type,
                "allowed_knowledge_node_ids": [
                    "python.list",
                    "python.iterable",
                    "python.iterator",
                    "python.iterator.iter",
                    "python.iterator.next",
                    "python.iterator.state",
                    "python.iterator.exhaustion",
                    "python.stop_iteration",
                ],
                "allowed_error_ids": [
                    "iter_vs_next",
                    "iterable_vs_iterator",
                    "iter_advances_state",
                    "stop_iteration_unrecognized",
                ],
            },
        }
    )


def model_question(question_type="code_blank") -> dict:
    payload = valid_question()
    payload["question_type"] = question_type
    return payload


def multiple_choice_question() -> dict:
    payload = model_question("multiple_choice")
    payload["student_content"]["markdown"] = (
        "下面哪个表达式会从迭代器中取出下一个元素？\n\n"
        "A. `iter(iterator)`\n\n"
        "B. `next(iterator)`\n\n"
        "C. `iterator[0]`\n\n"
        "D. `list(iterator)`"
    )
    payload["critic_content"]["reference_answer"] = "B"
    payload["critic_content"]["acceptable_answers"] = ["B", "next(iterator)"]
    return payload


class QuestionServiceTests(unittest.TestCase):
    def test_generates_valid_model_question(self) -> None:
        generated = model_question()
        model_question_id = generated["question_id"]
        provider = MockLLMProvider([generated])
        service = QuestionService(provider, CURRICULUM_DIR)

        result = asyncio.run(
            service.generate_next_question(
                question_context(preferred_question_type="code_blank")
            )
        )

        self.assertEqual(result.source, "model")
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(result.packet.question_type, "code_blank")
        self.assertNotEqual(str(result.packet.question_id), model_question_id)
        self.assertEqual(len(provider.calls), 1)

    def test_retries_once_with_validation_feedback(self) -> None:
        invalid = model_question()
        invalid["difficulty"] = 99
        provider = MockLLMProvider([invalid, model_question()])
        service = QuestionService(provider, CURRICULUM_DIR)

        result = asyncio.run(
            service.generate_next_question(
                question_context(preferred_question_type="code_blank")
            )
        )

        self.assertEqual(result.source, "model")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn("上一次输出无效", provider.calls[1][-1]["content"])

    def test_retries_multiple_choice_without_visible_options(self) -> None:
        invalid = model_question("multiple_choice")
        invalid["student_content"]["markdown"] = "下列哪项描述是正确的？"
        replacement = multiple_choice_question()
        provider = MockLLMProvider([invalid, replacement])
        service = QuestionService(provider, CURRICULUM_DIR)

        result = asyncio.run(
            service.generate_next_question(
                question_context(preferred_question_type="multiple_choice")
            )
        )

        self.assertEqual(result.source, "model")
        self.assertEqual(result.retry_count, 1)
        self.assertIn("A.", result.packet.student_content.markdown)
        self.assertIn("D.", result.packet.student_content.markdown)

    def test_retries_semantically_duplicate_question(self) -> None:
        duplicate = model_question()
        recent = [
            {
                "question_id": str(uuid4()),
                "question_type": "code_blank",
                "markdown": duplicate["student_content"]["markdown"],
                "knowledge_node_ids": ["python.iterator.next"],
            }
        ]
        replacement = model_question()
        replacement["student_content"]["markdown"] = "填写：`value = next(____)`"
        provider = MockLLMProvider([duplicate, replacement])
        service = QuestionService(provider, CURRICULUM_DIR)

        result = asyncio.run(
            service.generate_next_question(
                question_context(
                    preferred_question_type="code_blank",
                    recent_questions=recent,
                )
            )
        )

        self.assertEqual(result.source, "model")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(
            result.packet.student_content.markdown,
            replacement["student_content"]["markdown"],
        )

    def test_retries_surface_variant_with_only_numbers_and_names_changed(self) -> None:
        first = model_question()
        first["student_content"]["markdown"] = (
            "填写代码：\n\n```python\n"
            "numbers = [10, 20]\n"
            "iterator = iter(numbers)\n"
            "value = ______\n"
            "```"
        )
        variant = model_question()
        variant["student_content"]["markdown"] = (
            "填写代码：\n\n```python\n"
            "values = [1, 2]\n"
            "it = iter(values)\n"
            "item = ______\n"
            "```"
        )
        replacement = model_question()
        replacement["student_content"]["markdown"] = (
            "填写代码：\n\n```python\n"
            "items = iter([1, 2])\n"
            "first = ______\n"
            "```"
        )
        recent = [
            {
                "question_id": str(uuid4()),
                "question_type": "code_blank",
                "markdown": first["student_content"]["markdown"],
                "knowledge_node_ids": ["python.iterator.next"],
            }
        ]
        provider = MockLLMProvider([variant, replacement])
        service = QuestionService(provider, CURRICULUM_DIR)

        result = asyncio.run(
            service.generate_next_question(
                question_context(
                    preferred_question_type="code_blank",
                    recent_questions=recent,
                )
            )
        )

        self.assertEqual(result.retry_count, 1)
        self.assertEqual(
            result.packet.student_content.markdown,
            replacement["student_content"]["markdown"],
        )

    def test_falls_back_to_matching_seed_after_two_invalid_outputs(self) -> None:
        invalid_one = model_question()
        invalid_one["question_type"] = "short_explanation"
        invalid_one["difficulty"] = 99
        invalid_two = dict(invalid_one)
        provider = MockLLMProvider([invalid_one, invalid_two])
        service = QuestionService(provider, CURRICULUM_DIR)

        result = asyncio.run(
            service.generate_next_question(
                question_context(preferred_question_type="short_explanation")
            )
        )

        self.assertEqual(result.source, "seed_fallback")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.packet.question_type, "short_explanation")
        self.assertNotEqual(
            str(result.packet.question_id),
            "44444444-4444-4444-8444-444444444444",
        )

    def test_prepares_default_teaching_policy_and_constraints(self) -> None:
        provider = MockLLMProvider([])
        service = QuestionService(provider, CURRICULUM_DIR)

        prepared = service.prepare_context(question_context())

        self.assertEqual(
            prepared.candidate_constraints.preferred_question_type,
            "multiple_choice",
        )
        self.assertTrue(prepared.teaching_policy["retrieval_practice"])

    def test_type_scheduler_approximates_requested_mix(self) -> None:
        sequence = []
        for _ in range(10):
            sequence.append(
                choose_preferred_question_type(
                    sequence,
                    [
                        "multiple_choice",
                        "code_blank",
                        "output_prediction",
                        "short_explanation",
                    ],
                )
            )

        self.assertEqual(sequence.count("multiple_choice"), 4)
        self.assertEqual(sequence.count("code_blank"), 3)
        self.assertEqual(sequence.count("output_prediction"), 2)
        self.assertEqual(sequence.count("short_explanation"), 1)

    def test_builds_context_from_seeded_database(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as database:
            seed_database(database, CURRICULUM_DIR)
            context = QuestionContextBuilder(database).build("demo_user")

        self.assertEqual(len(context.global_knowledge_graph["nodes"]), 10)
        self.assertEqual(len(context.global_knowledge_graph["edges"]), 10)
        self.assertEqual(len(context.personal_knowledge_graph), 10)
        self.assertEqual(len(context.error_graph), 1)
        self.assertEqual(
            len(context.candidate_constraints.allowed_error_ids),
            9,
        )
        Base.metadata.drop_all(engine)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
