import asyncio
import json
import unittest
from typing import Dict, List, Sequence, Type
from unittest.mock import patch

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableSequence
from pydantic import ValidationError

from app.agents.critic import Critic, STREAMING_VISIBLE_REPLY_CONTRACT
from app.agents.questioner import Questioner
from app.llm.base import SchemaT, TextDeltaCallback, schema_output_contract
from app.llm.mock import MockLLMProvider
from app.schemas.critic import CriticTurnResult, QuestionReview
from app.schemas.question import QuestionPacket, QuestionerContext
from tests.test_critic_streaming_contract import valid_critic_turn_result
from tests.test_schemas import valid_question


def questioner_context(marker: str = "{context}") -> QuestionerContext:
    return QuestionerContext(
        global_knowledge_graph={"marker": marker, "example": {"a": "{literal}"}},
        personal_knowledge_graph=[],
        error_graph=[],
        recent_questions=[],
        recent_attempts=[],
        critic_summary={},
        teaching_policy={},
        candidate_constraints={},
    )


def review_payload(notes: str = "Accept equivalent answers.") -> dict:
    return {
        "status": "approved",
        "quality_score": 0.95,
        "issues": [],
        "grading_notes": notes,
    }


class UncheckedMockLLMProvider(MockLLMProvider):
    """Simulate a provider returning a model that was mutated after validation."""

    def __init__(self, result) -> None:
        super().__init__([])
        self.result = result

    async def generate_structured(self, messages, schema):
        self.calls.append(messages)
        return self.result


class ConcurrentMockLLMProvider(MockLLMProvider):
    def __init__(self, expected_calls: int) -> None:
        super().__init__([])
        self.expected_calls = expected_calls
        self.all_started = asyncio.Event()

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        self.calls.append(messages)
        context = json.loads(messages[1]["content"])
        if len(self.calls) == self.expected_calls:
            self.all_started.set()
        await self.all_started.wait()
        if schema is QuestionPacket:
            payload = valid_question()
            payload["student_content"]["markdown"] = context["global_knowledge_graph"]["marker"]
        else:
            payload = review_payload(context["marker"])
        return schema.model_validate(payload)


class StreamingMockLLMProvider(MockLLMProvider):
    visible_path: Sequence[str] = ()

    async def generate_structured_stream(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
        visible_path: Sequence[str],
        on_delta: TextDeltaCallback,
    ) -> SchemaT:
        self.visible_path = visible_path
        return await super().generate_structured_stream(messages, schema, visible_path, on_delta)


class LangChainAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_agents_invoke_real_prompt_and_lcel_sequence(self) -> None:
        provider = MockLLMProvider([valid_question(), review_payload()])
        invoked_chains = []
        original_ainvoke = RunnableSequence.ainvoke

        async def capture_ainvoke(chain, *args, **kwargs):
            invoked_chains.append(chain)
            return await original_ainvoke(chain, *args, **kwargs)

        with patch.object(RunnableSequence, "ainvoke", new=capture_ainvoke):
            question = await Questioner(provider, "Questioner").generate(questioner_context())
            review = await Critic(provider).run("Critic", "{}", QuestionReview)

        self.assertIsInstance(question, QuestionPacket)
        self.assertIsInstance(review, QuestionReview)
        self.assertEqual(len(invoked_chains), 2)
        for chain in invoked_chains:
            self.assertIsInstance(chain.steps[0], ChatPromptTemplate)
            self.assertEqual(len(chain.steps), 3)

    async def test_questioner_preserves_literal_braces_and_repair_message_order(self) -> None:
        provider = MockLLMProvider([valid_question()])
        system_prompt = '规则：保留 {system} 与 {"schema": {"type": "object"}}。'
        context = questioner_context()
        feedback = 'student_content 缺少字段 {"markdown": "..."}'

        await Questioner(provider, system_prompt).generate(context, feedback)

        self.assertEqual(
            provider.calls[0],
            [
                {"role": "system", "content": system_prompt + schema_output_contract(QuestionPacket)},
                {"role": "user", "content": context.model_dump_json(indent=2)},
                {
                    "role": "user",
                    "content": "上一次输出无效。只修正下列问题并重新输出完整的 "
                    f"QuestionPacket JSON：\n{feedback}",
                },
            ],
        )

    async def test_critic_preserves_literal_braces_and_repair_message_order(self) -> None:
        provider = MockLLMProvider([review_payload()])
        system_prompt = '审题：{"example": "{literal}"}'
        context_json = '{"student_message": "f\'{value}\'", "nested": {"a": 1}}'
        feedback = 'issues 必须为列表，收到 {"unexpected": true}'

        await Critic(provider).run(system_prompt, context_json, QuestionReview, feedback)

        self.assertEqual(
            provider.calls[0],
            [
                {"role": "system", "content": system_prompt + schema_output_contract(QuestionReview)},
                {"role": "user", "content": context_json},
                {
                    "role": "user",
                    "content": "上一次输出未通过 Schema 校验。只修正下列问题并重新输出"
                    f"完整 JSON：\n{feedback}",
                },
            ],
        )

    async def test_concurrent_calls_keep_each_context_prompt_and_feedback(self) -> None:
        provider = ConcurrentMockLLMProvider(expected_calls=4)
        questioner = Questioner(provider, "Questioner {literal}")
        critic = Critic(provider)

        results = await asyncio.wait_for(
            asyncio.gather(
                questioner.generate(questioner_context("question {one}"), "repair {one}"),
                questioner.generate(questioner_context("question {two}"), "repair {two}"),
                critic.run("Critic {one}", '{"marker": "review {one}"}', QuestionReview),
                critic.run("Critic {two}", '{"marker": "review {two}"}', QuestionReview),
            ),
            timeout=5,
        )

        self.assertEqual(results[0].student_content.markdown, "question {one}")
        self.assertEqual(results[1].student_content.markdown, "question {two}")
        self.assertEqual(results[2].grading_notes, "review {one}")
        self.assertEqual(results[3].grading_notes, "review {two}")
        for messages in provider.calls:
            context = json.loads(messages[1]["content"])
            if "global_knowledge_graph" in context:
                marker = context["global_knowledge_graph"]["marker"].split()[-1]
                self.assertTrue(messages[2]["content"].endswith(f"repair {marker}"))
            else:
                marker = context["marker"].split()[-1]
                self.assertTrue(messages[0]["content"].startswith(f"Critic {marker}"))

    async def test_both_agent_boundaries_revalidate_provider_models(self) -> None:
        question = QuestionPacket.model_validate(valid_question())
        question.difficulty = 10
        questioner = Questioner(UncheckedMockLLMProvider(question), "Questioner")
        with self.assertRaises(ValidationError):
            await questioner.generate(questioner_context())

        review = QuestionReview.model_validate(review_payload())
        review.quality_score = 2
        critic = Critic(UncheckedMockLLMProvider(review))
        with self.assertRaises(ValidationError):
            await critic.run("Critic", "{}", QuestionReview)

    async def test_critic_streams_only_student_visible_reply_field(self) -> None:
        payload = valid_critic_turn_result()
        payload["student_visible_reply_markdown"] = "可见回复：`{answer}`。"
        payload["provisional_knowledge_updates"] = [
            {
                "node_id": "python.iterator.next",
                "evidence": "positive",
                "strength": 0.9,
                "reason": "INTERNAL_GRAPH_REASON",
            }
        ]
        provider = StreamingMockLLMProvider([payload])
        deltas = []

        async def on_delta(delta: str) -> None:
            deltas.append(delta)

        result = await Critic(provider).run(
            "Critic {literal}",
            '{"answer": "{literal}"}',
            CriticTurnResult,
            on_delta=on_delta,
        )

        self.assertEqual(provider.visible_path, ("student_visible_reply_markdown",))
        self.assertEqual("".join(deltas), payload["student_visible_reply_markdown"])
        self.assertNotIn("INTERNAL_GRAPH_REASON", "".join(deltas))
        self.assertEqual(result.provisional_knowledge_updates[0].reason, "INTERNAL_GRAPH_REASON")
        self.assertEqual(
            provider.calls[0][0]["content"],
            "Critic {literal}"
            + STREAMING_VISIBLE_REPLY_CONTRACT
            + schema_output_contract(CriticTurnResult),
        )
