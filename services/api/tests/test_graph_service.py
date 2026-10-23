import unittest

from app.schemas.assessment import assessment_metrics
from app.services.graph_service import apply_error_update


class GraphUpdateTests(unittest.TestCase):
    def test_metrics_separate_accuracy_from_sample_progress(self) -> None:
        all_correct = assessment_metrics(8, 8)
        half_correct = assessment_metrics(16, 8)
        self.assertEqual(all_correct.assessment_score, 0.4)
        self.assertEqual(half_correct.assessment_score, 0.4)
        self.assertEqual(all_correct.accuracy, 1.0)
        self.assertEqual(half_correct.accuracy, 0.5)

    def test_unknown_and_invalid_counts(self) -> None:
        unknown = assessment_metrics(0, 0)
        self.assertIsNone(unknown.accuracy)
        self.assertEqual(unknown.assessment_stage, "unassessed")
        for counts in [(-1, 0), (0, 1), (2, -1)]:
            with self.assertRaises(ValueError):
                assessment_metrics(*counts)

    def test_error_update(self) -> None:
        self.assertAlmostEqual(apply_error_update(0.2, "activate", 1.0), 0.32)
        self.assertAlmostEqual(apply_error_update(0.2, "resolve", 1.0), 0.1)


if __name__ == "__main__":
    unittest.main()

