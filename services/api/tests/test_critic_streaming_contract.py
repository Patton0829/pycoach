import asyncio
import unittest
from typing import Dict, List, Sequence, Type

from app.agents.critic import Critic
from app.llm.base import LLMProvider, SchemaT, TextDeltaCallback
from app.schemas.critic import CriticTurnResult


def valid_critic_turn_result() -> dict:
    return {
        "student_visible_reply_markdown": "回答正确。",
        "intent": "answer_attempt",
        "intent_confidence": 0.95,
        "verdict": "correct",
        "round_action": "show_feedback",
        "provisional_knowledge_updates": [],
        "provisional_error_updates": [],
        "should_prepare_next_question": True,
        "should_invalidate_candidate_question": False,
    }


class CapturingStreamingProvider(LLMProvider):
    def __init__(self) -> None:
        self.messages: List[Dict[str, str]] = []
        self.visible_path: Sequence[str] = ()

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        raise AssertionError("streaming test should call generate_structured_stream")

    async def generate_structured_stream(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
        visible_path: Sequence[str],
        on_delta: TextDeltaCallback,
    ) -> SchemaT:
        self.messages = messages
        self.visible_path = visible_path
        await on_delta("回答正确。")
        return schema.model_validate(valid_critic_turn_result())


class CriticStreamingContractTests(unittest.TestCase):
    def test_visible_reply_is_first_schema_property(self) -> None:
        properties = CriticTurnResult.model_json_schema()["properties"]

        self.assertEqual(
            next(iter(properties)),
            "student_visible_reply_markdown",
        )

    def test_streaming_prompt_requires_visible_reply_first(self) -> None:
        provider = CapturingStreamingProvider()

        async def run_critic() -> None:
            critic = Critic(provider)

            await critic.run(
                "你是 Critic。",
                "{}",
                CriticTurnResult,
                on_delta=lambda _delta: asyncio.sleep(0),
            )

        asyncio.run(run_critic())

        self.assertEqual(provider.visible_path, ("student_visible_reply_markdown",))
        self.assertIn(
            '"student_visible_reply_markdown" 作为第一个字段输出',
            provider.messages[0]["content"],
        )


if __name__ == "__main__":
    unittest.main()
