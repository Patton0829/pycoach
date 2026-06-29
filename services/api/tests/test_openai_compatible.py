import unittest

from app.llm.openai_compatible import (
    OpenAICompatibleLLMProvider,
    extract_partial_json_string_field,
)


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_extracts_incremental_student_visible_json_string(self) -> None:
        partial = (
            '{"intent":"answer_attempt",'
            '"student_visible_reply_markdown":"回答正\\n确，继续'
        )

        self.assertEqual(
            extract_partial_json_string_field(
                partial,
                "student_visible_reply_markdown",
            ),
            "回答正\n确，继续",
        )

    def test_ignores_incomplete_json_escape_at_chunk_boundary(self) -> None:
        partial = '{"markdown":"第一行\\n第二行\\u4e'

        self.assertEqual(
            extract_partial_json_string_field(partial, "markdown"),
            "第一行\n第二行",
        )

    def test_parses_provider_specific_extra_body(self) -> None:
        provider = OpenAICompatibleLLMProvider(
            "https://example.com/v1",
            "test-key",
            "test-model",
            extra_body='{"enable_thinking": false}',
        )

        self.assertEqual(provider.extra_body, {"enable_thinking": False})

    def test_rejects_reserved_extra_body_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot override"):
            OpenAICompatibleLLMProvider(
                "https://example.com/v1",
                "test-key",
                "test-model",
                extra_body='{"model": "other-model"}',
            )

    def test_rejects_non_positive_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            OpenAICompatibleLLMProvider(
                "https://example.com/v1",
                "test-key",
                "test-model",
                timeout_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
