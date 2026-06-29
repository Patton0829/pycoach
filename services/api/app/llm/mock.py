from collections import deque
import json
from typing import Any, Deque, Dict, List, Type
from uuid import uuid4

from app.llm.base import LLMProvider, SchemaT


class MockLLMProvider(LLMProvider):
    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self._responses: Deque[Dict[str, Any]] = deque(responses)
        self.calls: List[List[Dict[str, str]]] = []

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        self.calls.append(messages)
        if not self._responses:
            raise RuntimeError("MockLLMProvider has no queued response")
        return schema.model_validate(self._responses.popleft())


class DemoMockLLMProvider(LLMProvider):
    """Deterministic local provider used by Docker and manual development."""

    def __init__(self) -> None:
        self.calls: List[tuple[str, List[Dict[str, str]]]] = []

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        self.calls.append((schema.__name__, messages))
        context = json.loads(messages[1]["content"])
        builders = {
            "QuestionPacket": self._question_packet,
            "QuestionReview": self._question_review,
            "CriticTurnResult": self._critic_turn,
            "DiscussionSummary": self._discussion_summary,
        }
        try:
            payload = builders[schema.__name__](context)
        except KeyError as error:
            raise RuntimeError(
                f"DemoMockLLMProvider does not support {schema.__name__}"
            ) from error
        return schema.model_validate(payload)

    def _question_packet(self, context: dict) -> dict:
        constraints = context["candidate_constraints"]
        question_type = constraints.get("preferred_question_type") or "multiple_choice"
        recent_count = len(context.get("recent_questions", []))
        allowed_nodes = constraints.get("allowed_knowledge_node_ids", [])
        allowed_errors = constraints.get("allowed_error_ids", [])

        node_id = (
            "python.iterator.next"
            if "python.iterator.next" in allowed_nodes
            else allowed_nodes[0]
        )
        error_id = "iter_vs_next" if "iter_vs_next" in allowed_errors else None
        variants = {
            "multiple_choice": {
                "markdown": (
                    f"第 {recent_count + 1} 题：下面哪个表达式会从迭代器中取出"
                    "下一个元素？\n\nA. `iter(iterator)`\n\n"
                    "B. `next(iterator)`\n\nC. `iterator[0]`\n\nD. `list(iterator)`"
                ),
                "answer": "B",
                "acceptable": ["B", "b", "next(iterator)"],
            },
            "code_blank": {
                "markdown": (
                    f"第 {recent_count + 1} 题：填写缺失内容。\n\n"
                    "```python\nvalues = [4, 8]\nit = iter(values)\n"
                    "first = ________\nprint(first)\n```"
                ),
                "answer": "next(it)",
                "acceptable": ["next(it)"],
            },
            "output_prediction": {
                "markdown": (
                    f"第 {recent_count + 1} 题：预测输出。\n\n"
                    "```python\nvalues = [3, 6]\nit = iter(values)\n"
                    "print(next(it))\nprint(next(it))\n```"
                ),
                "answer": "3 then 6",
                "acceptable": ["3\\n6", "3 then 6"],
            },
            "short_explanation": {
                "markdown": (
                    f"第 {recent_count + 1} 题：为什么连续调用 `next(it)` "
                    "会得到不同元素？请简短说明。"
                ),
                "answer": "The iterator stores and advances its state.",
                "acceptable": ["迭代器会保存并推进状态。"],
            },
        }
        selected = variants[question_type]
        return {
            "question_id": str(uuid4()),
            "question_type": question_type,
            "difficulty": 2,
            "knowledge_node_ids": [node_id],
            "target_error_ids": [error_id] if error_id else [],
            "pedagogical_strategy": "retrieval_practice",
            "student_content": {
                "markdown": selected["markdown"],
                "input_hint": "直接输入答案，也可以提出疑问。",
            },
            "critic_content": {
                "learning_objective": "Use next() and explain iterator state.",
                "reference_answer": selected["answer"],
                "acceptable_answers": selected["acceptable"],
                "grading_rubric": {
                    "correct": "Matches the iterator protocol.",
                    "partial": "Shows partial understanding.",
                    "incorrect": "Confuses iter(), next(), or indexing.",
                },
                "expected_reasoning": "next() returns one item and advances state.",
                "ambiguity_notes": None,
            },
        }

    def _question_review(self, context: dict) -> dict:
        return {
            "status": "approved",
            "quality_score": 0.95,
            "issues": [],
            "grading_notes": "Accept semantically equivalent answers.",
        }

    def _critic_turn(self, context: dict) -> dict:
        message = context["student_message"].strip()
        state = context["session_state"]
        lowered = message.lower()
        question = context["question_packet"]
        node_id = question["knowledge_node_ids"][0]
        error_ids = question.get("target_error_ids", [])

        intent = "ambiguous"
        verdict = "not_applicable"
        action = "continue_discussion"
        reply = "我还不能确定你的意思。可以换一种说法吗？"
        knowledge_updates = []
        error_updates = []
        prepare = False
        invalidate = False

        if context["question_review"]["status"] == "invalid":
            intent = "ambiguous"
            verdict = "invalid_question"
            action = "replace_question"
            reply = "这道题存在问题，不会影响你的学习记录。我会为你换一道题。"
        elif "结束" in message:
            intent, action = "end_session", "end_session"
            reply = "本次学习先到这里。"
        elif "下一题" in message or (state == "FEEDBACK_DISCUSSION" and message == "继续"):
            intent, action = "next_question", "finalize_round"
            reply = "好的，我们进入下一题。"
        elif "不确定" in message or message == "不会":
            intent, verdict = "student_uncertain", "student_uncertain"
            action = "show_feedback" if state == "QUESTION_ACTIVE" else "continue_discussion"
            reply = "没关系。`iter()` 得到迭代器，`next()` 从迭代器取出下一个元素。"
            prepare = state == "QUESTION_ACTIVE"
        elif "有问题" in message or "重新检查" in message:
            intent = "challenge_evaluation"
            action = "continue_discussion"
            verdict = "correct"
            reply = "我重新检查了题目和答案。你的质疑成立，我修正之前的判断。"
            invalidate = True
        elif "例子" in message:
            intent = "request_example"
            action = "wait_for_answer" if state == "QUESTION_ACTIVE" else "continue_discussion"
            reply = "例如 `it = iter([1, 2])`，两次 `next(it)` 依次得到 1 和 2。"
        elif "总结" in message:
            intent = "request_summary"
            reply = "`iter()` 创建迭代器，`next()` 读取并推进状态。"
        elif "懂了" in message:
            intent = "acknowledgement"
            reply = "好的。你可以继续追问，或者输入“下一题”。"
        elif "生成器" in message:
            intent = "concept_extension"
            reply = "生成器会产生迭代器，但当前先聚焦迭代器协议。"
        elif "天气" in message:
            intent = "off_topic"
            reply = "这个问题与当前迭代器学习无关，我们先回到当前题目。"
        elif "?" in message or "？" in message or "为什么" in message or "这里用" in message:
            if "next(" in lowered:
                intent = "answer_and_question"
                verdict = "correct"
                action = "show_feedback" if state == "QUESTION_ACTIVE" else "continue_discussion"
                reply = "回答正确。`next()` 读取元素并推进迭代状态。"
                prepare = state == "QUESTION_ACTIVE"
            else:
                intent = "clarification_question"
                action = "wait_for_answer" if state == "QUESTION_ACTIVE" else "continue_discussion"
                reply = "提示：先判断哪个对象保存了迭代状态。"
        elif state == "QUESTION_ACTIVE":
            intent = "answer_attempt"
            action = "show_feedback"
            prepare = True
            acceptable = [
                item.lower()
                for item in question["critic_content"]["acceptable_answers"]
            ]
            is_correct = lowered in acceptable or (
                "next(" in lowered
                and any("next(" in answer for answer in acceptable)
            )
            if is_correct:
                verdict = "correct"
                reply = "回答正确。`next()` 会返回下一个元素并推进迭代状态。"
                knowledge_updates = [
                    {
                        "node_id": node_id,
                        "evidence": "positive",
                        "strength": 0.9,
                        "reason": "Student answered correctly.",
                    }
                ]
                if error_ids:
                    error_updates = [
                        {
                            "error_id": error_ids[0],
                            "action": "weaken",
                            "strength": 0.8,
                            "reason": "Student distinguished iter() and next().",
                        }
                    ]
            else:
                verdict = "incorrect"
                reply = "这次回答不正确。`iter()` 创建迭代器，取元素需要使用 `next()`。"
                knowledge_updates = [
                    {
                        "node_id": node_id,
                        "evidence": "negative",
                        "strength": 0.8,
                        "reason": "Student confused the iterator operation.",
                    }
                ]
                if error_ids:
                    error_updates = [
                        {
                            "error_id": error_ids[0],
                            "action": "strengthen",
                            "strength": 0.8,
                            "reason": "Student confused iter() and next().",
                        }
                    ]

        return {
            "intent": intent,
            "intent_confidence": 0.95,
            "student_visible_reply_markdown": reply,
            "verdict": verdict,
            "round_action": action,
            "provisional_knowledge_updates": knowledge_updates,
            "provisional_error_updates": error_updates,
            "should_prepare_next_question": prepare,
            "should_invalidate_candidate_question": invalidate,
        }

    def _discussion_summary(self, context: dict) -> dict:
        results = context.get("turn_results", [])
        evaluative = [
            result
            for result in results
            if result["verdict"]
            not in {"not_applicable", "critic_uncertain"}
        ]
        original = evaluative[0]["verdict"] if evaluative else "not_applicable"
        final = evaluative[-1]["verdict"] if evaluative else original
        final_result = evaluative[-1] if evaluative else None
        reliable = final not in {
            "critic_uncertain",
            "invalid_question",
            "not_applicable",
        }
        knowledge_updates = (
            final_result["provisional_knowledge_updates"]
            if reliable and final_result
            else []
        )
        error_updates = (
            final_result["provisional_error_updates"]
            if reliable and final_result
            else []
        )
        if reliable and final == "correct" and not knowledge_updates:
            knowledge_updates = [
                {
                    "node_id": context["question_packet"]["knowledge_node_ids"][0],
                    "evidence": "positive",
                    "strength": 0.8,
                    "reason": "Final discussion confirmed correct understanding.",
                }
            ]
            if context["question_packet"]["target_error_ids"]:
                error_updates = [
                    {
                        "error_id": context["question_packet"]["target_error_ids"][0],
                        "action": "weaken",
                        "strength": 0.7,
                        "reason": "Final discussion resolved the targeted confusion.",
                    }
                ]
        return {
            "question_id": context["question_packet"]["question_id"],
            "original_verdict": original,
            "final_verdict": final,
            "diagnosis_changed": original != final,
            "discussion_resolved": True,
            "confirmed_knowledge": (
                context["question_packet"]["knowledge_node_ids"]
                if final == "correct"
                else []
            ),
            "remaining_knowledge_gaps": (
                context["question_packet"]["knowledge_node_ids"]
                if final in {"incorrect", "partially_correct", "student_uncertain"}
                else []
            ),
            "active_errors": (
                context["question_packet"]["target_error_ids"]
                if final == "incorrect"
                else []
            ),
            "resolved_errors": (
                context["question_packet"]["target_error_ids"]
                if final == "correct"
                else []
            ),
            "final_knowledge_updates": knowledge_updates,
            "final_error_updates": error_updates,
            "next_question_guidance": {
                "strategy": "variation_practice",
                "final_verdict": final,
                "diagnosis_changed": original != final,
            },
        }
