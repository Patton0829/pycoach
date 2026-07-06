import asyncio
import json
import unittest
from typing import Dict, List, Type
from uuid import uuid4

from app.llm.base import LLMProvider, LLMProviderError, SchemaT
from app.llm.mock import MockLLMProvider
from app.schemas.critic import (
    CriticTurnContext,
    DiscussionSummaryContext,
    QuestionReview,
)
from app.schemas.question import QuestionPacket
from app.services.critic_service import (
    SAFE_CRITIC_FAILURE_REPLY,
    CriticConversationService,
)
from tests.test_schemas import valid_question


def approved_review() -> QuestionReview:
    return QuestionReview(
        status="approved",
        quality_score=0.95,
        issues=[],
        grading_notes="Accept semantically equivalent explanations.",
    )


def turn_context(
    message: str,
    state: str = "QUESTION_ACTIVE",
    review: QuestionReview | None = None,
) -> CriticTurnContext:
    return CriticTurnContext(
        session_state=state,
        question_packet=QuestionPacket.model_validate(valid_question()),
        question_review=review or approved_review(),
        conversation_history=[
            {
                "role": "questioner",
                "content_markdown": "填写：`first = ____`",
            }
        ],
        student_message=message,
        candidate_question_status=(
            "provisional" if state == "FEEDBACK_DISCUSSION" else None
        ),
    )


def turn_result(
    intent: str,
    state: str,
    *,
    verdict: str | None = None,
    reply: str | None = None,
    diagnosis_changed: bool = False,
) -> dict:
    if intent in {"answer_attempt", "answer_and_question"}:
        selected_verdict = verdict or "correct"
        round_action = "show_feedback" if state == "QUESTION_ACTIVE" else "continue_discussion"
        knowledge_updates = [
            {
                "node_id": "python.iterator.next",
                "evidence": "positive",
                "strength": 0.9,
                "reason": "Student used next(iterator) correctly.",
            }
        ]
        error_updates = [
            {
                "error_id": "iter_vs_next",
                "action": "weaken",
                "strength": 0.8,
                "reason": "Student distinguished next() from iter().",
            }
        ]
    elif intent == "student_uncertain":
        selected_verdict = "student_uncertain"
        round_action = "show_feedback" if state == "QUESTION_ACTIVE" else "continue_discussion"
        knowledge_updates = []
        error_updates = []
    elif intent == "clarification_question":
        selected_verdict = "not_applicable"
        round_action = "wait_for_answer" if state == "QUESTION_ACTIVE" else "continue_discussion"
        knowledge_updates = []
        error_updates = []
    elif intent == "request_example":
        selected_verdict = "not_applicable"
        round_action = "wait_for_answer" if state == "QUESTION_ACTIVE" else "continue_discussion"
        knowledge_updates = []
        error_updates = []
    elif intent == "next_question":
        selected_verdict = verdict or "not_applicable"
        round_action = "finalize_round"
        knowledge_updates = []
        error_updates = []
    elif intent == "end_session":
        selected_verdict = "not_applicable"
        round_action = "end_session"
        knowledge_updates = []
        error_updates = []
    else:
        selected_verdict = verdict or "not_applicable"
        round_action = "continue_discussion"
        knowledge_updates = []
        error_updates = []

    return {
        "intent": intent,
        "intent_confidence": 0.95,
        "student_visible_reply_markdown": reply or f"已识别：{intent}",
        "verdict": selected_verdict,
        "round_action": round_action,
        "provisional_knowledge_updates": knowledge_updates,
        "provisional_error_updates": error_updates,
        "should_prepare_next_question": (
            state == "QUESTION_ACTIVE"
            and intent in {"answer_attempt", "answer_and_question", "student_uncertain"}
        ),
        "should_invalidate_candidate_question": diagnosis_changed,
    }


QUESTION_ACTIVE_INTENTS = {
    "next(iterator)": "answer_attempt",
    "我不确定": "student_uncertain",
    "不会": "student_uncertain",
    "这里用 next 吗": "clarification_question",
    "为什么不能用 iter": "clarification_question",
    "我觉得是 next(iterator)，但为什么": "answer_and_question",
    "再举个例子": "request_example",
    "懂了": "acknowledgement",
    "下一题": "next_question",
    "继续": "ambiguous",
    "结束学习": "end_session",
    "这道题是不是有问题": "challenge_evaluation",
}

FEEDBACK_DISCUSSION_INTENTS = {
    "next(iterator)": "answer_attempt",
    "我不确定": "student_uncertain",
    "不会": "student_uncertain",
    "这里用 next 吗": "clarification_question",
    "为什么不能用 iter": "clarification_question",
    "我觉得是 next(iterator)，但为什么": "answer_and_question",
    "再举个例子": "request_example",
    "懂了": "acknowledgement",
    "下一题": "next_question",
    "继续": "next_question",
    "结束学习": "end_session",
    "这道题是不是有问题": "challenge_evaluation",
}


class IntentFixtureProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls: List[List[Dict[str, str]]] = []

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        self.calls.append(messages)
        context = json.loads(messages[1]["content"])
        state = context["session_state"]
        message = context["student_message"]
        mapping = (
            QUESTION_ACTIVE_INTENTS
            if state == "QUESTION_ACTIVE"
            else FEEDBACK_DISCUSSION_INTENTS
        )
        return schema.model_validate(turn_result(mapping[message], state))


class InvalidThenTimeoutProvider(LLMProvider):
    def __init__(self) -> None:
        self.call_count = 0

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        self.call_count += 1
        if self.call_count == 1:
            invalid = turn_result("student_uncertain", "QUESTION_ACTIVE")
            invalid["verdict"] = "not_applicable"
            return schema.model_validate(invalid)
        raise LLMProviderError("LLM request timed out after 75 seconds")


class CriticConversationTests(unittest.TestCase):
    def test_required_intent_dataset_in_both_states(self) -> None:
        for state, mapping in [
            ("QUESTION_ACTIVE", QUESTION_ACTIVE_INTENTS),
            ("FEEDBACK_DISCUSSION", FEEDBACK_DISCUSSION_INTENTS),
        ]:
            for message, expected_intent in mapping.items():
                with self.subTest(state=state, message=message):
                    provider = IntentFixtureProvider()
                    execution = asyncio.run(
                        CriticConversationService(provider).process_turn(
                            turn_context(message, state)
                        )
                    )
                    self.assertEqual(execution.status, "completed")
                    self.assertEqual(execution.result.intent, expected_intent)
                    self.assertIn(message, provider.calls[0][1]["content"])

    def test_all_thirteen_intents_are_schema_valid(self) -> None:
        intents = [
            "answer_attempt",
            "student_uncertain",
            "clarification_question",
            "challenge_evaluation",
            "request_example",
            "concept_extension",
            "acknowledgement",
            "next_question",
            "answer_and_question",
            "request_summary",
            "end_session",
            "off_topic",
            "ambiguous",
        ]
        for intent in intents:
            with self.subTest(intent=intent):
                provider = MockLLMProvider(
                    [turn_result(intent, "FEEDBACK_DISCUSSION")]
                )
                execution = asyncio.run(
                    CriticConversationService(provider).process_turn(
                        turn_context("测试消息", "FEEDBACK_DISCUSSION")
                    )
                )
                self.assertEqual(execution.result.intent, intent)

    def test_pre_answer_clarification_keeps_question_active_and_gives_hint(self) -> None:
        provider = MockLLMProvider(
            [
                turn_result(
                    "clarification_question",
                    "QUESTION_ACTIVE",
                    reply="提示：先判断哪个对象保存了迭代状态。",
                )
            ]
        )
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("这里用 next 吗")
            )
        )

        self.assertEqual(execution.result.round_action, "wait_for_answer")
        self.assertEqual(execution.result.verdict, "not_applicable")
        self.assertEqual(execution.result.provisional_knowledge_updates, [])
        self.assertNotIn("next(iterator)", execution.result.student_visible_reply_markdown)

    def test_prompt_contains_exact_output_schema(self) -> None:
        provider = MockLLMProvider(
            [turn_result("student_uncertain", "QUESTION_ACTIVE")]
        )
        asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("我不确定")
            )
        )

        system_prompt = provider.calls[0][0]["content"]
        self.assertIn("JSON Schema", system_prompt)
        self.assertIn('"intent"', system_prompt)
        self.assertIn('"provisional_knowledge_updates"', system_prompt)
        self.assertIn("只有学生明确表达 next_question 意图时", system_prompt)
        self.assertIn("verdict=correct 时", system_prompt)
        self.assertIn("verdict=incorrect 或 partially_correct 时", system_prompt)

    def test_answer_and_question_is_evaluated_before_continuing_discussion(self) -> None:
        provider = MockLLMProvider(
            [
                turn_result(
                    "answer_and_question",
                    "QUESTION_ACTIVE",
                    reply=(
                        "回答正确。`next(iterator)` 取出下一个元素并推进状态。"
                        "`numbers[0]` 只是按索引读取列表。"
                    ),
                )
            ]
        )
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("我觉得是 next(iterator)，但为什么不能写 numbers[0]？")
            )
        )

        self.assertEqual(execution.result.verdict, "correct")
        self.assertEqual(execution.result.round_action, "show_feedback")
        self.assertTrue(execution.result.should_prepare_next_question)

    def test_challenge_can_correct_diagnosis_and_invalidate_candidate(self) -> None:
        provider = MockLLMProvider(
            [
                turn_result(
                    "challenge_evaluation",
                    "FEEDBACK_DISCUSSION",
                    verdict="correct",
                    reply="你说得对，我之前的判断有误。你的答案是正确的。",
                    diagnosis_changed=True,
                )
            ]
        )
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context(
                    "这道题是不是有问题",
                    "FEEDBACK_DISCUSSION",
                )
            )
        )

        self.assertEqual(execution.result.verdict, "correct")
        self.assertTrue(execution.result.should_invalidate_candidate_question)
        self.assertIn("判断有误", execution.result.student_visible_reply_markdown)

    def test_student_uncertainty_cannot_create_specific_negative_evidence(self) -> None:
        invalid = turn_result("student_uncertain", "QUESTION_ACTIVE")
        invalid["provisional_knowledge_updates"] = [
            {
                "node_id": "python.iterator.next",
                "evidence": "negative",
                "strength": 1.0,
                "reason": "Student said uncertain.",
            }
        ]
        provider = MockLLMProvider(
            [invalid, turn_result("student_uncertain", "QUESTION_ACTIVE")]
        )
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("我不确定")
            )
        )

        self.assertEqual(execution.retry_count, 1)
        self.assertEqual(execution.result.provisional_knowledge_updates, [])

    def test_two_invalid_outputs_return_safe_reply_without_updates(self) -> None:
        provider = MockLLMProvider([{"bad": 1}, {"bad": 2}])
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("next(iterator)")
            )
        )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.retry_count, 1)
        self.assertEqual(
            execution.result.student_visible_reply_markdown,
            SAFE_CRITIC_FAILURE_REPLY,
        )
        self.assertEqual(execution.result.verdict, "critic_uncertain")
        self.assertEqual(execution.result.provisional_knowledge_updates, [])
        self.assertEqual(execution.result.provisional_error_updates, [])

    def test_validation_error_then_provider_timeout_returns_safe_reply(self) -> None:
        provider = InvalidThenTimeoutProvider()
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("我不确定")
            )
        )

        self.assertEqual(provider.call_count, 2)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(
            execution.result.student_visible_reply_markdown,
            SAFE_CRITIC_FAILURE_REPLY,
        )
        self.assertEqual(execution.result.verdict, "critic_uncertain")
        self.assertEqual(execution.result.provisional_knowledge_updates, [])
        self.assertEqual(execution.result.provisional_error_updates, [])

    def test_invalid_reviewed_question_forces_replacement(self) -> None:
        invalid_review = QuestionReview(
            status="invalid",
            quality_score=0.1,
            issues=["Reference answer is incorrect."],
        )
        wrong_behavior = turn_result("answer_attempt", "QUESTION_ACTIVE")
        replacement_behavior = {
            **turn_result("ambiguous", "QUESTION_ACTIVE"),
            "verdict": "invalid_question",
            "round_action": "replace_question",
            "student_visible_reply_markdown": "这道题存在问题，我会为你换一道题。",
        }
        provider = MockLLMProvider([wrong_behavior, replacement_behavior])
        execution = asyncio.run(
            CriticConversationService(provider).process_turn(
                turn_context("next(iterator)", review=invalid_review)
            )
        )

        self.assertEqual(execution.retry_count, 1)
        self.assertEqual(execution.result.verdict, "invalid_question")
        self.assertEqual(execution.result.round_action, "replace_question")

    def test_discussion_summary_records_corrected_verdict(self) -> None:
        packet = QuestionPacket.model_validate(valid_question())
        first_result = turn_result("answer_attempt", "QUESTION_ACTIVE", verdict="incorrect")
        first_result["provisional_knowledge_updates"] = [
            {
                "node_id": "python.iterator.next",
                "evidence": "negative",
                "strength": 0.8,
                "reason": "Initial diagnosis.",
            }
        ]
        challenge_result = turn_result(
            "challenge_evaluation",
            "FEEDBACK_DISCUSSION",
            verdict="correct",
            diagnosis_changed=True,
        )
        summary = {
            "question_id": str(packet.question_id),
            "original_verdict": "incorrect",
            "final_verdict": "correct",
            "diagnosis_changed": True,
            "discussion_resolved": True,
            "confirmed_knowledge": ["python.iterator.next"],
            "remaining_knowledge_gaps": [],
            "active_errors": [],
            "resolved_errors": ["iter_vs_next"],
            "final_knowledge_updates": [
                {
                    "node_id": "python.iterator.next",
                    "evidence": "positive",
                    "strength": 0.9,
                    "reason": "Recheck confirmed the answer was correct.",
                }
            ],
            "final_error_updates": [
                {
                    "error_id": "iter_vs_next",
                    "action": "weaken",
                    "strength": 0.8,
                    "reason": "Student correctly distinguished iter and next.",
                }
            ],
            "next_question_guidance": {
                "strategy": "variation_practice",
                "avoid_repeating_surface_form": True,
            },
        }
        provider = MockLLMProvider([summary])
        context = DiscussionSummaryContext(
            question_packet=packet,
            question_review=approved_review(),
            conversation_history=[
                {
                    "role": "student",
                    "content_markdown": "next(iterator)",
                },
                {
                    "role": "student",
                    "content_markdown": "请重新检查。",
                },
            ],
            turn_results=[first_result, challenge_result],
        )
        execution = asyncio.run(
            CriticConversationService(provider).summarize_discussion(context)
        )

        self.assertEqual(execution.status, "completed")
        self.assertTrue(execution.summary.diagnosis_changed)
        self.assertEqual(execution.summary.final_verdict, "correct")

    def test_summary_schema_failure_retries_once_then_fails(self) -> None:
        packet = QuestionPacket.model_validate(valid_question())
        provider = MockLLMProvider(
            [
                {
                    "question_id": str(uuid4()),
                    "original_verdict": "incorrect",
                    "final_verdict": "incorrect",
                    "diagnosis_changed": True,
                    "discussion_resolved": True,
                    "confirmed_knowledge": [],
                    "remaining_knowledge_gaps": [],
                    "active_errors": [],
                    "resolved_errors": [],
                    "final_knowledge_updates": [],
                    "final_error_updates": [],
                    "next_question_guidance": {},
                },
                {"bad": 2},
            ]
        )
        context = DiscussionSummaryContext(
            question_packet=packet,
            question_review=approved_review(),
            conversation_history=[],
            turn_results=[
                turn_result("answer_attempt", "QUESTION_ACTIVE")
            ],
        )
        execution = asyncio.run(
            CriticConversationService(provider).summarize_discussion(context)
        )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.retry_count, 1)
        self.assertIsNone(execution.summary)


if __name__ == "__main__":
    unittest.main()
