from typing import Optional

from langchain_core.messages import HumanMessage

from app.agents.structured_chain import build_structured_chain
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
        feedback_messages = []
        if validation_feedback:
            feedback_messages.append(
                HumanMessage(
                    content=(
                        "上一次输出无效。只修正下列问题并重新输出完整的 "
                        f"QuestionPacket JSON：\n{validation_feedback}"
                    ),
                )
            )
        chain = build_structured_chain(self.provider, QuestionPacket)
        return await chain.ainvoke(
            {
                "system_prompt": self.system_prompt + schema_output_contract(QuestionPacket),
                "context_json": context.model_dump_json(indent=2),
                "validation_feedback_messages": feedback_messages,
            }
        )
