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
        blueprint = context.get("critic_summary", {}).get(
            "chapter_question_blueprint",
            {},
        )
        question_type = (
            blueprint.get("question_type")
            or constraints.get("preferred_question_type")
            or "multiple_choice"
        )
        target_nodes = (
            blueprint.get("target_knowledge_node_ids")
            or constraints.get("allowed_knowledge_node_ids", [])
        )
        target_errors = (
            blueprint.get("target_error_ids")
            or constraints.get("allowed_error_ids", [])
        )
        node_id = target_nodes[0] if target_nodes else "python.iterator.next"
        error_id = target_errors[0] if target_errors else None
        slot = blueprint.get("slot") or len(context.get("recent_questions", [])) + 1
        goal = blueprint.get("cognitive_goal") or "retrieve"
        prompt_brief = blueprint.get(
            "prompt_brief",
            "检验学生能否使用 Python 迭代器协议。",
        )
        variants = self._question_variants(slot, goal)
        selected = variants[question_type]
        return {
            "question_id": str(uuid4()),
            "question_type": question_type,
            "difficulty": blueprint.get("difficulty", 2),
            "knowledge_node_ids": [node_id],
            "target_error_ids": [error_id] if error_id else [],
            "pedagogical_strategy": blueprint.get(
                "pedagogical_strategy",
                "retrieval_practice",
            ),
            "student_content": {
                "markdown": selected["markdown"],
                "input_hint": "直接输入答案，也可以提出疑问。",
            },
            "critic_content": {
                "learning_objective": prompt_brief,
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

    def _question_variants(self, slot: int, goal: str) -> dict:
        multiple_choice = {
            "recognize": (
                "关于可迭代对象和迭代器，下面哪项正确？\n\n"
                "A. 列表本身会记住 `next()` 的当前位置\n\n"
                "B. `iter([1, 2])` 会创建一个可传给 `next()` 的迭代器\n\n"
                "C. `next([1, 2])` 可以直接取出列表第一个元素\n\n"
                "D. 每次 `next(it)` 都会从开头重新取值"
            ),
            "construct": (
                "要从元组 `source` 创建一个迭代器，下面哪项最合适？\n\n"
                "A. `next(source)`\n\nB. `iter(source)`\n\n"
                "C. `source[0]`\n\nD. `list(source)`"
            ),
            "contrast_operations": (
                "关于 `iter(data)` 和 `next(it)`，下面哪项正确？\n\n"
                "A. 二者都会把同一个迭代器向前推进\n\n"
                "B. `iter(data)` 创建迭代器，`next(it)` 取值并推进状态\n\n"
                "C. `next(it)` 会自动创建一个全新的迭代器\n\n"
                "D. 二者都只适用于列表"
            ),
        }
        code_blank = {
            "construct": (
                f"第 {slot} 题：填写缺失内容，创建迭代器并输出 `10`：\n\n"
                "```python\nsource = (10, 20, 30)\nit = ________\nprint(next(it))\n```"
            ),
            "retrieve": (
                f"第 {slot} 题：填写缺失内容，使程序输出 `10`：\n\n"
                "```python\nnumbers = [10, 20, 30]\niterator = iter(numbers)\n"
                "first = ________\nprint(first)\n```"
            ),
            "contrast_operations": (
                f"第 {slot} 题：填写缺失内容，取出当前迭代器的下一个元素：\n\n"
                "```python\ndata = [3, 6, 9]\nit = iter(data)\nnext(it)\nsecond = ________\n```"
            ),
            "transfer": (
                f"第 {slot} 题：生成器已经是迭代器，填写缺失内容取出第一个值：\n\n"
                "```python\ndef values():\n    yield 4\ngen = values()\nfirst = ________\n```"
            ),
        }
        output_prediction = {
            "trace_state": (
                f"第 {slot} 题：预测输出。\n\n"
                "```python\nitems = ['A', 'B', 'C']\nit = iter(items)\n"
                "print(next(it))\nprint(next(it))\nprint(next(it))\n```"
            ),
            "predict_output": (
                f"第 {slot} 题：预测所有 print 输出，每行一个。\n\n"
                "```python\nnums = [1, 2]\nit = iter(nums)\nprint(next(it))\n"
                "print(next(it))\ntry:\n    print(next(it))\n"
                "except StopIteration:\n    print('End')\n```"
            ),
            "diagnose_exhaustion": (
                f"第 {slot} 题：预测输出。\n\n"
                "```python\nit = iter(['x'])\nprint(next(it))\n"
                "try:\n    print(next(it))\nexcept StopIteration:\n    print('Done')\n```"
            ),
        }
        short_explanation = {
            "explain_protocol": (
                f"第 {slot} 题：简要说明 `for item in data` 背后如何使用 "
                "`iter()`、`next()` 和 `StopIteration`。"
            ),
            "diagnose_exhaustion": (
                f"第 {slot} 题：一个迭代器已经被取完，再调用 `next(it)` "
                "会发生什么？为什么？"
            ),
            "synthesize": (
                f"第 {slot} 题：为什么同一个迭代器连续调用 `next()` 会得到"
                "不同结果，而重新 `iter(data)` 又会从头开始？"
            ),
            "transfer": (
                f"第 {slot} 题：生成器和普通迭代器在 `next()` 取值行为上"
                "有什么共同点？"
            ),
        }
        if goal == "construct":
            blank_answer = "iter(source)"
        elif goal == "retrieve":
            blank_answer = "next(iterator)"
        elif goal == "transfer":
            blank_answer = "next(gen)"
        else:
            blank_answer = "next(it)"

        if goal == "trace_state":
            output_answer = "A\nB\nC"
            output_acceptable = ["A\nB\nC", "A B C"]
        elif goal == "diagnose_exhaustion":
            output_answer = "x\nDone"
            output_acceptable = ["x\nDone", "x Done"]
        else:
            output_answer = "1\n2\nEnd"
            output_acceptable = ["1\n2\nEnd", "1 2 End"]

        return {
            "multiple_choice": {
                "markdown": f"第 {slot} 题：{multiple_choice.get(goal, multiple_choice['recognize'])}",
                "answer": "B",
                "acceptable": ["B", "b"],
            },
            "code_blank": {
                "markdown": code_blank.get(goal, code_blank["retrieve"]),
                "answer": blank_answer,
                "acceptable": [blank_answer],
            },
            "output_prediction": {
                "markdown": output_prediction.get(goal, output_prediction["predict_output"]),
                "answer": output_answer,
                "acceptable": output_acceptable,
            },
            "short_explanation": {
                "markdown": short_explanation.get(goal, short_explanation["synthesize"]),
                "answer": "迭代器保存当前位置，next() 取值并推进；耗尽时抛出 StopIteration。",
                "acceptable": ["迭代器保存状态", "next会推进状态", "StopIteration"],
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
