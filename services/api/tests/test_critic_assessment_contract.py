import asyncio
import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.llm.mock import MockLLMProvider
from app.schemas.critic import DiscussionSummary, DiscussionSummaryContext, QuestionReview
from app.schemas.question import QuestionPacket
from app.services.critic_service import CriticConversationService
from tests.test_schemas import valid_question


def summary_payload(packet, assessments):
    return {
        "question_id": str(packet.question_id),
        "original_verdict": "correct", "final_verdict": "correct",
        "diagnosis_changed": False, "discussion_resolved": True,
        "confirmed_knowledge": [], "remaining_knowledge_gaps": [],
        "active_errors": [], "resolved_errors": [],
        "final_knowledge_updates": [], "final_error_updates": [],
        "next_question_guidance": {}, "knowledge_assessments": assessments,
    }


class CriticAssessmentContractTests(unittest.TestCase):
    def setUp(self):
        self.packet = QuestionPacket.model_validate(valid_question())
        self.assessment = {
            "node_id": "python.iterator.next", "outcome": "correct",
            "reason": "The first independent answer identifies next() correctly.",
        }

    def context(self):
        message_id = uuid4()
        return DiscussionSummaryContext(
            question_packet=self.packet,
            question_review=QuestionReview(status="approved", quality_score=1, issues=[]),
            conversation_history=[{
                "message_id": message_id, "role": "student",
                "content_markdown": "next(iterator)",
            }],
            turn_results=[], assessment_basis_message_id=message_id,
        )

    def test_duplicate_node_assessments_are_rejected(self):
        with self.assertRaises(ValidationError):
            DiscussionSummary.model_validate(summary_payload(
                self.packet, [self.assessment, self.assessment],
            ))

    def test_uncertain_result_cannot_claim_a_correct_assessment(self):
        payload = summary_payload(self.packet, [self.assessment])
        payload.update(original_verdict="critic_uncertain", final_verdict="critic_uncertain")
        with self.assertRaises(ValidationError):
            DiscussionSummary.model_validate(payload)

    def test_unknown_knowledge_node_is_retried_before_acceptance(self):
        bad = summary_payload(self.packet, [{**self.assessment, "node_id": "python.iterable"}])
        good = summary_payload(self.packet, [self.assessment])
        provider = MockLLMProvider([bad, good])
        result = asyncio.run(CriticConversationService(provider).summarize_discussion(self.context()))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.summary.knowledge_assessments[0].node_id, "python.iterator.next")

    def test_missing_explicit_assessment_is_not_inferred_from_positive_evidence(self):
        bad = summary_payload(self.packet, [])
        bad["final_knowledge_updates"] = [{
            "node_id": "python.iterator.next", "evidence": "positive", "strength": 1,
            "reason": "A positive update is not an explicit question result.",
        }]
        provider = MockLLMProvider([bad, bad])
        result = asyncio.run(CriticConversationService(provider).summarize_discussion(self.context()))
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(provider.calls), 2)


if __name__ == "__main__":
    unittest.main()
