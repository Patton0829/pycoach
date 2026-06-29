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
    GraphUpdateEvent,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
)
from app.schemas.critic import ErrorGraphUpdate, KnowledgeGraphUpdate
from app.seed import seed_database
from app.services.graph_service import GraphService

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
        learner_node.status = "mastered"
        self.database.commit()

        result = seed_database(self.database, CURRICULUM_DIR)

        self.assertEqual(result.knowledge_nodes, 10)
        self.assertEqual(result.knowledge_edges, 10)
        self.assertEqual(result.error_types, 9)
        self.assertEqual(result.learners, 1)
        self.assertEqual(result.learner_knowledge_nodes, 5)
        self.assertEqual(result.learner_error_nodes, 1)
        self.assertAlmostEqual(learner_node.mastery, 0.91)
        self.assertEqual(learner_node.status, "mastered")

    def test_knowledge_graph_api_uses_student_visible_statuses(self) -> None:
        response = self.client.get("/api/learners/demo_user/knowledge-graph")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["learner_id"], "demo_user")
        self.assertEqual(len(payload["nodes"]), 10)
        self.assertNotIn("mastery", payload["nodes"][0])
        statuses = {node["display_status"] for node in payload["nodes"]}
        self.assertIn("基本掌握", statuses)
        self.assertIn("正在学习", statuses)
        self.assertIn("尚未学习", statuses)

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
        self.database.add_all([session, learning_round])
        self.database.commit()

        service = GraphService(self.database)
        knowledge_event = service.commit_knowledge_update(
            learner_id="demo_user",
            round_id=learning_round.id,
            update=KnowledgeGraphUpdate(
                node_id="python.iterator.next",
                evidence="positive",
                strength=1.0,
                reason="Student correctly used next(iterator).",
            ),
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
        self.assertIsNotNone(knowledge_event)
        self.assertAlmostEqual(knowledge_event.before_value, 0.42)
        self.assertAlmostEqual(knowledge_event.after_value, 0.54)
        self.assertIsNotNone(error_event)
        self.assertAlmostEqual(error_event.before_value, 0.45)
        self.assertAlmostEqual(error_event.after_value, 0.35)


if __name__ == "__main__":
    unittest.main()
