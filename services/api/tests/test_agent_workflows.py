import asyncio
from contextvars import ContextVar
import unittest

from pydantic import ValidationError

from app.agents.workflow import StructuredAgentWorkflow
from app.llm.mock import MockLLMProvider
from app.schemas.critic import QuestionReview
from app.services.critic_service import CriticConversationService
from tests.test_critic_conversation import turn_context, turn_result


def review_payload(quality=0.9):
    return {"status": "approved", "quality_score": quality, "issues": []}


class StreamingMockLLMProvider(MockLLMProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.visible_paths = []

    async def generate_structured_stream(self, messages, schema, visible_path, on_delta):
        self.visible_paths.append(tuple(visible_path))
        await on_delta(f"preview {len(self.calls) + 1}")
        return await self.generate_structured(messages, schema)


class BlockingMockLLMProvider(MockLLMProvider):
    def __init__(self):
        super().__init__([review_payload()])
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_structured(self, messages, schema):
        self.started.set()
        await self.release.wait()
        return await super().generate_structured(messages, schema)


class AgentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_langgraph_routes_business_rejection_through_repair(self):
        provider = MockLLMProvider([review_payload(0.2), review_payload()])
        feedbacks = []
        rejections = []

        async def invoke(feedback):
            feedbacks.append(feedback)
            return await provider.generate_structured([], QuestionReview)

        def validate(review):
            if review.quality_score < 0.5:
                raise ValueError("Review quality is insufficient")

        async def rejected(error, attempt):
            rejections.append((error, attempt))

        workflow = StructuredAgentWorkflow(
            role="critic", schema=QuestionReview, invoke=invoke,
            retry_exceptions=(ValueError,), validate=validate, on_rejected=rejected,
        )
        updates = [update async for update in workflow.graph.astream(
            workflow.initial_state(), stream_mode="updates",
        )]

        self.assertEqual(
            [next(iter(update)) for update in updates],
            ["critic", "validate", "rejected", "repair", "critic", "validate", "complete"],
        )
        self.assertEqual(feedbacks, [None, "Review quality is insufficient"])
        self.assertEqual(rejections, [("Review quality is insufficient", 1)])
        self.assertEqual(updates[-1]["complete"]["result"].quality_score, 0.9)
        self.assertEqual(len(provider.calls), 2)

    async def test_two_schema_failures_take_fallback_without_a_third_model_call(self):
        provider = MockLLMProvider([{"bad": 1}, {"bad": 2}])
        fallback_calls = []

        async def invoke(feedback):
            return await provider.generate_structured([], QuestionReview)

        def fallback():
            fallback_calls.append(True)
            return QuestionReview(
                status="needs_revision", quality_score=0, issues=["Review unavailable"],
            )

        result = await StructuredAgentWorkflow(
            role="critic", schema=QuestionReview, invoke=invoke,
            retry_exceptions=(ValidationError,), fallback=fallback,
        ).run()

        self.assertTrue(result.used_fallback)
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.value.status, "needs_revision")
        self.assertIn("validation errors", result.error)
        self.assertEqual(fallback_calls, [True])
        self.assertEqual(len(provider.calls), 2)

    async def test_concurrent_invocations_of_one_graph_have_independent_retry_state(self):
        request_id = ContextVar("workflow_request_id")
        providers = {
            "repair": MockLLMProvider([{"bad": 1}, review_payload(0.8)]),
            "valid": MockLLMProvider([review_payload(0.95)]),
        }
        feedbacks = {"repair": [], "valid": []}

        async def invoke(feedback):
            name = request_id.get()
            feedbacks[name].append(feedback)
            await asyncio.sleep(0)
            return await providers[name].generate_structured([], QuestionReview)

        workflow = StructuredAgentWorkflow(
            role="critic", schema=QuestionReview, invoke=invoke,
            retry_exceptions=(ValidationError,),
        )

        async def run(name):
            token = request_id.set(name)
            try:
                return await workflow.run()
            finally:
                request_id.reset(token)

        repaired, valid = await asyncio.gather(run("repair"), run("valid"))
        self.assertEqual((repaired.retry_count, valid.retry_count), (1, 0))
        self.assertEqual((repaired.value.quality_score, valid.value.quality_score), (0.8, 0.95))
        self.assertIsNotNone(feedbacks["repair"][1])
        self.assertEqual(feedbacks["valid"], [None])
        self.assertEqual((len(providers["repair"].calls), len(providers["valid"].calls)), (2, 1))

    async def test_task_cancellation_propagates_without_retry_or_fallback(self):
        provider = BlockingMockLLMProvider()
        fallback_calls = []

        async def invoke(feedback):
            return await provider.generate_structured([], QuestionReview)

        def fallback():
            fallback_calls.append(True)
            return QuestionReview.model_validate(review_payload())

        workflow = StructuredAgentWorkflow(
            role="critic", schema=QuestionReview, invoke=invoke,
            retry_exceptions=(ValueError,), fallback=fallback,
        )
        task = asyncio.create_task(workflow.run())
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(fallback_calls, [])
        self.assertEqual(provider.calls, [])

    async def test_unexpected_provider_error_is_not_hidden_by_fallback(self):
        # An empty Mock queue is a programming/configuration error, not a
        # schema/provider failure that should silently trigger a safe reply.
        provider = MockLLMProvider([])

        async def invoke(feedback):
            return await provider.generate_structured([], QuestionReview)

        workflow = StructuredAgentWorkflow(
            role="critic", schema=QuestionReview, invoke=invoke,
            retry_exceptions=(ValidationError,),
        )
        with self.assertRaisesRegex(RuntimeError, "no queued response"):
            await workflow.run()
        self.assertEqual(len(provider.calls), 1)

    async def test_stream_preview_is_reset_before_business_validation_retry(self):
        invalid = turn_result("answer_attempt", "QUESTION_ACTIVE")
        invalid["round_action"] = "continue_discussion"
        provider = StreamingMockLLMProvider([
            invalid, turn_result("answer_attempt", "QUESTION_ACTIVE"),
        ])
        events = []

        async def delta(text):
            events.append(("delta", text))

        async def reset():
            events.append(("reset", None))

        execution = await CriticConversationService(provider).process_turn(
            turn_context("next(iterator)"), on_delta=delta, on_reset=reset,
        )
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.retry_count, 1)
        self.assertEqual(events, [("delta", "preview 1"), ("reset", None), ("delta", "preview 2")])
        self.assertEqual(provider.visible_paths, [
            ("student_visible_reply_markdown",), ("student_visible_reply_markdown",),
        ])


if __name__ == "__main__":
    unittest.main()
