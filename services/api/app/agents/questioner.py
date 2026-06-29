from typing import Dict, List, Optional

from app.llm.base import LLMProvider, schema_output_contract
from app.schemas.question import QuestionPacket, QuestionerContext


class Questioner:
    def __init__(self, provider: LLMProvider, system_prompt: str) -> None:
        self.provider = provider
        self.system_prompt = system_prompt

    async def generate(
        self,
        context: QuestionerContext,
        validation_feedback: Optional[str] = None,
    ) -> QuestionPacket:
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": self.system_prompt
                + schema_output_contract(QuestionPacket),
            },
            {
                "role": "user",
                "content": context.model_dump_json(indent=2),
            },
        ]
        if validation_feedback:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "上一次输出无效。只修正下列问题并重新输出完整的 "
                        f"QuestionPacket JSON：\n{validation_feedback}"
                    ),
                }
            )
        return await self.provider.generate_structured(messages, QuestionPacket)
