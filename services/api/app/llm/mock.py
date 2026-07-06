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
            "检验学生能否使用当前 Python 知识点。",
        )
        variants = (
            self._foundation_question_variants(slot, goal, node_id, prompt_brief)
            if node_id.startswith("python.ch")
            else self._question_variants(slot, goal)
        )
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
                    "correct": "Matches the targeted Python rule.",
                    "partial": "Shows partial understanding of the targeted concept.",
                    "incorrect": "Misses the targeted Python rule or execution behavior.",
                },
                "expected_reasoning": selected["reasoning"],
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
                "reasoning": "The correct option matches the iterator protocol rule.",
            },
            "code_blank": {
                "markdown": code_blank.get(goal, code_blank["retrieve"]),
                "answer": blank_answer,
                "acceptable": [blank_answer],
                "reasoning": "The blank must use the operation that matches the current iterator state.",
            },
            "output_prediction": {
                "markdown": output_prediction.get(goal, output_prediction["predict_output"]),
                "answer": output_answer,
                "acceptable": output_acceptable,
                "reasoning": "Trace each statement in order and follow the iterator state.",
            },
            "short_explanation": {
                "markdown": short_explanation.get(goal, short_explanation["synthesize"]),
                "answer": "迭代器保存当前位置，next() 取值并推进；耗尽时抛出 StopIteration。",
                "acceptable": ["迭代器保存状态", "next会推进状态", "StopIteration"],
                "reasoning": "A complete explanation connects state, next(), and exhaustion.",
            },
        }

    def _foundation_question_variants(
        self,
        slot: int,
        goal: str,
        node_id: str,
        prompt_brief: str,
    ) -> dict:
        topic = self._topic_from_prompt(prompt_brief, node_id)
        mc_answer = self._foundation_mc_statement(node_id)
        blank_markdown, blank_answer, blank_reasoning = self._foundation_blank(slot, node_id, topic)
        output_markdown, output_answer, output_acceptable, output_reasoning = (
            self._foundation_output(slot, node_id, topic)
        )
        explanation_answer, explanation_acceptable, explanation_reasoning = (
            self._foundation_explanation(node_id, topic)
        )
        return {
            "multiple_choice": {
                "markdown": (
                    f"第 {slot} 题：关于“{topic}”，下面哪项更符合 Python 规则？\n\n"
                    "A. 只要语法能运行，结果总会自动转换成字符串\n\n"
                    f"B. {mc_answer}\n\n"
                    "C. 所有相关操作都会修改原对象并返回自身\n\n"
                    "D. Python 会忽略名称绑定、作用域或执行顺序的差异"
                ),
                "answer": "B",
                "acceptable": ["B", "b"],
                "reasoning": mc_answer,
            },
            "code_blank": {
                "markdown": blank_markdown,
                "answer": blank_answer,
                "acceptable": [blank_answer],
                "reasoning": blank_reasoning,
            },
            "output_prediction": {
                "markdown": output_markdown,
                "answer": output_answer,
                "acceptable": output_acceptable,
                "reasoning": output_reasoning,
            },
            "short_explanation": {
                "markdown": f"第 {slot} 题：请用 1-3 句话说明“{topic}”的核心规则。",
                "answer": explanation_answer,
                "acceptable": explanation_acceptable,
                "reasoning": explanation_reasoning,
            },
        }

    @staticmethod
    def _topic_from_prompt(prompt_brief: str, node_id: str) -> str:
        if "“" in prompt_brief and "”" in prompt_brief:
            return prompt_brief.split("“", 1)[1].split("”", 1)[0]
        return node_id

    @staticmethod
    def _foundation_mc_statement(node_id: str) -> str:
        statements = {
            "python.ch3.sequence_indexing": "切片的停止位置不包含在结果中。",
            "python.ch3.assignment_mutability": "给同一个可变对象建立多个名字后，原地修改会被这些名字共同观察到。",
            "python.ch4.for_range": "`range(stop)` 从 0 开始，到 stop 之前结束。",
            "python.ch4.arguments": "默认参数在函数定义时求值，关键字参数按名字绑定。",
            "python.ch5.list_methods": "`list.sort()` 会原地排序并返回 `None`。",
            "python.ch5.sets_dicts": "字典按键查找值，集合主要表达唯一元素和集合运算。",
            "python.ch6.imports": "`import module` 绑定模块名，`from module import name` 绑定导入的名字。",
            "python.ch7.with_files": "`with open(...)` 会在代码块结束时关闭文件对象。",
            "python.ch8.try_except": "异常发生后会跳到匹配的 except，finally 在离开 try 结构时执行。",
            "python.ch9.instance_methods": "实例方法通过 `self` 访问和更新当前实例的属性。",
        }
        return statements.get(node_id, "需要按照表达式、语句和名称绑定规则逐步判断结果。")

    @staticmethod
    def _foundation_blank(slot: int, node_id: str, topic: str) -> tuple[str, str, str]:
        examples = {
            "python.ch3.numbers": (
                "```python\nresult = ________\nprint(result)\n```",
                "7 // 3",
                "Floor division returns the integer quotient.",
            ),
            "python.ch3.text": (
                "```python\ntext = \"Python\"\npart = ________\nprint(part)\n```",
                "text[1:4]",
                "String slicing uses zero-based, half-open bounds.",
            ),
            "python.ch4.for_range": (
                "```python\nfor i in ________:\n    print(i)\n```",
                "range(3)",
                "range(3) yields 0, 1, and 2.",
            ),
            "python.ch5.comprehensions": (
                "```python\nsquares = ________\nprint(squares)\n```",
                "[x * x for x in range(3)]",
                "A list comprehension builds a new list from the loop expression.",
            ),
            "python.ch6.imports": (
                "```python\nimport math\nvalue = ________\nprint(value)\n```",
                "math.sqrt(9)",
                "After import math, sqrt is accessed as an attribute on the module.",
            ),
            "python.ch7.fstrings_format": (
                "```python\nname = \"Ada\"\nmessage = ________\nprint(message)\n```",
                "f\"Hi {name}\"",
                "An f-string interpolates the name expression.",
            ),
            "python.ch8.raise": (
                "```python\nif value < 0:\n    ________ ValueError(\"negative\")\n```",
                "raise",
                "raise starts an exception path with the given exception object.",
            ),
            "python.ch9.instance_methods": (
                "```python\nclass User:\n    def __init__(self, name):\n        ________ = name\n```",
                "self.name",
                "self.name stores data on the current instance.",
            ),
        }
        code, answer, reasoning = examples.get(
            node_id,
            (
                "```python\nvalue = 3\nresult = ________\nprint(result)\n```",
                "value",
                "The blank should preserve the value required by the surrounding code.",
            ),
        )
        return (
            f"第 {slot} 题：围绕“{topic}”填写缺失内容。\n\n{code}",
            answer,
            reasoning,
        )

    @staticmethod
    def _foundation_output(
        slot: int,
        node_id: str,
        topic: str,
    ) -> tuple[str, str, list[str], str]:
        examples = {
            "python.ch3.lists": (
                "```python\nitems = [1, 2]\nitems.append(3)\nprint(items)\n```",
                "[1, 2, 3]",
                ["[1, 2, 3]", "[1,2,3]"],
                "append mutates the list in place.",
            ),
            "python.ch4.loop_control": (
                "```python\nfor i in range(4):\n    if i == 2:\n        break\n    print(i)\n```",
                "0\n1",
                ["0\n1", "0 1"],
                "break exits the loop before printing 2.",
            ),
            "python.ch5.list_methods": (
                "```python\nitems = [3, 1]\nresult = items.sort()\nprint(items)\nprint(result)\n```",
                "[1, 3]\nNone",
                ["[1, 3]\nNone", "[1,3]\nNone"],
                "sort mutates the list and returns None.",
            ),
            "python.ch7.str_repr": (
                "```python\nvalue = \"A\\nB\"\nprint(str(value))\nprint(repr(value))\n```",
                "A\nB\n'A\\nB'",
                ["A\nB\n'A\\nB'"],
                "str displays the string; repr shows an escaped representation.",
            ),
            "python.ch8.try_except": (
                "```python\ntry:\n    print(\"A\")\n    int(\"x\")\n    print(\"B\")\nexcept ValueError:\n    print(\"C\")\nfinally:\n    print(\"D\")\n```",
                "A\nC\nD",
                ["A\nC\nD", "A C D"],
                "The ValueError skips B, runs except, then finally.",
            ),
            "python.ch9.class_instance_variables": (
                "```python\nclass Bag:\n    items = []\n\na = Bag()\nb = Bag()\na.items.append(\"x\")\nprint(b.items)\n```",
                "['x']",
                ["['x']", "[\"x\"]"],
                "items is a class variable shared by both instances.",
            ),
        }
        code, answer, acceptable, reasoning = examples.get(
            node_id,
            (
                "```python\nx = 2\nx = x + 3\nprint(x)\n```",
                "5",
                ["5"],
                "Trace assignment and expression evaluation in order.",
            ),
        )
        return (
            f"第 {slot} 题：围绕“{topic}”预测输出。\n\n{code}",
            answer,
            acceptable,
            reasoning,
        )

    @staticmethod
    def _foundation_explanation(
        node_id: str,
        topic: str,
    ) -> tuple[str, list[str], str]:
        answers = {
            "python.ch6.search_path": (
                "Python 会按模块搜索路径查找导入目标，通常包括当前目录、PYTHONPATH 和安装目录。",
                ["搜索路径", "sys.path", "PYTHONPATH"],
                "Imports are resolved through sys.path-like search order.",
            ),
            "python.ch8.custom_exceptions": (
                "自定义异常通常继承 Exception，用清晰的异常类型表达特定错误场景。",
                ["继承 Exception", "自定义异常", "错误场景"],
                "Custom exceptions encode domain-specific failure types.",
            ),
            "python.ch9.namespaces_scopes": (
                "Python 按局部、外层、全局、内置等作用域查找名字，赋值会在相应作用域绑定名字。",
                ["作用域", "命名空间", "名字查找"],
                "Name lookup follows scope and namespace rules.",
            ),
        }
        return answers.get(
            node_id,
            (
                f"{topic} 要根据 Python 的具体语义逐步判断，包括表达式求值、名称绑定和对象行为。",
                [topic, "规则", "语义"],
                "A good explanation states the governing Python rule and applies it to code.",
            ),
        )

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
            reply = f"没关系。关键点是：{question['critic_content']['expected_reasoning']}"
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
            reply = question["critic_content"]["expected_reasoning"]
        elif "懂了" in message:
            intent = "acknowledgement"
            reply = "好的。你可以继续追问，或者输入“下一题”。"
        elif "生成器" in message:
            intent = "concept_extension"
            reply = "生成器会产生迭代器；当前仍按本题目标知识点来判断。"
        elif "天气" in message:
            intent = "off_topic"
            reply = "这个问题与当前 Python 题目无关，我们先回到当前题目。"
        elif "?" in message or "？" in message or "为什么" in message or "这里用" in message:
            if "next(" in lowered:
                intent = "answer_and_question"
                verdict = "correct"
                action = "show_feedback" if state == "QUESTION_ACTIVE" else "continue_discussion"
                reply = "回答正确。你的答案符合本题考查的 Python 规则。"
                prepare = state == "QUESTION_ACTIVE"
            else:
                intent = "clarification_question"
                action = "wait_for_answer" if state == "QUESTION_ACTIVE" else "continue_discussion"
                reply = f"提示：先抓住本题目标规则：{question['critic_content']['learning_objective']}"
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
                reply = "回答正确。你的答案符合本题考查的 Python 规则。"
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
                            "reason": "Student resolved the targeted misconception.",
                        }
                    ]
            else:
                verdict = "incorrect"
                reply = (
                    "这次回答不正确。关键点是："
                    f"{question['critic_content']['expected_reasoning']}"
                )
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
                            "reason": "Student missed the targeted Python rule.",
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
