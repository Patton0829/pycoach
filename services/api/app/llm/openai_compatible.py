import json
import re
from contextlib import aclosing
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Type

import httpx
from langchain_openai import ChatOpenAI
from openai import (
    APIStatusError,
    APITimeoutError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAIError,
)

from app.llm.base import (
    LLMProvider,
    LLMProviderError,
    SchemaT,
    TextDeltaCallback,
)


def extract_partial_json_string_field(document: str, field_name: str) -> str:
    match = re.search(
        rf'"{re.escape(field_name)}"\s*:\s*"',
        document,
    )
    if match is None:
        return ""

    index = match.end()
    raw_characters: List[str] = []
    while index < len(document):
        character = document[index]
        if character == '"':
            break
        if character != "\\":
            raw_characters.append(character)
            index += 1
            continue

        if index + 1 >= len(document):
            break
        escaped = document[index + 1]
        if escaped == "u":
            sequence = document[index : index + 6]
            if len(sequence) < 6 or not re.fullmatch(
                r"\\u[0-9a-fA-F]{4}",
                sequence,
            ):
                break
            raw_characters.append(sequence)
            index += 6
            continue
        if escaped not in '"\\/bfnrt':
            break
        raw_characters.append(document[index : index + 2])
        index += 2

    raw_value = "".join(raw_characters)
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        return ""


class OpenAICompatibleLLMProvider(LLMProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 75,
        extra_body: str = "",
        http_async_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required")
        if timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than zero")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.extra_body = self._parse_extra_body(extra_body)
        self.chat_model = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=self.base_url,
            temperature=0.2,
            timeout=timeout_seconds,
            # LangGraph owns the two-attempt repair policy. SDK retries would
            # multiply requests and make retry_count misleading.
            max_retries=0,
            extra_body=self.extra_body,
            http_async_client=http_async_client,
            stream_usage=False,
            use_responses_api=False,
        )

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        try:
            structured_model = self.chat_model.with_structured_output(
                schema, method="json_mode", include_raw=True,
            )
            response = await structured_model.ainvoke(messages)
        except (OpenAIError, httpx.HTTPError) as error:
            raise self._provider_error(error) from error
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise LLMProviderError("LLM provider returned an unexpected response shape") from error

        content = response["raw"].content
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("LLM provider returned empty message content")
        # LangChain's parser accepts repaired/partial JSON. Keep our existing
        # stricter boundary: only a complete JSON document may drive a turn.
        return schema.model_validate(json.loads(content))

    async def generate_structured_stream(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
        visible_path: Sequence[str],
        on_delta: TextDeltaCallback,
    ) -> SchemaT:
        if not visible_path:
            raise ValueError("visible_path must not be empty")
        content = ""
        visible_content = ""

        async with aclosing(self._stream_content(messages)) as stream:
            async for delta in stream:
                content += delta
                current_visible = extract_partial_json_string_field(
                    content,
                    visible_path[-1],
                )
                if current_visible.startswith(visible_content):
                    new_text = current_visible[len(visible_content) :]
                    if new_text:
                        visible_content = current_visible
                        await on_delta(new_text)

        if not content.strip():
            raise LLMProviderError("LLM provider returned empty streamed content")
        try:
            return schema.model_validate(json.loads(content))
        except json.JSONDecodeError as error:
            raise LLMProviderError(
                "LLM provider returned invalid streamed JSON"
            ) from error

    async def _stream_content(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        # Isolate transport errors from application callback failures. A failed
        # websocket callback must not be mistaken for malformed model output.
        # Own the SDK stream context directly: LangChain's nested astream
        # generators do not synchronously close their children on early exit.
        try:
            response = await self.chat_model.async_client.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
                stream=True,
                extra_body=self.extra_body,
            )
            async with response:
                async for chunk in response:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason == "length":
                        raise LLMProviderError(
                            "LLM provider truncated the response before completion"
                        )
                    if choice.finish_reason == "content_filter":
                        raise LLMProviderError("LLM provider could not complete the response")
                    delta = choice.delta.content
                    if not delta:
                        continue
                    if not isinstance(delta, str):
                        raise LLMProviderError("LLM provider returned non-text streamed content")
                    yield delta
        except (OpenAIError, httpx.HTTPError) as error:
            raise self._provider_error(error) from error
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise LLMProviderError("LLM provider returned malformed stream data") from error

    def _provider_error(self, error: Exception) -> LLMProviderError:
        if isinstance(error, LengthFinishReasonError):
            return LLMProviderError("LLM provider truncated the response before completion")
        if isinstance(error, ContentFilterFinishReasonError):
            return LLMProviderError("LLM provider could not complete the response")
        if isinstance(error, (APITimeoutError, httpx.TimeoutException)):
            return LLMProviderError(
                f"LLM request timed out after {self.timeout_seconds:g} seconds"
            )
        if isinstance(error, APIStatusError):
            return LLMProviderError(f"LLM provider returned HTTP {error.status_code}")
        if isinstance(error, httpx.HTTPStatusError):
            return LLMProviderError(
                f"LLM provider returned HTTP {error.response.status_code}"
            )
        return LLMProviderError("LLM provider request failed")

    @staticmethod
    def _parse_extra_body(raw_value: str) -> Dict[str, Any]:
        if not raw_value.strip():
            return {}
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ValueError("LLM_EXTRA_BODY must be a valid JSON object") from error
        if not isinstance(parsed, dict):
            raise ValueError("LLM_EXTRA_BODY must be a JSON object")
        reserved = {"model", "messages", "response_format", "stream"}
        conflicting = reserved.intersection(parsed)
        if conflicting:
            names = ", ".join(sorted(conflicting))
            raise ValueError(f"LLM_EXTRA_BODY cannot override: {names}")
        return parsed
