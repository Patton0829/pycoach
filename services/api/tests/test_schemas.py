import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.schemas.question import QuestionPacket


def valid_question() -> dict:
    return {
        "question_id": str(uuid4()),
        "question_type": "code_blank",
        "difficulty": 2,
        "knowledge_node_ids": ["python.iterator.next"],
        "target_error_ids": ["iter_vs_next"],
        "pedagogical_strategy": "retrieval_practice",
        "student_content": {"markdown": "填写：`first = ____`"},
        "critic_content": {
            "learning_objective": "Use next on an iterator.",
            "reference_answer": "next(iterator)",
            "acceptable_answers": ["next(iterator)"],
            "grading_rubric": {"correct": "Uses next(iterator)."},
            "expected_reasoning": "next returns and advances one element.",
        },
    }


class QuestionPacketTests(unittest.TestCase):
    def test_valid_question_packet(self) -> None:
        packet = QuestionPacket.model_validate(valid_question())
        self.assertEqual(packet.question_type, "code_blank")

    def test_rejects_unknown_fields(self) -> None:
        payload = valid_question()
        payload["internal_leak"] = True
        with self.assertRaises(ValidationError):
            QuestionPacket.model_validate(payload)

    def test_rejects_more_than_two_knowledge_nodes(self) -> None:
        payload = valid_question()
        payload["knowledge_node_ids"] = ["a", "b", "c"]
        with self.assertRaises(ValidationError):
            QuestionPacket.model_validate(payload)


if __name__ == "__main__":
    unittest.main()

