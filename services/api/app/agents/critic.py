from typing import Dict, List, Optional, Type, TypeVar

from app.llm.base import LLMProvider, TextDeltaCallback, schema_output_contract
from app.schemas.critic import CriticTurnResult, DiscussionSummary, QuestionReview

CriticSchema = TypeVar(
    "CriticSchema",
    QuestionReview,
    CriticTurnResult,
    DiscussionSummary,
)

STREAMING_VISIBLE_REPLY_CONTRACT = (
    "\n\n流式展示要求：当输出 CriticTurnResult JSON 时，必须把 "
    '"student_visible_reply_markdown" 作为第一个字段输出，并先生成该字段的'
    "完整学生可见回复文本；随后再输出 intent、intent_confidence、verdict、"
    "round_action 和图谱更新字段。"
)


class Critic:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def run(
        self,
        system_prompt: str,
        context_json: str,
        schema: Type[CriticSchema],
        validation_feedback: Optional[str] = None,
        on_delta: Optional[TextDeltaCallback] = None,
    ) -> CriticSchema:
        prompt = system_prompt
        if on_delta is not None and schema is CriticTurnResult:
            prompt += STREAMING_VISIBLE_REPLY_CONTRACT
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": prompt + schema_output_contract(schema),
            },
            {"role": "user", "content": context_json},
        ]
        if validation_feedback:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过 Schema 校验。只修正下列问题并重新输出"
                        f"完整 JSON：\n{validation_feedback}"
                    ),
                }
            )
        if on_delta is not None:
            return await self.provider.generate_structured_stream(
                messages,
                schema,
                ("student_visible_reply_markdown",),
                on_delta,
            )
        return await self.provider.generate_structured(messages, schema)
