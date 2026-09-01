import json
import re
import time
from typing import Any

import httpx

from .base import LLMCallResult, NodeLLMRequest


def _payload(request: NodeLLMRequest) -> str:
    return json.dumps(request.user_payload, ensure_ascii=False, default=str)


def _json_text(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("structured output must be a JSON object")
    return value


def _raise_for_status_with_body(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        provider_body = response.text[:2000]
        raise httpx.HTTPStatusError(
            f"{exc}\nProvider response: {provider_body}",
            request=response.request,
            response=response,
        ) from exc


def _deepseek_json(raw: str, finish_reason: Any, api_key: str) -> dict[str, Any]:
    try:
        return _json_text(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        tail = raw[-240:].replace("\r", "\\r").replace("\n", "\\n")
        if api_key:
            tail = tail.replace(api_key, "[REDACTED]")
        tail = re.sub(
            r"(?i)(authorization|api[_-]?key)\s*[:=]\s*[^\s,;}]+",
            r"\1=[REDACTED]",
            tail,
        )
        tail = re.sub(r"(?i)bearer\s+[^\s,;}]+", "Bearer [REDACTED]", tail)
        raise ValueError(
            "DeepSeek JSON parse failed: "
            f"finish_reason={finish_reason or 'unknown'}, "
            f"raw_response_chars={len(raw)}, raw_tail={tail!r}"
        ) from exc


class OpenAIResponsesProvider:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", timeout: float = 180, client: httpx.AsyncClient | None = None):
        self.api_key, self.model, self.base_url, self.timeout, self._client = api_key, model, base_url.rstrip("/"), timeout, client

    async def generate(self, request: NodeLLMRequest) -> LLMCallResult:
        body = {"model": self.model, "input": [{"role": "system", "content": request.system_prompt}, {"role": "user", "content": _payload(request)}], "text": {"format": {"type": "json_schema", "name": request.schema_name, "schema": request.output_schema, "strict": True}}, "max_output_tokens": request.parameter_profile.max_output_tokens}
        own = self._client is None; client = self._client or httpx.AsyncClient(timeout=self.timeout); started = time.monotonic()
        try:
            response = await client.post(f"{self.base_url}/responses", json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status(); data = response.json(); raw = data.get("output_text", "")
            if not raw:
                for output in data.get("output", []):
                    for content in output.get("content", []):
                        if content.get("text"): raw = content["text"]
            usage = data.get("usage", {})
            return LLMCallResult(raw, _json_text(raw), data.get("id"), "openai", self.model, usage.get("input_tokens"), usage.get("output_tokens"), usage.get("total_tokens"), round((time.monotonic()-started)*1000), data.get("status"))
        finally:
            if own: await client.aclose()

    async def connection_test(self) -> dict[str, Any]:
        return {"ok": True, "provider": "openai", "model": self.model, "protocol": "responses"}


class DeepSeekChatProvider:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.deepseek.com", timeout: float = 180, client: httpx.AsyncClient | None = None):
        self.api_key, self.model, self.base_url, self.timeout, self._client = api_key, model, base_url.rstrip("/"), timeout, client

    async def generate(self, request: NodeLLMRequest) -> LLMCallResult:
        schema_hint = json.dumps(request.output_schema, ensure_ascii=False)
        system = f"{request.system_prompt}\nReturn only JSON matching this schema: {schema_hint}"
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": _payload(request)}], "response_format": {"type": "json_object"}, "max_tokens": request.parameter_profile.max_output_tokens}
        if request.parameter_profile.temperature is not None: body["temperature"] = request.parameter_profile.temperature
        own = self._client is None; client = self._client or httpx.AsyncClient(timeout=self.timeout); started = time.monotonic()
        try:
            response = await client.post(f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {self.api_key}"})
            _raise_for_status_with_body(response); data = response.json(); choice = data.get("choices", [{}])[0]; raw = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})
            finish_reason = choice.get("finish_reason")
            return LLMCallResult(raw, _deepseek_json(raw, finish_reason, self.api_key), data.get("id"), "deepseek", self.model, usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"), round((time.monotonic()-started)*1000), finish_reason)
        finally:
            if own: await client.aclose()

    async def connection_test(self) -> dict[str, Any]:
        return {"ok": True, "provider": "deepseek", "model": self.model, "protocol": "chat.completions"}
