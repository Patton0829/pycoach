"""Exercise student exam sessions with the real reviewed bank and MockLLMProvider."""

import asyncio
from pathlib import Path
import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.sessions import router as sessions_router
from app.core.orchestrator import get_session_orchestrator
from app.llm.mock import DemoMockLLMProvider
from app.models.base import Base
from app.models.entities import (
    AssessmentEvidence,
    BankQuestionRevision,
    GraphUpdateEvent,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
)
from app.schemas.question_bank import QuestionBankImport
from app.schemas.session import CreateSessionRequest, SessionState
from app.seed import seed_database
from app.services.graph_service import GraphService
from app.services.question_bank_service import QuestionBankService
from app.services.session_orchestrator import LearningSessionOrchestrator


ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "python考试真题/结构化真题/ncre-python-sample"
EXAM_MODULE = "python_exam_practice"


class ExamMockLLMProvider(DemoMockLLMProvider):
    async def generate_structured(self, messages, schema):
        if schema.__name__ == "QuestionPacket":
            raise AssertionError("Exam practice must retrieve the reviewed bank, not generate a replacement.")
        return await super().generate_structured(messages, schema)


class RecordingWebSocket:
    def __init__(self):
        self.events = []

    async def broadcast(self, session_id, event):
        self.events.append(event.model_dump(mode="json"))


async def settle(orchestrator):
    while orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))
        await asyncio.sleep(0)


class ExamSessionFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.payload = QuestionBankImport.model_validate_json(
            (CORPUS / "bank_import.reviewed.json").read_text(encoding="utf-8")
        )
        with self.factory() as database:
            seed_database(database, ROOT / "curriculum/python_iterator_v1")
            seed_database(database, ROOT / "curriculum/python_foundation_v1")
            service = QuestionBankService(database)
            service.register_catalog(self.payload.catalog_chapters, self.payload.catalog_knowledge_nodes)
            document = service.register_document(self.payload.document)
            self.document_id = document.id
            for question in self.payload.questions:
                service.create_revision(document.id, question)
            database.commit()
        self.provider = ExamMockLLMProvider()
        self.websocket = RecordingWebSocket()
        self.orchestrator = LearningSessionOrchestrator(
            self.provider, self.websocket, session_factory=self.factory,
        )

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    async def create(self):
        response = await self.orchestrator.create_session(CreateSessionRequest(
            learner_id="demo_user", module=EXAM_MODULE,
        ))
        await settle(self.orchestrator)
        return str(response.session_id), self.current(str(response.session_id))

    async def send(self, session_id, text):
        self.orchestrator.accept_message(session_id, text)
        await settle(self.orchestrator)

    def current(self, session_id):
        response = self.orchestrator.get_session_response(session_id)
        with self.factory() as database:
            return database.get(Question, str(response.current_question_id))

    def counts(self, node_id):
        with self.factory() as database:
            row = database.scalar(select(LearnerKnowledgeNode).where(
                LearnerKnowledgeNode.learner_id == "demo_user",
                LearnerKnowledgeNode.knowledge_node_id == node_id,
            ))
            return (row.evaluated_question_count, row.correct_question_count, row.mastery) if row else (0, 0, 0)

    def evidence(self, round_id):
        with self.factory() as database:
            return list(database.scalars(select(AssessmentEvidence).where(
                AssessmentEvidence.round_id == round_id,
            )).all())

    @staticmethod
    def answer(question):
        return question.critic_content_json["acceptable_answers"][0]

    def test_start_and_reload_show_reviewed_source_and_public_metadata(self):
        async def scenario():
            session_id, question = await self.create()
            self.assertIsNotNone(question.bank_question_revision_id)
            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(response.state, SessionState.QUESTION_ACTIVE)
            self.assertEqual(response.chapter_question_set.chapter_id, EXAM_MODULE)
            self.assertEqual(response.chapter_question_set.target_question_count, 27)
            public = response.current_question["question_metadata"]
            self.assertIn(public["difficulty"], range(1, 6))
            self.assertTrue(public["knowledge_points"])
            self.assertEqual(public["source"]["document_type"], "sample_exam")
            self.assertIsNone(public["source"]["exam_year"])
            self.assertTrue(public["source"]["pdf_pages"])
            self.assertIn("样题", public["source"]["title"])
            message = next(item for item in response.messages if item["role"] == "questioner")
            self.assertEqual(message["question_metadata"], public)
            for forbidden in ("critic_content", "grading_rubric", "reference_answer", "file_path", "sha256"):
                self.assertNotIn(forbidden, str(public))
            self.assertFalse(any(name == "QuestionPacket" for name, _ in self.provider.calls))
        asyncio.run(scenario())

    def test_finalized_answer_updates_mapped_progress_once_and_can_be_seen_in_personal_graph(self):
        async def scenario():
            session_id, question = await self.create()
            node_id = question.knowledge_node_ids[0]
            await self.send(session_id, self.answer(question))
            self.assertEqual(self.counts(node_id), (0, 0, 0))
            self.assertEqual(self.evidence(question.round_id), [])
            await self.send(session_id, "下一题")
            self.assertEqual(self.counts(node_id), (1, 1, 0.05))
            evidence = self.evidence(question.round_id)
            self.assertEqual(len(evidence), len(question.knowledge_node_ids))
            self.assertTrue(all(item.counted for item in evidence))
            self.assertTrue(all(item.bank_question_revision_id == question.bank_question_revision_id for item in evidence))
            with self.factory() as database:
                graph = GraphService(database).get_knowledge_graph("demo_user")
                self.assertIn(node_id, {node.node_id for node in graph.nodes})
                event_count = database.scalar(select(func.count()).select_from(GraphUpdateEvent))
            current = self.current(session_id)
            await self.orchestrator.complete_round_summary(
                session_id, question.round_id, question.id, current.round_id,
            )
            self.assertEqual(self.counts(node_id), (1, 1, 0.05))
            with self.factory() as database:
                self.assertEqual(database.scalar(select(func.count()).select_from(GraphUpdateEvent)), event_count)
            event = next(item for item in self.websocket.events if item["type"] == "question_ready")
            self.assertTrue(event["payload"]["question_metadata"]["source"])
        asyncio.run(scenario())

    def test_all_reviewed_questions_are_distinct_and_last_next_request_finishes_the_exam(self):
        async def scenario():
            session_id, question = await self.create()
            stable_ids = []
            answered_questions = []
            for _ in range(27):
                with self.factory() as database:
                    revision = database.get(BankQuestionRevision, question.bank_question_revision_id)
                    self.assertEqual(revision.review_status, "approved")
                    stable_id = revision.bank_question_id
                self.assertNotIn(stable_id, stable_ids)
                stable_ids.append(stable_id)
                answered_questions.append(question)
                await self.send(session_id, self.answer(question))
                await self.send(session_id, "下一题")
                response = self.orchestrator.get_session_response(session_id)
                if response.state == SessionState.SESSION_ENDED:
                    break
                question = self.current(session_id)
            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(len(stable_ids), 27)
            self.assertEqual(response.state, SessionState.SESSION_ENDED)
            self.assertEqual(response.completed_question_count, 27)
            self.assertEqual(response.chapter_question_set.target_question_count, 27)
            self.assertEqual(response.chapter_question_set.current_question_slot, 27)
            with self.factory() as database:
                evidence = list(database.scalars(select(AssessmentEvidence)).all())
                expected_targets = sum(len(item.knowledge_node_ids) for item in answered_questions)
                self.assertEqual(len(evidence), expected_targets)
                self.assertTrue(all(item.counted for item in evidence))
                self.assertTrue(all(item.outcome == "correct" for item in evidence))
                rounds = list(database.scalars(select(LearningRound)).all())
                self.assertEqual(len(rounds), 27)
                self.assertTrue(all(item.discussion_summary_json is not None for item in rounds))
            self.assertFalse(any(name == "QuestionPacket" for name, _ in self.provider.calls))
        asyncio.run(scenario())

    def test_explicit_end_finalizes_answer_without_publishing_an_extra_question(self):
        async def scenario():
            session_id, question = await self.create()
            await self.send(session_id, self.answer(question))
            await self.send(session_id, "结束本次学习")
            response = self.orchestrator.get_session_response(session_id)
            self.assertEqual(response.state, SessionState.SESSION_ENDED)
            self.assertEqual(response.completed_question_count, 1)
            self.assertEqual(self.counts(question.knowledge_node_ids[0]), (1, 1, 0.05))
            self.assertFalse(any(item["type"] == "question_ready" for item in self.websocket.events))
            await self.orchestrator.prepare_candidate(session_id, critic_summary={})
            self.assertEqual(self.orchestrator.get_session_response(session_id).state, SessionState.SESSION_ENDED)
        asyncio.run(scenario())

    def test_repeating_the_same_original_in_a_new_session_does_not_count_again(self):
        async def scenario():
            with self.factory() as database:
                service = QuestionBankService(database)
                approved = list(database.scalars(select(BankQuestionRevision).where(
                    BankQuestionRevision.review_status == "approved",
                )).all())
                retained = approved[0].id
                for item in approved:
                    if item.id != retained:
                        service.review_revision(item.id, "invalid")
                database.commit()
            first_session, first_question = await self.create()
            await self.send(first_session, self.answer(first_question))
            await self.send(first_session, "结束本次学习")
            node_id = first_question.knowledge_node_ids[0]
            self.assertEqual(self.counts(node_id), (1, 1, 0.05))
            second_session, second_question = await self.create()
            self.assertEqual(first_question.bank_question_revision_id, second_question.bank_question_revision_id)
            await self.send(second_session, self.answer(second_question))
            await self.send(second_session, "结束本次学习")
            self.assertEqual(self.counts(node_id), (1, 1, 0.05))
            evidence = self.evidence(second_question.round_id)
            self.assertTrue(evidence)
            self.assertTrue(all(not item.counted and item.exclusion_reason == "repeat_question" for item in evidence))
        asyncio.run(scenario())

    def test_invalid_bank_question_is_replaced_with_another_reviewed_original(self):
        async def scenario():
            session_id, question = await self.create()
            with self.factory() as database:
                QuestionBankService(database).review_revision(question.bank_question_revision_id, "invalid")
                database.commit()
            await self.orchestrator.replace_invalid_question(session_id, student_has_answered=False)
            await settle(self.orchestrator)
            replacement = self.current(session_id)
            self.assertNotEqual(replacement.id, question.id)
            self.assertIsNotNone(replacement.bank_question_revision_id)
            self.assertNotEqual(replacement.bank_question_revision_id, question.bank_question_revision_id)
            with self.factory() as database:
                revision = database.get(BankQuestionRevision, replacement.bank_question_revision_id)
                self.assertEqual(revision.review_status, "approved")
            self.assertFalse(any(name == "QuestionPacket" for name, _ in self.provider.calls))
        asyncio.run(scenario())

    def test_empty_reviewed_bank_returns_api_error_without_orphan_session(self):
        with self.factory() as database:
            service = QuestionBankService(database)
            approved = list(database.scalars(select(BankQuestionRevision).where(
                BankQuestionRevision.review_status == "approved",
            )).all())
            for revision in approved:
                service.review_revision(revision.id, "invalid")
            database.commit()
        api = FastAPI()
        api.include_router(sessions_router)
        api.dependency_overrides[get_session_orchestrator] = lambda: self.orchestrator
        with TestClient(api) as client:
            response = client.post("/api/sessions", json={
                "learner_id": "demo_user", "module": EXAM_MODULE,
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("真题", response.json()["detail"])
        with self.factory() as database:
            self.assertEqual(database.scalar(select(func.count()).select_from(LearningSession)), 0)
            self.assertEqual(database.scalar(select(func.count()).select_from(LearningRound)), 0)

    def test_explicit_source_starts_exam_and_unknown_source_returns_api_error(self):
        api = FastAPI()
        api.include_router(sessions_router)
        api.dependency_overrides[get_session_orchestrator] = lambda: self.orchestrator
        with TestClient(api) as client:
            response = client.post("/api/sessions", json={
                "learner_id": "demo_user", "module": EXAM_MODULE,
                "source_document_id": self.document_id,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["chapter_question_set"]["target_question_count"], 27)
            unknown = client.post("/api/sessions", json={
                "learner_id": "demo_user", "module": EXAM_MODULE,
                "source_document_id": str(uuid4()),
            })
        self.assertEqual(unknown.status_code, 400)
        self.assertIn("source document", unknown.json()["detail"])
        with self.factory() as database:
            self.assertEqual(database.scalar(select(func.count()).select_from(LearningSession)), 1)
            self.assertEqual(database.scalar(select(func.count()).select_from(LearningRound)), 1)
