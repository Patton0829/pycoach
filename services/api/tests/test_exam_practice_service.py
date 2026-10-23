import json
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.entities import (
    AssessmentEvidence,
    ChapterQuestionSet,
    KnowledgeNode,
    Learner,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    QuestionReviewRecord,
)
from app.schemas.question_bank import BankQuestionRevisionInput, SourceDocumentInput
from app.services.exam_practice_service import EXAM_MODULE_ID, ExamPracticeService
from app.services.question_bank_service import QuestionBankService


class ExamPracticeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.database = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.database.add(Learner(id="learner", display_name="Learner"))
        for node_id in ("exam.node_a", "exam.node_b"):
            self.database.add(KnowledgeNode(
                id=node_id, name=node_id, description="Exam-only knowledge",
                difficulty=1, learning_objective="Identify the source concept.",
                runtime_enabled=False,
            ))
        self.database.flush()
        self.bank = QuestionBankService(self.database)
        self.source = self.bank.register_document(SourceDocumentInput(
            title="Reviewed sample paper", document_type="sample_exam", exam_year=None,
            file_path="private/source.pdf", sha256="a" * 64, page_count=3,
        ))
        self.easy = self._revision("q001", 1, "exam.node_a")
        self.hard = self._revision("q002", 4, "exam.node_a")
        self.other = self._revision("q003", 1, "exam.node_b")
        self.database.commit()
        self.service = ExamPracticeService(self.database)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.database.close()
        self.engine.dispose()

    def _revision(self, stable_id, difficulty, node_id, *, revision=1, status="approved", source=None):
        return self.bank.create_revision((source or self.source).id, BankQuestionRevisionInput(
            bank_question_id=stable_id, question_number=stable_id,
            revision=revision, question_type="short_explanation", difficulty=difficulty,
            difficulty_reason="Reason about a source concept.", cognitive_goal="explain",
            original_content={"stem": f"Original source item {stable_id}."},
            student_content={"markdown": f"Explain source item {stable_id}, version {revision}."},
            critic_content={
                "learning_objective": "Identify the source concept.",
                "reference_answer": "INTERNAL_REFERENCE_SECRET",
                "acceptable_answers": ["INTERNAL_REFERENCE_SECRET"],
                "grading_rubric": {"correct": "INTERNAL_RUBRIC_SECRET"},
                "expected_reasoning": "INTERNAL_REASONING_SECRET",
            },
            source_locations={"question_pdf_pages": [1], "answer_pdf_pages": [3]},
            answer_provenance={"origin": "project_annotation"},
            knowledge_targets=[{
                "knowledge_node_id": node_id, "role": "assessed", "is_primary": True,
                "assessment_criterion": "Identifies the source concept independently.",
            }],
            review_status=status,
        ))

    def _session(self, revisions=None, source_id=None):
        session = LearningSession(learner_id="learner", status="QUESTION_ACTIVE")
        self.database.add(session)
        self.database.flush()
        learning_round = LearningRound(session_id=session.id, state="QUESTION_ACTIVE")
        self.database.add(learning_round)
        self.database.flush()
        self.database.add(ChapterQuestionSet(
            session_id=session.id, learner_id="learner", chapter_id=EXAM_MODULE_ID,
            chapter_title="真题测试", target_question_count=3, learner_level="novice",
            average_mastery=0.0,
            blueprint_json={
                "mode": "exam", "source_document_id": source_id,
                "bank_revision_ids": [item.id for item in (revisions if revisions is not None else [self.easy, self.hard, self.other])],
            },
        ))
        self.database.commit()
        return session, learning_round

    def _profile(self, node_id, n, c):
        profile = self.database.scalar(select(LearnerKnowledgeNode).where(
            LearnerKnowledgeNode.learner_id == "learner",
            LearnerKnowledgeNode.knowledge_node_id == node_id,
        ))
        if profile is None:
            profile = LearnerKnowledgeNode(learner_id="learner", knowledge_node_id=node_id)
            self.database.add(profile)
        profile.evaluated_question_count = n
        profile.correct_question_count = c
        # Selection must use the evidence counts rather than stale legacy scores.
        profile.mastery = 0.99
        self.database.commit()

    def test_latest_invalid_or_draft_revision_never_revives_older_approved_answer(self):
        self._revision("q001", 1, "exam.node_a", revision=2, status="invalid")
        self._revision("q002", 4, "exam.node_a", revision=2, status="draft")
        self.assertEqual([item.id for item in self.service.approved_revisions()], [self.other.id])
        paper = self.service.list_papers()[0]
        self.assertEqual(paper.available_question_count, 1)
        self.assertEqual(paper.excluded_question_count, 2)

    def test_source_filter_and_unknown_source_are_explicit(self):
        second = self.bank.register_document(SourceDocumentInput(
            title="Other paper", document_type="past_exam", exam_year=2020,
            file_path="private/other.pdf", sha256="b" * 64, page_count=3,
        ))
        other_revision = self._revision("other-q1", 1, "exam.node_a", source=second)
        self.assertEqual([item.id for item in self.service.approved_revisions(second.id)], [other_revision.id])
        with self.assertRaises(ValueError):
            self.service.approved_revisions(str(uuid4()))

    def test_catalog_api_contains_only_public_paper_information(self):
        def override_database():
            yield self.database

        app.dependency_overrides[get_db] = override_database
        response = TestClient(app).get("/api/exams")
        self.assertEqual(response.status_code, 200)
        paper = response.json()[0]
        self.assertEqual(set(paper), {
            "id", "title", "document_type", "exam_year", "available_question_count",
            "excluded_question_count", "question_types",
        })
        self.assertEqual(paper["available_question_count"], 3)
        self.assertIsNone(paper["exam_year"])
        rendered = json.dumps(paper)
        for private in ("PRIVATE", "private/", "SECRET", "reference_answer", "grading_rubric", "sha256"):
            self.assertNotIn(private, rendered)

    def test_difficulty_matches_counts_and_weak_nodes_receive_priority(self):
        session, learning_round = self._session([self.easy, self.hard])
        first = self.service.create_question(session.id, learning_round.id)
        self.assertEqual(first.bank_question_revision_id, self.easy.id)
        self._profile("exam.node_a", 40, 38)
        advanced, advanced_round = self._session([self.easy, self.hard])
        harder = self.service.create_question(advanced.id, advanced_round.id)
        self.assertEqual(harder.bank_question_revision_id, self.hard.id)

        self._profile("exam.node_a", 20, 5)
        self._profile("exam.node_b", 20, 19)
        weak, weak_round = self._session([self.easy, self.other])
        question = self.service.create_question(weak.id, weak_round.id)
        self.assertEqual(question.knowledge_node_ids, ["exam.node_a"])

    def test_session_never_repeats_a_stable_identity_and_exhaustion_is_finite(self):
        session, learning_round = self._session()
        snapshots = []
        for _ in range(3):
            snapshots.append(self.service.create_question(session.id, learning_round.id, "candidate_stale"))
        self.assertEqual(len({item.bank_question_revision_id for item in snapshots}), 3)
        self.assertIsNone(self.service.create_question(session.id, learning_round.id))
        second, second_round = self._session()
        self.assertIsNotNone(self.service.create_question(second.id, second_round.id))

    def test_cross_session_counted_original_is_deprioritized_but_review_is_allowed(self):
        session, learning_round = self._session([self.easy])
        first = self.service.create_question(session.id, learning_round.id)
        self.database.add(AssessmentEvidence(
            learner_id="learner", round_id=learning_round.id, question_id=first.id,
            bank_question_id=self.easy.bank_question_id, bank_question_revision_id=self.easy.id,
            knowledge_node_id="exam.node_a", outcome="correct", assistance="none",
            counted=True, counted_question_key="c" * 64, reason="Independent answer.",
        ))
        self.database.commit()
        second, second_round = self._session([self.easy, self.hard])
        fresh = self.service.create_question(second.id, second_round.id)
        self.assertEqual(fresh.bank_question_revision_id, self.hard.id)
        third, third_round = self._session([self.easy])
        self.assertIsNotNone(self.service.create_question(third.id, third_round.id))

    def test_snapshot_and_review_preserve_the_chosen_version_and_caller_transaction(self):
        session, learning_round = self._session([self.easy])
        question = self.service.create_question(session.id, learning_round.id)
        self.assertNotEqual(question.id, self.easy.id)
        self.assertEqual(question.student_content_json, self.easy.student_content_json)
        review = self.database.scalar(select(QuestionReviewRecord).where(
            QuestionReviewRecord.question_id == question.id,
        ))
        self.assertEqual(review.status, "approved")
        self.assertEqual(question.knowledge_node_ids, ["exam.node_a"])
        self.assertEqual(question.bank_question_revision_id, self.easy.id)
        self.database.rollback()
        self.assertEqual(self.database.scalar(select(func.count()).select_from(Question)), 0)
        self.assertEqual(self.database.scalar(select(func.count()).select_from(QuestionReviewRecord)), 0)

    def test_fixed_pool_rechecks_newer_revocations_without_rewriting_history(self):
        session, learning_round = self._session([self.easy])
        question = self.service.create_question(session.id, learning_round.id)
        self.database.commit()
        original_content = dict(question.student_content_json)
        self._revision("q001", 3, "exam.node_a", revision=2, status="invalid")
        self.database.commit()
        another, another_round = self._session([self.easy])
        self.assertIsNone(self.service.create_question(another.id, another_round.id))
        self.assertEqual(question.student_content_json, original_content)
        self.assertEqual(question.bank_question_revision_id, self.easy.id)

    def test_exam_plan_is_required_and_round_must_match_session(self):
        session, learning_round = self._session()
        plan = self.database.scalar(select(ChapterQuestionSet).where(
            ChapterQuestionSet.session_id == session.id,
        ))
        plan.chapter_id = "python_iterator"
        self.database.flush()
        with self.assertRaises(ValueError):
            self.service.create_question(session.id, learning_round.id)
        with self.assertRaises(ValueError):
            self.service.create_question(session.id, str(uuid4()))


if __name__ == "__main__":
    unittest.main()
