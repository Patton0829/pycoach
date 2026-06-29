from abc import ABC, abstractmethod
import json
from typing import Awaitable, Callable, Dict, List, Sequence, Type, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)
TextDeltaCallback = Callable[[str], Awaitable[None]]


class LLMProviderError(RuntimeError):
    """A recoverable failure while calling an external model provider."""


def schema_output_contract(schema: Type[SchemaT]) -> str:
    serialized = json.dumps(
        schema.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "\n\n输出必须严格满足下面的 JSON Schema。"
        "字段名、必填字段、枚举值和嵌套结构都不得自行修改：\n"
        f"{serialized}"
    )


class LLMProvider(ABC):
    @abstractmethod
    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        """Generate and validate one structured model response."""

    async def generate_structured_stream(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
        visible_path: Sequence[str],
        on_delta: TextDeltaCallback,
    ) -> SchemaT:
        """Generate structured output and expose only one student-visible field."""
        result = await self.generate_structured(messages, schema)
        value = result
        for part in visible_path:
            value = getattr(value, part)
        if not isinstance(value, str):
            raise LLMProviderError("Streamed visible field must be a string")
        if value:
            await on_delta(value)
        return result
