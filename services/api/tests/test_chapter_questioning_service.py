import unittest
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.entities import ChapterQuestionSet, LearningSession
from app.schemas.session import SessionState
from app.seed import seed_database
from app.services.chapter_questioning_service import ChapterQuestioningService

CURRICULUM_DIR = (
    Path(__file__).resolve().parents[3] / "curriculum" / "python_iterator_v1"
)


class ChapterQuestioningServiceTests(unittest.TestCase):
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

    def tearDown(self) -> None:
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_generates_ten_question_chapter_plan_from_learner_graph(self) -> None:
        with self.factory() as database:
            plan = ChapterQuestioningService(database).generate_plan("demo_user")

        self.assertEqual(plan.question_count, 10)
        self.assertEqual([item.slot for item in plan.questions], list(range(1, 11)))
        self.assertEqual(plan.learner_level, "novice")
        self.assertEqual(plan.questions[0].cognitive_goal, "recognize")
        self.assertEqual(plan.questions[0].question_type, "multiple_choice")
        self.assertIn(
            "iter_vs_next",
            [item.error_id for item in plan.active_error_priorities],
        )

    def test_persists_plan_and_builds_slot_constraints(self) -> None:
        with self.factory() as database:
            session = LearningSession(
                learner_id="demo_user",
                status=SessionState.QUESTION_GENERATING.value,
            )
            database.add(session)
            database.flush()

            service = ChapterQuestioningService(database)
            critic_summary, constraints = service.generation_inputs_for_slot(
                session,
                slot=2,
            )
            record = database.scalar(select(ChapterQuestionSet))

        self.assertIsNotNone(record)
        self.assertEqual(record.target_question_count, 10)
        self.assertEqual(
            critic_summary["chapter_question_blueprint"]["slot"],
            2,
        )
        self.assertEqual(
            constraints.preferred_question_type,
            critic_summary["chapter_question_blueprint"]["question_type"],
        )
        self.assertEqual(len(constraints.allowed_knowledge_node_ids), 1)

    def test_slots_after_planned_set_fall_back_to_default_constraints(self) -> None:
        with self.factory() as database:
            session = LearningSession(
                learner_id="demo_user",
                status=SessionState.QUESTION_GENERATING.value,
            )
            database.add(session)
            database.flush()

            critic_summary, constraints = ChapterQuestioningService(
                database
            ).generation_inputs_for_slot(session, slot=11)

        self.assertNotIn("chapter_question_blueprint", critic_summary)
        self.assertTrue(critic_summary["chapter_question_set"]["completed"])
        self.assertIsNone(constraints.preferred_question_type)


if __name__ == "__main__":
    unittest.main()
