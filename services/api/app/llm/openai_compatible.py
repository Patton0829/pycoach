import json
import re
from typing import Any, Dict, List, Sequence, Type

import httpx

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

    async def generate_structured(
        self,
        messages: List[Dict[str, str]],
        schema: Type[SchemaT],
    ) -> SchemaT:
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        payload.update(self.extra_body)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LLMProviderError(
                f"LLM request timed out after {self.timeout_seconds:g} seconds"
            ) from error
        except httpx.HTTPStatusError as error:
            raise LLMProviderError(
                f"LLM provider returned HTTP {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise LLMProviderError("LLM provider request failed") from error

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMProviderError(
                "LLM provider returned an unexpected response shape"
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("LLM provider returned empty message content")
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
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "stream": True,
        }
        payload.update(self.extra_body)
        headers = {"Authorization": f"Bearer {self.api_key}"}
        content = ""
        visible_content = ""

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                            choices = event.get("choices", [])
                        except (
                            json.JSONDecodeError,
                            TypeError,
                        ) as error:
                            raise LLMProviderError(
                                "LLM provider returned malformed stream data"
                            ) from error
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content")
                        if not delta:
                            continue
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
        except httpx.TimeoutException as error:
            raise LLMProviderError(
                f"LLM request timed out after {self.timeout_seconds:g} seconds"
            ) from error
        except httpx.HTTPStatusError as error:
            raise LLMProviderError(
                f"LLM provider returned HTTP {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise LLMProviderError("LLM provider request failed") from error

        if not content.strip():
            raise LLMProviderError("LLM provider returned empty streamed content")
        try:
            return schema.model_validate(json.loads(content))
        except json.JSONDecodeError as error:
            raise LLMProviderError(
                "LLM provider returned invalid streamed JSON"
            ) from error

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
