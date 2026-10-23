import asyncio
import json
from pathlib import Path
import unittest
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.llm.mock import DemoMockLLMProvider
from app.models.base import Base
from app.models.entities import (
    BankQuestion,
    BankQuestionRevision,
    KnowledgeNode,
    Question,
    SourceDocument,
)
from app.schemas.public_question import PublicQuestionMetadata
from app.schemas.session import CreateSessionRequest
from app.seed import seed_database
from app.services.question_metadata_service import (
    question_metadata,
    question_metadata_batch,
)
from app.services.session_orchestrator import LearningSessionOrchestrator


CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


class PublicQuestionMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.database = sessionmaker(bind=self.engine, autoflush=False)()
        self.database.add_all([
            KnowledgeNode(
                id="python.iterator.next",
                name="next() 推进迭代器",
                description="INTERNAL_KNOWLEDGE_DESCRIPTION",
                difficulty=1,
                learning_objective="INTERNAL_LEARNING_OBJECTIVE",
            ),
            KnowledgeNode(
                id="python.iterator.state",
                name="迭代器状态",
                description="INTERNAL_KNOWLEDGE_DESCRIPTION",
                difficulty=2,
                learning_objective="INTERNAL_LEARNING_OBJECTIVE",
            ),
        ])
        self.document = SourceDocument(
            id=str(uuid4()),
            title="Python 真题资料",
            document_type="past_exam",
            exam_year=2024,
            file_path="/private/INTERNAL_SOURCE_PATH/exam.pdf",
            sha256="a" * 64,
            page_count=9,
        )
        self.database.add(self.document)
        self.database.flush()
        self.identity = BankQuestion(
            id="fixture-metadata-q1",
            source_document_id=self.document.id,
            question_number="12",
        )
        self.database.add(self.identity)
        self.database.flush()
        self.first_revision = self._revision(1, difficulty=2, pages=[1, 2])
        self.database.add(self.first_revision)
        self.database.commit()

    def tearDown(self) -> None:
        self.database.close()
        self.engine.dispose()

    def _revision(
        self, number: int, *, difficulty: int, pages: list[int]
    ) -> BankQuestionRevision:
        return BankQuestionRevision(
            id=str(uuid4()),
            bank_question_id=self.identity.id,
            revision=number,
            question_type="output_prediction",
            difficulty=difficulty,
            difficulty_reason="INTERNAL_DIFFICULTY_REASON",
            original_content_json={"stem": "INTERNAL_ORIGINAL_CONTENT"},
            student_content_json={"markdown": "预测结果。"},
            critic_content_json={
                "reference_answer": "INTERNAL_REFERENCE_ANSWER",
                "grading_rubric": {"correct": "INTERNAL_GRADING_RUBRIC"},
            },
            source_locations_json={
                "question_pdf_pages": pages,
                "answer_pdf_pages": [9],
            },
            answer_provenance_json={"source_text": "INTERNAL_ANSWER_SOURCE"},
            review_status="approved",
            content_hash=str(number) * 64,
        )

    def _question(self, *, revision_id=None, difficulty=2, node_ids=None) -> Question:
        return Question(
            id=str(uuid4()),
            session_id=str(uuid4()),
            round_id=str(uuid4()),
            bank_question_revision_id=revision_id,
            question_type="output_prediction",
            difficulty=difficulty,
            student_content_json={"markdown": "预测结果。"},
            critic_content_json={"reference_answer": "INTERNAL_SESSION_ANSWER"},
            knowledge_node_ids=(
                ["python.iterator.next", "python.iterator.state"]
                if node_ids is None else node_ids
            ),
            target_error_ids=["INTERNAL_TARGET_ERROR"],
            pedagogical_strategy="INTERNAL_TEACHING_STRATEGY",
            status="active",
        )

    def test_exam_metadata_exposes_only_public_labels_and_question_pages(self) -> None:
        question = self._question(revision_id=self.first_revision.id)

        payload = question_metadata(self.database, question).model_dump(mode="json")

        self.assertEqual(set(payload), {"difficulty", "knowledge_points", "source"})
        self.assertEqual(payload["difficulty"], 2)
        self.assertEqual(payload["knowledge_points"], [
            {"id": "python.iterator.next", "name": "next() 推进迭代器"},
            {"id": "python.iterator.state", "name": "迭代器状态"},
        ])
        self.assertEqual(payload["source"], {
            "title": "Python 真题资料",
            "document_type": "past_exam",
            "exam_year": 2024,
            "question_number": "12",
            "pdf_pages": [1, 2],
        })
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("INTERNAL_", serialized)
        for forbidden in (
            "file_path", "sha256", "reference_answer", "grading_rubric",
            "answer_pdf_pages", "content_hash", "review_status",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_generated_questions_have_no_exam_source_or_invented_year(self) -> None:
        question = self._question(difficulty=1)
        generated = question_metadata(self.database, question)
        self.assertIsNone(generated.source)
        self.assertEqual(generated.difficulty, 1)

        self.document.document_type = "sample_exam"
        self.document.exam_year = None
        self.database.commit()
        exam_question = self._question(revision_id=self.first_revision.id)
        source = question_metadata(self.database, exam_question).source
        self.assertEqual(source.document_type, "sample_exam")
        self.assertIsNone(source.exam_year)

    def test_historical_snapshot_is_not_replaced_by_newest_bank_revision(self) -> None:
        second_revision = self._revision(2, difficulty=5, pages=[6])
        self.database.add(second_revision)
        self.database.commit()
        previous_question = self._question(
            revision_id=self.first_revision.id, difficulty=2,
        )
        newer_question = self._question(revision_id=second_revision.id, difficulty=5)

        results = question_metadata_batch(
            self.database, [previous_question, newer_question],
        )

        self.assertEqual(results[previous_question.id].difficulty, 2)
        self.assertEqual(results[previous_question.id].source.pdf_pages, [1, 2])
        self.assertEqual(results[newer_question.id].difficulty, 5)
        self.assertEqual(results[newer_question.id].source.pdf_pages, [6])

    def test_batch_loading_does_not_add_queries_per_question(self) -> None:
        questions = [
            self._question(revision_id=self.first_revision.id)
            for _ in range(12)
        ]
        statements = []

        def record_query(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_query)
        try:
            results = question_metadata_batch(self.database, questions)
        finally:
            event.remove(self.engine, "before_cursor_execute", record_query)

        self.assertEqual(len(results), 12)
        self.assertLessEqual(len(statements), 2)

    def test_empty_batch_needs_no_database_queries_and_missing_name_has_stable_id(self) -> None:
        self.assertEqual(question_metadata_batch(self.database, []), {})
        question = self._question(node_ids=["python.unknown-history-node"])
        metadata = question_metadata(self.database, question)
        self.assertEqual(metadata.knowledge_points[0].id, "python.unknown-history-node")
        self.assertEqual(metadata.knowledge_points[0].name, "python.unknown-history-node")

    def test_public_schema_rejects_invalid_difficulty_and_internal_fields(self) -> None:
        for difficulty in (0, 6):
            with self.subTest(difficulty=difficulty):
                with self.assertRaises(ValidationError):
                    question_metadata(self.database, self._question(difficulty=difficulty))
        with self.assertRaises(ValidationError):
            PublicQuestionMetadata.model_validate({
                "difficulty": 2,
                "critic_content": {"reference_answer": "INTERNAL_ANSWER"},
            })


class RecordingWebSocket:
    def __init__(self) -> None:
        self.events = []

    async def broadcast(self, session_id: str, event) -> None:
        self.events.append(event.model_dump(mode="json"))


async def settle(orchestrator: LearningSessionOrchestrator) -> None:
    while orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))
        await asyncio.sleep(0)


class QuestionMetadataDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False,
        )
        with self.factory() as database:
            seed_database(database, CURRICULUM_DIR)
        self.provider = DemoMockLLMProvider()
        self.websocket = RecordingWebSocket()
        self.orchestrator = LearningSessionOrchestrator(
            provider=self.provider,
            websocket_manager=self.websocket,
            session_factory=self.factory,
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    def _assert_public_labels(self, metadata: dict) -> None:
        self.assertIsNotNone(metadata)
        self.assertIn(metadata["difficulty"], range(1, 6))
        self.assertTrue(metadata["knowledge_points"])
        for point in metadata["knowledge_points"]:
            self.assertEqual(set(point), {"id", "name"})
            self.assertNotEqual(point["id"], point["name"])
        self.assertIsNone(metadata["source"])
        self.assertEqual(set(metadata), {"difficulty", "knowledge_points", "source"})

    def test_initial_next_question_and_reloaded_history_keep_public_labels(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(CreateSessionRequest(
                learner_id="demo_user", module="python_iterator",
            ))
            await settle(self.orchestrator)
            first_metadata = created.current_question["question_metadata"]
            self._assert_public_labels(first_metadata)
            first_message = next(
                message for message in created.messages if message["role"] == "questioner"
            )
            self.assertEqual(first_message["question_metadata"], first_metadata)

            session_id = str(created.session_id)
            self.orchestrator.accept_message(session_id, "next(iterator)")
            await settle(self.orchestrator)
            self.orchestrator.accept_message(session_id, "下一题")
            await settle(self.orchestrator)
            ready = next(
                message for message in reversed(self.websocket.events)
                if message["type"] == "question_ready"
            )
            self._assert_public_labels(ready["payload"]["question_metadata"])
            self.assertNotEqual(ready["payload"]["question_id"], str(created.current_question_id))

            reloaded = LearningSessionOrchestrator(
                provider=self.provider,
                websocket_manager=self.websocket,
                session_factory=self.factory,
            ).get_session_response(session_id)
            self.assertEqual(
                reloaded.current_question["question_metadata"],
                ready["payload"]["question_metadata"],
            )
            question_messages = [
                message for message in reloaded.messages if message["role"] == "questioner"
            ]
            self.assertEqual(len(question_messages), 2)
            self.assertEqual(question_messages[0]["question_metadata"], first_metadata)
            for message in question_messages:
                self._assert_public_labels(message["question_metadata"])
            for message in reloaded.messages:
                if message["role"] != "questioner":
                    self.assertIsNone(message["question_metadata"])
            self.assertNotIn("critic_content", str(reloaded.model_dump(mode="json")))

        asyncio.run(scenario())

    def test_replacement_question_event_and_both_history_entries_keep_labels(self) -> None:
        async def scenario():
            created = await self.orchestrator.create_session(CreateSessionRequest(
                learner_id="demo_user", module="python_iterator",
            ))
            await settle(self.orchestrator)
            session_id = str(created.session_id)
            await self.orchestrator.replace_invalid_question(session_id, student_has_answered=False)
            await settle(self.orchestrator)

            ready = next(
                message for message in reversed(self.websocket.events)
                if message["type"] == "question_ready"
            )
            self._assert_public_labels(ready["payload"]["question_metadata"])
            self.assertNotEqual(ready["payload"]["question_id"], str(created.current_question_id))
            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(
                response.current_question["question_metadata"],
                ready["payload"]["question_metadata"],
            )
            question_messages = [
                message for message in response.messages if message["role"] == "questioner"
            ]
            self.assertEqual(len(question_messages), 2)
            for message in question_messages:
                self._assert_public_labels(message["question_metadata"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
