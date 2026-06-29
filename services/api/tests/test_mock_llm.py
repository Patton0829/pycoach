import asyncio
import unittest

from app.llm.mock import MockLLMProvider
from app.schemas.critic import QuestionReview


class MockLLMTests(unittest.TestCase):
    def test_validates_queued_response(self) -> None:
        provider = MockLLMProvider(
            [
                {
                    "status": "approved",
                    "quality_score": 0.9,
                    "issues": [],
                    "grading_notes": None,
                }
            ]
        )
        result = asyncio.run(provider.generate_structured([], QuestionReview))
        self.assertEqual(result.status, "approved")


if __name__ == "__main__":
    unittest.main()

