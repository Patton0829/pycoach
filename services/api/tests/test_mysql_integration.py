"""Opt-in application checks against disposable real MySQL schemas.

TEST_MYSQL_URL identifies a server/account, never an application schema to modify.
All LLM work in this module uses the deterministic mock provider.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier
import unittest
from uuid import uuid4

from alembic import command
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.llm.mock import DemoMockLLMProvider
from app.models.entities import (
    AssessmentEvidence,
    ConversationMessage,
    GraphUpdateEvent,
    Learner,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
)
from app.schemas.assessment import assessment_metrics
from app.schemas.critic import KnowledgeAssessment
from app.schemas.question_bank import (
    QuestionBankImport,
    QuestionBankQuery,
    import_from_exam_example,
)
from app.schemas.session import CreateSessionRequest
from app.seed import seed_database
from app.services.assessment_service import AssessmentService
from app.services.question_bank_service import QuestionBankService
from app.services.session_orchestrator import LearningSessionOrchestrator
from tests.test_database_migrations import migration_config
from tests.test_question_bank import question_definition, source_document

CURRICULUM_DIR = Path(__file__).resolve().parents[3] / "curriculum/python_iterator_v1"


class RecordingWebSocket:
    def __init__(self):
        self.events = []

    async def broadcast(self, session_id, event):
        self.events.append(event.model_dump(mode="json"))


async def settle(orchestrator):
    while orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))
        await asyncio.sleep(0)


@unittest.skipUnless(os.getenv("TEST_MYSQL_URL"), "TEST_MYSQL_URL is not configured")
class MySQLApplicationIntegrationTests(unittest.TestCase):
    def setUp(self):
        supplied_url = make_url(os.environ["TEST_MYSQL_URL"])
        if supplied_url.drivername != "mysql+pymysql":
            self.fail("TEST_MYSQL_URL must use mysql+pymysql")
        self.database_name = "pycoach_test_" + uuid4().hex
        self.admin = create_engine(supplied_url.set(database=None))
        self.engine = None
        self.addCleanup(self.cleanup_database)
        with self.admin.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE `{self.database_name}` CHARACTER SET utf8mb4 "
                    "COLLATE utf8mb4_unicode_ci"
                )
            )
        self.engine = create_engine(
            supplied_url.set(database=self.database_name), pool_pre_ping=True
        )
        with self.engine.connect() as connection:
            command.upgrade(migration_config(connection), "head")
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.factory() as database:
            seed_database(database, CURRICULUM_DIR)

    def cleanup_database(self):
        if self.engine is not None:
            self.engine.dispose()
        with self.admin.begin() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{self.database_name}`"))
        self.admin.dispose()

    def new_learner(self, database):
        learner = Learner(id=str(uuid4()), display_name="迭代器测试学生")
        database.add(learner)
        database.flush()
        return learner

    def new_round(self, database, learner_id, revision_id):
        session = LearningSession(learner_id=learner_id, status="ROUND_FINALIZING")
        database.add(session)
        database.flush()
        learning_round = LearningRound(session_id=session.id, state="ROUND_FINALIZING")
        database.add(learning_round)
        database.flush()
        question = QuestionBankService(database).attach_to_round(
            revision_id, session.id, learning_round.id
        )
        session.current_question_id = question.id
        message = ConversationMessage(
            session_id=session.id,
            round_id=learning_round.id,
            role="student",
            content_markdown="独立作答：2",
            critic_intent="answer_attempt",
        )
        database.add(message)
        database.flush()
        return learning_round, message, question

    def state(self, learner_id, node_id="python.iterator.state"):
        with self.factory() as database:
            return database.scalar(
                select(LearnerKnowledgeNode).where(
                    LearnerKnowledgeNode.learner_id == learner_id,
                    LearnerKnowledgeNode.knowledge_node_id == node_id,
                )
            )

    def test_draft_import_approved_retrieval_snapshot_and_per_node_assessment(self):
        example_path = Path(__file__).resolve().parents[3] / (
            "python考试真题/结构化示例/前三题.json"
        )
        if example_path.is_file():
            imported = import_from_exam_example(
                json.loads(example_path.read_text(encoding="utf-8"))
            )
        else:
            imported = QuestionBankImport(
                document=source_document(sha256="b" * 64),
                questions=[
                    question_definition(
                        bank_question_id=f"draft-fixture-{index}",
                        question_number=str(index),
                        knowledge_targets=[],
                        review_status="draft",
                    )
                    for index in range(1, 4)
                ],
            )
        with self.factory.begin() as database:
            service = QuestionBankService(database)
            source = service.register_document(imported.document)
            drafts = [service.create_revision(source.id, item) for item in imported.questions]
            self.assertEqual(len(drafts), 3)
            self.assertTrue(all(revision.review_status == "draft" for revision in drafts))
            self.assertEqual(service.find_candidates(QuestionBankQuery()), [])
            document = service.register_document(source_document(title="迭代状态真题测试来源"))
            revision = service.create_revision(document.id, question_definition())
            candidates = service.find_candidates(
                QuestionBankQuery(knowledge_node_ids=["python.iterator.state"], difficulty_max=2)
            )
            self.assertEqual([item.revision_id for item in candidates], [revision.id])
            self.assertNotIn("critic_content", candidates[0].model_dump())
            self.assertEqual(
                service.materialize(revision.id).knowledge_node_ids, ["python.iterator.state"]
            )
            learner = self.new_learner(database)
            learning_round, message, question = self.new_round(database, learner.id, revision.id)
            evidence = AssessmentService(database).commit_assessment(
                learner.id,
                learning_round.id,
                KnowledgeAssessment(
                    node_id="python.iterator.state",
                    outcome="correct",
                    reason="Independent state tracing.",
                ),
                basis_message_id=message.id,
            )
            self.assertTrue(evidence.counted)
            self.assertEqual(evidence.bank_question_revision_id, revision.id)
            self.assertEqual(question.student_content_json, revision.student_content_json)
            learner_id = learner.id
            revision_id = revision.id
        state = self.state(learner_id)
        self.assertEqual((state.evaluated_question_count, state.correct_question_count), (1, 1))
        self.assertEqual(state.mastery, 0.05)
        with self.factory.begin() as database:
            # A new round using the same stable source identity does not add a sample.
            learning_round, message, _ = self.new_round(database, learner_id, revision_id)
            duplicate = AssessmentService(database).commit_assessment(
                learner_id,
                learning_round.id,
                KnowledgeAssessment(
                    node_id="python.iterator.state",
                    outcome="correct",
                    reason="Repeated source item.",
                ),
                basis_message_id=message.id,
            )
            self.assertFalse(duplicate.counted)
            self.assertEqual(duplicate.exclusion_reason, "repeat_question")
        self.assertEqual(self.state(learner_id).evaluated_question_count, 1)

    def test_real_mysql_twenty_question_boundary_retains_exact_double_threshold(self):
        with self.factory.begin() as database:
            service = QuestionBankService(database)
            source = service.register_document(source_document())
            learner = self.new_learner(database)
            learner_id = learner.id
            for index in range(1, 22):
                revision = service.create_revision(
                    source.id,
                    question_definition(
                        bank_question_id=f"boundary-q{index}", question_number=str(index)
                    ),
                )
                learning_round, message, _ = self.new_round(database, learner_id, revision.id)
                AssessmentService(database).commit_assessment(
                    learner_id,
                    learning_round.id,
                    KnowledgeAssessment(
                        node_id="python.iterator.state",
                        outcome="incorrect" if index <= 4 or index == 21 else "correct",
                        reason="Independent boundary fixture.",
                    ),
                    basis_message_id=message.id,
                )
                if index in {19, 20, 21}:
                    state = database.scalar(
                        select(LearnerKnowledgeNode).where(
                            LearnerKnowledgeNode.learner_id == learner_id,
                            LearnerKnowledgeNode.knowledge_node_id == "python.iterator.state",
                        )
                    )
                    database.refresh(state)
                    metrics = assessment_metrics(
                        state.evaluated_question_count, state.correct_question_count
                    )
                    self.assertEqual(state.evaluated_question_count, index)
                    self.assertEqual(state.mastery, metrics.assessment_score)
                    if index == 19:
                        self.assertEqual(metrics.assessment_stage, "collecting")
                        self.assertEqual(state.mastery, 0.75)
                    elif index == 20:
                        self.assertEqual(metrics.assessment_stage, "sample_ready")
                        self.assertEqual(state.mastery, 0.8)
                        self.assertEqual(state.status, "mastered")
                    else:
                        self.assertEqual(state.mastery, 16 / 21)
                        self.assertEqual(state.status, "needs_review")
        self.assertEqual(self.state(learner_id).correct_question_count, 16)

    def test_mysql_row_locks_prevent_concurrent_double_counting(self):
        with self.factory.begin() as database:
            bank = QuestionBankService(database)
            source = bank.register_document(source_document())
            revision = bank.create_revision(source.id, question_definition())
            learner_id = self.new_learner(database).id
            first_round, first_message, _ = self.new_round(database, learner_id, revision.id)
            second_round, second_message, _ = self.new_round(database, learner_id, revision.id)
            round_messages = [
                (first_round.id, first_message.id),
                (second_round.id, second_message.id),
            ]
        barrier = Barrier(2)

        def assess(round_and_message):
            round_id, message_id = round_and_message
            with self.factory.begin() as database:
                barrier.wait(timeout=10)
                evidence = AssessmentService(database).commit_assessment(
                    learner_id,
                    round_id,
                    KnowledgeAssessment(
                        node_id="python.iterator.state",
                        outcome="correct",
                        reason="Concurrent original source assessment.",
                    ),
                    basis_message_id=message_id,
                )
                return evidence.id, evidence.counted

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(assess, round_messages, timeout=20))
        self.assertEqual(sum(counted for _, counted in results), 1)
        self.assertEqual(self.state(learner_id).evaluated_question_count, 1)
        # Replaying both already finalized rounds changes neither evidence nor audit counts.
        with self.factory.begin() as database:
            for round_id, message_id in round_messages:
                AssessmentService(database).commit_assessment(
                    learner_id,
                    round_id,
                    KnowledgeAssessment(
                        node_id="python.iterator.state", outcome="correct", reason="Replay."
                    ),
                    basis_message_id=message_id,
                )
            self.assertEqual(
                database.scalar(select(func.count()).select_from(AssessmentEvidence)), 2
            )
            self.assertEqual(database.scalar(select(func.count()).select_from(GraphUpdateEvent)), 2)

    def test_case_insensitive_learner_identity_cannot_bypass_generated_question_deduplication(self):
        with self.factory.begin() as database:
            bank = QuestionBankService(database)
            document = bank.register_document(source_document())
            revision_id = bank.create_revision(document.id, question_definition()).id
            learner_id = self.new_learner(database).id
        counted = []
        for identity in (learner_id, learner_id.upper()):
            with self.factory.begin() as database:
                learning_round, message, question = self.new_round(database, identity, revision_id)
                # Exercise the content-based path used by generated questions.
                question.bank_question_revision_id = None
                database.flush()
                evidence = AssessmentService(database).commit_assessment(
                    identity, learning_round.id,
                    KnowledgeAssessment(
                        node_id="python.iterator.state", outcome="correct",
                        reason="The same student must have one canonical counting identity.",
                    ),
                    basis_message_id=message.id,
                )
                counted.append(evidence.counted)
        self.assertEqual(counted, [True, False])
        self.assertEqual(self.state(learner_id).evaluated_question_count, 1)

    def test_mock_agent_round_updates_mysql_only_after_finalization(self):
        provider = DemoMockLLMProvider()
        websocket = RecordingWebSocket()
        orchestrator = LearningSessionOrchestrator(
            provider, websocket, session_factory=self.factory
        )

        async def scenario():
            created = await orchestrator.create_session(
                CreateSessionRequest(learner_id="demo_user", module="python_iterator")
            )
            await settle(orchestrator)
            session_id = str(created.session_id)
            with self.factory() as database:
                question = database.get(Question, str(created.current_question_id))
                node_id = question.knowledge_node_ids[0]
                answer = question.critic_content_json["acceptable_answers"][0]
            orchestrator.accept_message(session_id, answer)
            await settle(orchestrator)
            with self.factory() as database:
                self.assertEqual(
                    database.scalar(select(func.count()).select_from(AssessmentEvidence)), 0
                )
            orchestrator.accept_message(session_id, "结束本次学习")
            await settle(orchestrator)
            state = self.state("demo_user", node_id)
            self.assertEqual((state.evaluated_question_count, state.correct_question_count), (1, 1))
            self.assertEqual(state.mastery, 0.05)
            with self.factory() as database:
                evidence = database.scalar(
                    select(AssessmentEvidence).where(
                        AssessmentEvidence.round_id == question.round_id
                    )
                )
                self.assertTrue(evidence.counted)
                self.assertIsNotNone(evidence.basis_message_id)
            self.assertTrue(any(name == "DiscussionSummary" for name, _ in provider.calls))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
