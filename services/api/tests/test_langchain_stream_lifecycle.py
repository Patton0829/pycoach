"""Verify early stream exits close the in-memory HTTP response immediately."""

import asyncio
import json
import unittest

import httpx

from app.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.schemas.critic import CriticTurnResult
from tests.test_critic_streaming_contract import valid_critic_turn_result
from tests.test_langchain_provider import MESSAGES, streamed_completion


class TrackingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0
        payload = json.dumps(valid_critic_turn_result())
        self.events = streamed_completion(payload).split("\n\n")

    async def __aiter__(self):
        for event in self.events:
            if event:
                yield (event + "\n\n").encode("utf-8")
                await asyncio.sleep(0)

    async def aclose(self) -> None:
        self.closed = True
        self.close_calls += 1


class LangChainStreamLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def transport(self, stream, requests):
        def respond(request):
            requests.append(request)
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=stream,
            )

        return httpx.MockTransport(respond)

    def provider(self, client):
        return OpenAICompatibleLLMProvider(
            "https://model.invalid/v1", "test-key", "test-model",
            http_async_client=client,
        )

    async def test_callback_failure_closes_transport_and_preserves_exception(self):
        stream = TrackingStream()
        requests = []
        failure = ValueError("application callback failed")

        async def on_delta(_value):
            raise failure

        async with httpx.AsyncClient(transport=self.transport(stream, requests)) as client:
            with self.assertRaises(ValueError) as raised:
                await self.provider(client).generate_structured_stream(
                    MESSAGES, CriticTurnResult, ("student_visible_reply_markdown",), on_delta,
                )

            # Check before closing the client or yielding another loop tick;
            # background generator finalization must not own HTTP cleanup.
            self.assertIs(raised.exception, failure)
            self.assertTrue(stream.closed)
            self.assertEqual(stream.close_calls, 1)
            self.assertEqual(len(requests), 1)

    async def test_cancellation_in_callback_closes_transport_without_retry(self):
        stream = TrackingStream()
        requests = []
        callback_started = asyncio.Event()
        never_release = asyncio.Event()

        async def on_delta(_value):
            callback_started.set()
            await never_release.wait()

        async with httpx.AsyncClient(transport=self.transport(stream, requests)) as client:
            task = asyncio.create_task(self.provider(client).generate_structured_stream(
                MESSAGES, CriticTurnResult, ("student_visible_reply_markdown",), on_delta,
            ))
            try:
                await asyncio.wait_for(callback_started.wait(), timeout=1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(stream.closed)
                self.assertEqual(stream.close_calls, 1)
                self.assertEqual(len(requests), 1)
            finally:
                if not task.done():
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task


if __name__ == "__main__":
    unittest.main()
