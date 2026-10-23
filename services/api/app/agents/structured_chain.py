from typing import Dict, List, Optional, Type, cast

from langchain_core.messages import convert_to_openai_messages
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnableSequence
from pydantic import BaseModel

from app.llm.base import LLMProvider, SchemaT, TextDeltaCallback


def build_structured_chain(
    provider: LLMProvider,
    schema: Type[SchemaT],
    on_delta: Optional[TextDeltaCallback] = None,
) -> RunnableSequence:
    """Render literal prompt values, call the provider, then validate the boundary."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            ("human", "{context_json}"),
            MessagesPlaceholder("validation_feedback_messages", optional=True),
        ]
    )

    async def invoke_provider(prompt_value: ChatPromptValue) -> SchemaT:
        messages = cast(
            List[Dict[str, str]],
            convert_to_openai_messages(prompt_value.to_messages()),
        )
        if on_delta is not None:
            return await provider.generate_structured_stream(
                messages,
                schema,
                ("student_visible_reply_markdown",),
                on_delta,
            )
        return await provider.generate_structured(messages, schema)

    def validate_output(result: SchemaT) -> SchemaT:
        # Revalidate model instances too: providers may return constructed or mutated models.
        data = result.model_dump(mode="python") if isinstance(result, BaseModel) else result
        return schema.model_validate(data)

    return (
        prompt
        | RunnableLambda(invoke_provider, name=f"{schema.__name__}Provider")
        | RunnableLambda(validate_output, name=f"{schema.__name__}Validation")
    )
