import unittest

from app.services.graph_service import apply_error_update, apply_mastery_update


class GraphUpdateTests(unittest.TestCase):
    def test_mastery_positive_and_bounds(self) -> None:
        self.assertAlmostEqual(apply_mastery_update(0.5, "positive", 1.0), 0.62)
        self.assertEqual(apply_mastery_update(0.99, "positive", 1.0), 1.0)

    def test_mastery_negative_and_bounds(self) -> None:
        self.assertAlmostEqual(apply_mastery_update(0.5, "negative", 0.5), 0.45)
        self.assertEqual(apply_mastery_update(0.01, "negative", 1.0), 0.0)

    def test_error_update(self) -> None:
        self.assertAlmostEqual(apply_error_update(0.2, "activate", 1.0), 0.32)
        self.assertAlmostEqual(apply_error_update(0.2, "resolve", 1.0), 0.1)


if __name__ == "__main__":
    unittest.main()

