from typing import Dict, List, Optional, Type, TypeVar

from app.llm.base import LLMProvider, TextDeltaCallback, schema_output_contract
from app.schemas.critic import CriticTurnResult, DiscussionSummary, QuestionReview

CriticSchema = TypeVar(
    "CriticSchema",
    QuestionReview,
    CriticTurnResult,
    DiscussionSummary,
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
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": system_prompt + schema_output_contract(schema),
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
