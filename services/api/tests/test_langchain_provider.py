"""Exercise the real LangChain adapter against an in-memory HTTP transport."""

import json
import unittest

import httpx
from pydantic import ValidationError

from app.llm.base import LLMProviderError
from app.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.schemas.critic import CriticTurnResult, QuestionReview
from tests.test_critic_streaming_contract import valid_critic_turn_result


MESSAGES = [{"role": "system", "content": "Return a JSON object."}]
REVIEW = {"status": "approved", "quality_score": 0.9, "issues": []}


def completion(content: str) -> dict:
    return {
        "id": "test-completion",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }


def streamed_completion(content: str, finish_reason: str = "stop") -> str:
    # Small fragments intentionally split JSON keys, escapes and Unicode.
    events = []
    for index in range(0, len(content), 5):
        event = {
            "id": "test-stream",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test-model",
            "choices": [{
                "index": 0,
                "delta": {
                    "content": content[index:index + 5],
                    **({"role": "assistant"} if index == 0 else {}),
                },
                "finish_reason": None,
            }],
        }
        events.append("data: " + json.dumps(event) + "\n\n")
    final = {
        "id": "test-stream", "object": "chat.completion.chunk", "created": 0,
        "model": "test-model",
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
    }
    events.append("data: " + json.dumps(final) + "\n\n")
    events.append("data: [DONE]\n\n")
    return "".join(events)


class LangChainProviderTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, client: httpx.AsyncClient) -> OpenAICompatibleLLMProvider:
        return OpenAICompatibleLLMProvider(
            "https://model.invalid/v1", "test-key", "test-model",
            extra_body='{"enable_thinking": false}',
            http_async_client=client,
        )

    async def test_structured_chat_uses_json_mode_and_provider_configuration(self) -> None:
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=completion(json.dumps(REVIEW)))

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = self.provider(client)
            result = await provider.generate_structured(MESSAGES, QuestionReview)

        self.assertEqual(result.status, "approved")
        self.assertEqual(str(requests[0].url), "https://model.invalid/v1/chat/completions")
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["messages"], MESSAGES)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["enable_thinking"])
        self.assertEqual(provider.chat_model.max_retries, 0)

    async def test_pydantic_rejects_invalid_structured_output(self) -> None:
        def respond(_request):
            invalid = {**REVIEW, "quality_score": 9}
            return httpx.Response(200, json=completion(json.dumps(invalid)))

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(ValidationError):
                await self.provider(client).generate_structured(MESSAGES, QuestionReview)

    async def test_incomplete_json_is_not_silently_repaired_by_langchain(self) -> None:
        def respond(_request):
            return httpx.Response(200, json=completion(json.dumps(REVIEW)[:-1]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(json.JSONDecodeError):
                await self.provider(client).generate_structured(MESSAGES, QuestionReview)

    async def test_http_error_has_no_hidden_sdk_retry(self) -> None:
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(429, json={"error": {"message": "rate limited"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(LLMProviderError, "HTTP 429"):
                await self.provider(client).generate_structured(MESSAGES, QuestionReview)
        self.assertEqual(len(calls), 1)

    async def test_malformed_response_is_a_recoverable_provider_error(self) -> None:
        def respond(_request):
            return httpx.Response(200, json={**completion(""), "choices": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(LLMProviderError, "unexpected response shape"):
                await self.provider(client).generate_structured(MESSAGES, QuestionReview)

    async def test_timeout_remains_a_recoverable_provider_error(self) -> None:
        def respond(request):
            raise httpx.ReadTimeout("test timeout", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(LLMProviderError, "timed out after 75"):
                await self.provider(client).generate_structured(MESSAGES, QuestionReview)

    async def test_stream_exposes_only_visible_markdown_and_validates_final_json(self) -> None:
        payload = valid_critic_turn_result()
        payload["student_visible_reply_markdown"] = "第一行\n你好，`next(it)`。"
        payload["provisional_knowledge_updates"] = [{
            "node_id": "python.iterator.next", "evidence": "positive", "strength": 0.9,
            "reason": "INTERNAL_EVIDENCE_DO_NOT_DISPLAY",
        }]
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"},
                text=streamed_completion(json.dumps(payload)),
            )

        deltas = []

        async def on_delta(value):
            deltas.append(value)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await self.provider(client).generate_structured_stream(
                MESSAGES, CriticTurnResult, ("student_visible_reply_markdown",), on_delta,
            )

        self.assertEqual("".join(deltas), payload["student_visible_reply_markdown"])
        self.assertGreater(len(deltas), 1)
        self.assertNotIn("INTERNAL_EVIDENCE", "".join(deltas))
        self.assertEqual(result.verdict, "correct")
        self.assertTrue(requests[0]["stream"])
        self.assertNotIn("stream_options", requests[0])

    async def test_truncated_stream_is_rejected_after_visible_preview(self) -> None:
        payload = valid_critic_turn_result()

        def respond(_request):
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"},
                text=streamed_completion(json.dumps(payload)[:-1]),
            )

        deltas = []

        async def on_delta(value):
            deltas.append(value)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(LLMProviderError, "invalid streamed JSON"):
                await self.provider(client).generate_structured_stream(
                    MESSAGES, CriticTurnResult, ("student_visible_reply_markdown",), on_delta,
                )
        self.assertEqual("".join(deltas), payload["student_visible_reply_markdown"])

    async def test_sdk_length_failure_is_recoverable_for_graph_retry(self) -> None:
        def respond(_request):
            return httpx.Response(
                200, headers={"Content-Type": "text/event-stream"},
                text=streamed_completion(json.dumps(valid_critic_turn_result()), "length"),
            )

        async def on_delta(_value):
            pass

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(LLMProviderError, "truncated"):
                await self.provider(client).generate_structured_stream(
                    MESSAGES, CriticTurnResult, ("student_visible_reply_markdown",), on_delta,
                )


if __name__ == "__main__":
    unittest.main()
