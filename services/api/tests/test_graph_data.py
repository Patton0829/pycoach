import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.entities import (
    CurriculumChapter,
    GraphUpdateEvent,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    ConversationMessage,
    KnowledgeNode,
)
from app.schemas.critic import ErrorGraphUpdate, KnowledgeAssessment
from app.seed import load_tutorial_catalog, seed_database
from app.services.graph_service import GraphService
from app.services.assessment_service import AssessmentService

CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


class GraphDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        self.database: Session = self.session_factory()
        seed_database(self.database, CURRICULUM_DIR)

        def override_get_db():
            database = self.session_factory()
            try:
                yield database
            finally:
                database.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.database.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_seed_is_idempotent_and_preserves_personal_progress(self) -> None:
        learner_node = self.database.scalar(
            select(LearnerKnowledgeNode).where(
                LearnerKnowledgeNode.learner_id == "demo_user",
                LearnerKnowledgeNode.knowledge_node_id == "python.iterator.next",
            )
        )
        self.assertIsNotNone(learner_node)
        learner_node.mastery = 0.91
        learner_node.evaluated_question_count = 100
        learner_node.correct_question_count = 91
        learner_node.status = "mastered"
        knowledge_node = self.database.get(KnowledgeNode, "python.iterator.next")
        knowledge_node.runtime_enabled = False
        self.database.commit()

        result = seed_database(self.database, CURRICULUM_DIR)

        self.assertEqual(result.knowledge_nodes, 10)
        self.assertEqual(result.knowledge_edges, 10)
        self.assertEqual(result.error_types, 9)
        self.assertEqual(result.learners, 1)
        self.assertEqual(result.learner_knowledge_nodes, 5)
        self.assertEqual(result.learner_error_nodes, 1)
        self.assertAlmostEqual(learner_node.mastery, 0.91)
        self.assertEqual(learner_node.evaluated_question_count, 100)
        self.assertEqual(learner_node.correct_question_count, 91)
        self.assertEqual(learner_node.status, "mastered")
        self.assertFalse(knowledge_node.runtime_enabled)
        self.assertEqual(knowledge_node.chapter_id, "python_tutorial.ch09")
        self.assertEqual(knowledge_node.reference_section, "9.8")

    def test_tutorial_catalog_covers_existing_nodes_with_official_section_references(self) -> None:
        catalog = load_tutorial_catalog(CURRICULUM_DIR)
        self.assertIsNotNone(catalog)
        self.assertEqual(len(catalog.chapters), 17)
        expected_chapters = {f"python_tutorial.ch{number:02d}" for number in range(1, 17)}
        expected_chapters.add("python_supplementary")
        chapters = self.database.scalars(select(CurriculumChapter)).all()
        self.assertEqual({chapter.id for chapter in chapters}, expected_chapters)
        self.assertIsNone(self.database.get(CurriculumChapter, "python_iterator"))
        self.assertIsNone(self.database.get(CurriculumChapter, "python_supplementary").reference_url)
        self.assertEqual(
            self.database.get(CurriculumChapter, "python_tutorial.ch09").reference_url,
            "https://docs.python.org/3/tutorial/classes.html",
        )

        seed_database(self.database, CURRICULUM_DIR.parent / "python_foundation_v1")
        nodes = self.database.scalars(select(KnowledgeNode)).all()
        self.assertEqual(len(nodes), 45)
        self.assertEqual(set(catalog.node_metadata), {node.id for node in nodes})
        for node in nodes:
            self.assertIn(node.chapter_id, expected_chapters)
            self.assertTrue(node.reference_url.startswith("https://docs.python.org/3/tutorial/"))
            self.assertTrue(node.reference_section)
            self.assertFalse(node.is_supplementary)
        self.assertEqual(self.database.get(KnowledgeNode, "python.list").reference_section, "3.1.3")
        self.assertEqual(
            self.database.get(KnowledgeNode, "python.for_loop.protocol").reference_section, "4.2"
        )
        self.assertEqual(
            self.database.get(KnowledgeNode, "python.generator.intro").reference_section, "9.9"
        )

    def test_knowledge_graph_api_uses_student_visible_statuses(self) -> None:
        response = self.client.get("/api/learners/demo_user/knowledge-graph")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["learner_id"], "demo_user")
        self.assertEqual(len(payload["nodes"]), 10)
        self.assertNotIn("mastery", payload["nodes"][0])
        statuses = {node["display_status"] for node in payload["nodes"]}
        self.assertEqual(statuses, {"尚未测评"})
        self.assertEqual(payload["nodes"][0]["assessment_score"], 0)
        self.assertIsNone(payload["nodes"][0]["accuracy"])
        self.assertNotIn("score_policy_version", str(payload))
        class_nodes = [node for node in payload["nodes"]
                       if node["chapter_id"] == "python_tutorial.ch09"]
        self.assertEqual(len(class_nodes), 8)

    def test_error_graph_api_returns_only_personal_error_history(self) -> None:
        response = self.client.get("/api/learners/demo_user/error-graph")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["nodes"],
            [
                {
                    "error_id": "iter_vs_next",
                    "name": "iter 与 next 混淆",
                    "display_status": "需要巩固",
                }
            ],
        )
        self.assertNotIn("severity", payload["nodes"][0])

    def test_graph_api_returns_404_for_unknown_learner(self) -> None:
        response = self.client.get("/api/learners/missing/knowledge-graph")
        self.assertEqual(response.status_code, 404)

    def test_final_updates_create_audit_events(self) -> None:
        session = LearningSession(
            id=str(uuid4()),
            learner_id="demo_user",
            status="FEEDBACK_DISCUSSION",
        )
        learning_round = LearningRound(
            id=str(uuid4()),
            session_id=session.id,
            state="ROUND_FINALIZING",
        )
        self.database.add(session)
        self.database.flush()
        self.database.add(learning_round)
        self.database.flush()
        question = Question(
            id=str(uuid4()), session_id=session.id, round_id=learning_round.id,
            question_type="short_explanation", difficulty=1,
            student_content_json={"markdown": "next() 的作用是什么？"},
            critic_content_json={}, knowledge_node_ids=["python.iterator.next"],
            target_error_ids=[], pedagogical_strategy="retrieval_practice", status="completed",
        )
        self.database.add(question)
        self.database.flush()
        learning_round.question_id = question.id
        answer = ConversationMessage(
            id=str(uuid4()), session_id=session.id, round_id=learning_round.id,
            role="student", content_markdown="取得下一个元素并推进状态。",
        )
        self.database.add(answer)
        self.database.flush()

        service = GraphService(self.database)
        evidence = AssessmentService(self.database).commit_assessment(
            learner_id="demo_user",
            round_id=learning_round.id,
            assessment=KnowledgeAssessment(
                node_id="python.iterator.next",
                outcome="correct",
                reason="Student correctly used next(iterator).",
            ),
            basis_message_id=answer.id,
        )
        error_event = service.commit_error_update(
            learner_id="demo_user",
            round_id=learning_round.id,
            update=ErrorGraphUpdate(
                error_id="iter_vs_next",
                action="weaken",
                strength=1.0,
                reason="Student distinguished iter() from next().",
            ),
        )
        self.database.commit()

        events = self.database.scalars(
            select(GraphUpdateEvent).order_by(GraphUpdateEvent.graph_type)
        ).all()
        self.assertEqual(len(events), 2)
        knowledge_event = next(event for event in events if event.graph_type == "knowledge")
        self.assertIsNotNone(knowledge_event)
        self.assertEqual(knowledge_event.assessment_evidence_id, evidence.id)
        self.assertAlmostEqual(knowledge_event.before_value, 0)
        self.assertAlmostEqual(knowledge_event.after_value, 0.05)
        self.assertEqual(knowledge_event.after_evaluated_count, 1)
        self.assertEqual(knowledge_event.after_correct_count, 1)
        self.assertIsNotNone(error_event)
        self.assertAlmostEqual(error_event.before_value, 0.45)
        self.assertAlmostEqual(error_event.after_value, 0.35)


if __name__ == "__main__":
    unittest.main()
