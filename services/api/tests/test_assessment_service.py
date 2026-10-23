import unittest
from datetime import datetime
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.entities import (
    AssessmentEvidence,
    BankQuestion,
    BankQuestionRevision,
    ConversationMessage,
    GraphUpdateEvent,
    KnowledgeNode,
    Learner,
    LearnerKnowledgeNode,
    LearningRound,
    LearningSession,
    Question,
    QuestionKnowledgeMapping,
    SourceDocument,
)
from app.schemas.assessment import assessment_metrics
from app.schemas.critic import KnowledgeAssessment, KnowledgeGraphUpdate
from app.services.assessment_service import AssessmentContextError, AssessmentService
from app.services.graph_service import GraphService

NODE = "python.iterator.exhaustion"
OTHER_NODE = "python.stop_iteration"


class AssessmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.database = Session(self.engine, autoflush=False, expire_on_commit=False)
        self.database.add(Learner(id="student", display_name="Student"))
        self.database.add_all([
            KnowledgeNode(id=node, name=node, description="Test concept", difficulty=2,
                          learning_objective="Understand exhaustion")
            for node in [NODE, OTHER_NODE]
        ])
        self.database.commit()
        self.service = AssessmentService(self.database)

    def tearDown(self) -> None:
        self.database.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def make_round(self, *, revision=None, nodes=None, markdown=None):
        session = LearningSession(learner_id="student", status="ROUND_FINALIZING")
        self.database.add(session)
        self.database.flush()
        learning_round = LearningRound(session_id=session.id, state="ROUND_FINALIZING")
        self.database.add(learning_round)
        self.database.flush()
        question = Question(
            id=str(uuid4()), session_id=session.id, round_id=learning_round.id,
            question_type="output_prediction", difficulty=2,
            knowledge_node_ids=nodes or [NODE], target_error_ids=[],
            student_content_json={"markdown": markdown or f"Unique question {uuid4()}"},
            critic_content_json={"reference_answer": "StopIteration"},
            pedagogical_strategy="retrieval_practice", status="completed",
            bank_question_revision_id=revision.id if revision else None,
        )
        self.database.add(question)
        self.database.flush()
        learning_round.question_id = question.id
        message = ConversationMessage(
            session_id=session.id, round_id=learning_round.id,
            role="student", content_markdown="My answer",
        )
        self.database.add(message)
        self.database.commit()
        return learning_round, question, message

    def assess(self, learning_round, message, outcome="correct", node=NODE, **kwargs):
        return self.service.commit_assessment(
            "student", learning_round.id,
            KnowledgeAssessment(node_id=node, outcome=outcome, reason="Final node judgement"),
            basis_message_id=message.id if message else None,
            **kwargs,
        )

    def state(self, node=NODE):
        return self.database.scalar(select(LearnerKnowledgeNode).where(
            LearnerKnowledgeNode.learner_id == "student",
            LearnerKnowledgeNode.knowledge_node_id == node,
        ))

    def count(self, model):
        return self.database.scalar(select(func.count()).select_from(model))

    def bank_revision(self, *, bank=None, revision=1, mapping_role="assessed"):
        if bank is None:
            document = SourceDocument(
                title="Test source", document_type="sample_exam", file_path="test.pdf",
                sha256=uuid4().hex + uuid4().hex, page_count=1,
            )
            self.database.add(document)
            self.database.flush()
            bank = BankQuestion(
                id=f"bank-{uuid4()}", source_document_id=document.id, question_number="1",
            )
            self.database.add(bank)
            self.database.flush()
        record = BankQuestionRevision(
            bank_question_id=bank.id, revision=revision,
            question_type="output_prediction", difficulty=2,
            original_content_json={"stem": "Test original"},
            student_content_json={"markdown": "Test question"},
            critic_content_json={"reference_answer": "StopIteration"},
            source_locations_json={"question_pdf_pages": [1]},
            review_status="approved", content_hash=uuid4().hex + uuid4().hex,
        )
        self.database.add(record)
        self.database.flush()
        self.database.add(QuestionKnowledgeMapping(
            bank_question_revision_id=record.id, knowledge_node_id=NODE,
            role=mapping_role, is_primary=mapping_role == "assessed",
        ))
        self.database.commit()
        return bank, record

    def test_first_nineteenth_twentieth_and_twenty_first_samples(self):
        self.assertIsNone(assessment_metrics(0, 0).accuracy)
        for i in range(21):
            learning_round, _, message = self.make_round()
            self.assess(learning_round, message, "correct" if i < 20 else "incorrect")
            self.database.commit()
            state = self.state()
            self.assertEqual(state.evaluated_question_count, i + 1)
            self.assertEqual(state.correct_question_count, min(i + 1, 20))
            if i == 0:
                self.assertAlmostEqual(state.mastery, 0.05)
            if i == 18:
                self.assertAlmostEqual(state.mastery, 0.95)
                self.assertEqual(assessment_metrics(19, 19).assessment_stage, "collecting")
            if i == 19:
                self.assertEqual(state.mastery, 1.0)
                self.assertEqual(assessment_metrics(20, 20).assessment_stage, "sample_ready")
        self.assertAlmostEqual(self.state().mastery, 20 / 21)
        self.assertEqual(self.count(AssessmentEvidence), 21)
        self.assertEqual(self.count(GraphUpdateEvent), 21)
        last_event = self.database.scalar(select(GraphUpdateEvent).where(
            GraphUpdateEvent.round_id == learning_round.id,
        ))
        self.assertEqual((last_event.before_evaluated_count, last_event.after_evaluated_count),
                         (20, 21))
        self.assertEqual((last_event.before_correct_count, last_event.after_correct_count),
                         (20, 20))

    def test_partial_counts_in_denominator_but_not_numerator(self):
        for outcome in ["partial", "incorrect", "correct"]:
            learning_round, _, message = self.make_round()
            self.assertTrue(self.assess(learning_round, message, outcome).counted)
            self.database.commit()
        self.assertEqual(self.state().evaluated_question_count, 3)
        self.assertEqual(self.state().correct_question_count, 1)
        self.assertAlmostEqual(self.state().mastery, 0.05)

    def test_excluded_answers_keep_evidence_and_audit_without_changing_counts(self):
        cases = [
            ({"outcome": "unassessable"}, "unassessable"),
            ({"assistance": "hint"}, "assisted_answer"),
            ({"assistance": "answer_visible"}, "assisted_answer"),
            ({"question_valid": False}, "invalid_question"),
        ]
        for kwargs, reason in cases:
            learning_round, _, message = self.make_round()
            evidence = self.assess(learning_round, message, **kwargs)
            self.assertFalse(evidence.counted)
            self.assertEqual(evidence.exclusion_reason, reason)
            self.assertIsNone(evidence.counted_question_key)
            self.database.commit()
        learning_round, _, _ = self.make_round()
        evidence = self.assess(learning_round, None)
        self.database.commit()
        self.assertEqual(evidence.exclusion_reason, "no_answer")
        self.assertIsNone(self.state())
        self.assertEqual(self.count(AssessmentEvidence), 5)
        self.assertEqual(self.count(GraphUpdateEvent), 5)
        self.assertTrue(all(event.before_value == event.after_value == 0
                            for event in self.database.scalars(select(GraphUpdateEvent))))

    def test_retry_of_finalization_is_idempotent(self):
        learning_round, _, message = self.make_round()
        first = self.assess(learning_round, message)
        self.database.commit()
        again = self.assess(learning_round, message)
        self.database.commit()
        self.assertEqual(first.id, again.id)
        self.assertEqual(self.state().evaluated_question_count, 1)
        self.assertEqual(self.count(GraphUpdateEvent), 1)

    def test_revised_original_question_does_not_create_another_sample(self):
        bank, first_revision = self.bank_revision()
        _, next_revision = self.bank_revision(bank=bank, revision=2)
        for revision in [first_revision, next_revision]:
            learning_round, _, message = self.make_round(revision=revision)
            evidence = self.assess(learning_round, message)
            self.database.commit()
        self.assertFalse(evidence.counted)
        self.assertTrue(evidence.is_repeat)
        self.assertEqual(evidence.exclusion_reason, "repeat_question")
        self.assertEqual(self.state().evaluated_question_count, 1)
        self.assertEqual(evidence.bank_question_id, bank.id)

    def test_hint_exposure_cannot_become_fresh_sample_in_another_round(self):
        _, revision = self.bank_revision()
        learning_round, _, message = self.make_round(revision=revision)
        self.assess(learning_round, message, assistance="hint")
        self.database.commit()
        learning_round, _, message = self.make_round(revision=revision)
        repeated = self.assess(learning_round, message)
        self.database.commit()
        self.assertFalse(repeated.counted)
        self.assertTrue(repeated.is_repeat)
        self.assertIsNone(self.state())

    def test_new_target_on_revision_does_not_make_a_seen_original_independent(self):
        bank, revision = self.bank_revision()
        learning_round, _, message = self.make_round(revision=revision)
        self.assess(learning_round, message)
        self.database.commit()
        _, next_revision = self.bank_revision(bank=bank, revision=2)
        self.database.add(QuestionKnowledgeMapping(
            bank_question_revision_id=next_revision.id, knowledge_node_id=OTHER_NODE,
            role="assessed", is_primary=False,
        ))
        self.database.commit()
        learning_round, _, message = self.make_round(revision=next_revision, nodes=[OTHER_NODE])
        result = self.assess(learning_round, message, node=OTHER_NODE)
        self.database.commit()
        self.assertTrue(result.is_repeat)
        self.assertFalse(result.counted)
        self.assertIsNone(self.state(OTHER_NODE))

    def test_two_bank_targets_in_same_round_are_not_repeats_of_each_other(self):
        _, revision = self.bank_revision()
        self.database.add(QuestionKnowledgeMapping(
            bank_question_revision_id=revision.id, knowledge_node_id=OTHER_NODE,
            role="assessed", is_primary=False,
        ))
        self.database.commit()
        learning_round, _, message = self.make_round(revision=revision, nodes=[NODE, OTHER_NODE])
        first = self.assess(learning_round, message, node=NODE)
        second = self.assess(learning_round, message, node=OTHER_NODE)
        self.database.commit()
        self.assertTrue(first.counted)
        self.assertTrue(second.counted)
        self.assertFalse(second.is_repeat)

    def test_identical_non_bank_content_is_deduplicated_across_runtime_ids(self):
        for _ in range(2):
            learning_round, _, message = self.make_round(markdown="Same generated question")
            evidence = self.assess(learning_round, message)
            self.database.commit()
        self.assertTrue(evidence.is_repeat)
        self.assertEqual(self.state().evaluated_question_count, 1)

    def test_two_targets_receive_independent_final_judgements(self):
        learning_round, _, message = self.make_round(nodes=[NODE, OTHER_NODE])
        self.assess(learning_round, message, "correct", node=NODE)
        self.assess(learning_round, message, "incorrect", node=OTHER_NODE)
        self.database.commit()
        self.assertEqual(self.state(NODE).correct_question_count, 1)
        self.assertEqual(self.state(OTHER_NODE).correct_question_count, 0)
        self.assertEqual(self.state(OTHER_NODE).evaluated_question_count, 1)

    def test_transaction_rollback_removes_evidence_counts_and_audit(self):
        learning_round, _, message = self.make_round()
        self.assess(learning_round, message)
        self.database.rollback()
        self.assertIsNone(self.state())
        self.assertEqual(self.count(AssessmentEvidence), 0)
        self.assertEqual(self.count(GraphUpdateEvent), 0)

    def test_only_explicit_targets_in_finalized_round_may_be_assessed(self):
        learning_round, question, message = self.make_round()
        with self.assertRaises(AssessmentContextError):
            self.assess(learning_round, message, node=OTHER_NODE)
        learning_round.state = "QUESTION_ACTIVE"
        self.database.commit()
        with self.assertRaises(AssessmentContextError):
            self.assess(learning_round, message)
        learning_round.finalized_at = datetime.utcnow()
        self.database.commit()
        self.assertTrue(self.assess(learning_round, message).counted)

    def test_bank_prerequisite_does_not_receive_a_score(self):
        _, revision = self.bank_revision(mapping_role="prerequisite")
        learning_round, _, message = self.make_round(revision=revision)
        with self.assertRaises(AssessmentContextError):
            self.assess(learning_round, message)

    def test_unreviewed_bank_question_cannot_update_mastery(self):
        _, revision = self.bank_revision()
        revision.review_status = "draft"
        self.database.commit()
        learning_round, _, message = self.make_round(revision=revision)
        evidence = self.assess(learning_round, message)
        self.database.commit()
        self.assertFalse(evidence.counted)
        self.assertEqual(evidence.exclusion_reason, "unreviewed_question")
        self.assertIsNone(self.state())

    def test_basis_must_belong_to_the_same_round(self):
        first_round, _, first_message = self.make_round()
        second_round, _, second_message = self.make_round()
        with self.assertRaises(AssessmentContextError):
            self.assess(second_round, first_message)
        first_message.role = "critic"
        self.database.commit()
        with self.assertRaises(AssessmentContextError):
            self.assess(first_round, first_message)
        self.assertTrue(self.assess(second_round, second_message).counted)

    def test_legacy_positive_evidence_cannot_be_used_as_a_correct_question(self):
        learning_round, _, _ = self.make_round()
        with self.assertRaises(ValueError):
            GraphService(self.database).commit_knowledge_update(
                "student", learning_round.id,
                KnowledgeGraphUpdate(node_id=NODE, evidence="positive", strength=1,
                                     reason="Not an explicit assessment"),
            )
        self.assertEqual(self.count(AssessmentEvidence), 0)


if __name__ == "__main__":
    unittest.main()
