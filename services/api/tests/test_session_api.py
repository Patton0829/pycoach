import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.orchestrator import get_session_orchestrator
from app.llm.mock import DemoMockLLMProvider
from app.main import app
from app.models.base import Base
from app.seed import seed_database
from app.services.session_orchestrator import LearningSessionOrchestrator
from app.services.websocket_manager import session_websocket_manager

CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


class SessionApiIntegrationTests(unittest.TestCase):
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
        self.orchestrator = LearningSessionOrchestrator(
            DemoMockLLMProvider(),
            session_websocket_manager,
            session_factory=self.factory,
        )
        app.dependency_overrides[get_session_orchestrator] = (
            lambda: self.orchestrator
        )

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    @staticmethod
    def receive_until(websocket, expected_type: str) -> tuple[dict, list[dict]]:
        received = []
        for _ in range(40):
            event = websocket.receive_json()
            received.append(event)
            if event["type"] == expected_type:
                return event, received
        raise AssertionError(f"Did not receive event type: {expected_type}")

    def test_rest_202_and_websocket_complete_one_round(self) -> None:
        with TestClient(app) as client:
            created = client.post(
                "/api/sessions",
                json={
                    "learner_id": "demo_user",
                    "module": "python_iterator",
                },
            )
            self.assertEqual(created.status_code, 200)
            session_id = created.json()["session_id"]
            self.assertEqual(created.json()["state"], "QUESTION_ACTIVE")

            with client.websocket_connect(
                f"/ws/sessions/{session_id}"
            ) as websocket:
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "connection_ready")

                accepted = client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"content": "iter(iterator)"},
                )
                self.assertEqual(accepted.status_code, 202)
                self.assertEqual(accepted.json()["status"], "processing")
                self.assertEqual(
                    accepted.json()["session_state"],
                    "CRITIC_PROCESSING",
                )

                critic_event, critic_events = self.receive_until(
                    websocket,
                    "critic_reply_ready",
                )
                self.assertIn(
                    "message_stream_delta",
                    [event["type"] for event in critic_events],
                )
                self.assertEqual(critic_event["type"], "critic_reply_ready")
                self.assertEqual(
                    critic_event["payload"]["session_state"],
                    "FEEDBACK_DISCUSSION",
                )

                next_accepted = client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"content": "下一题"},
                )
                self.assertEqual(next_accepted.status_code, 202)

                next_critic, _ = self.receive_until(
                    websocket,
                    "critic_reply_ready",
                )
                question_event, _ = self.receive_until(
                    websocket,
                    "question_ready",
                )
                summary_event, _ = self.receive_until(
                    websocket,
                    "session_summary_ready",
                )
                self.assertEqual(next_critic["type"], "critic_reply_ready")
                self.assertEqual(question_event["type"], "question_ready")
                self.assertEqual(summary_event["type"], "session_summary_ready")
                self.assertEqual(
                    summary_event["payload"]["completed_question_count"],
                    1,
                )

            recovered = client.get(f"/api/sessions/{session_id}")
            self.assertEqual(recovered.status_code, 200)
            payload = recovered.json()
            self.assertEqual(payload["state"], "QUESTION_ACTIVE")
            self.assertEqual(payload["completed_question_count"], 1)
            self.assertNotIn("critic_content", str(payload))
            self.assertNotIn("provisional_knowledge_updates", str(payload))


if __name__ == "__main__":
    unittest.main()
