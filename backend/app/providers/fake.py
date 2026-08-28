import json
from collections.abc import Iterable

from .base import (
    LLMCallResult,
    NodeLLMRequest,
    SearchBatch,
    SearchRequest,
)


class FakeLLMProvider:
    def __init__(self, responses: Iterable[dict] | None = None, model: str = "fake-model"):
        self.responses = list(responses or [])
        self.model = model
        self.requests: list[NodeLLMRequest] = []

    async def generate(self, request: NodeLLMRequest) -> LLMCallResult:
        self.requests.append(request)
        value = self.responses.pop(0) if self.responses else {}
        return LLMCallResult(json.dumps(value, ensure_ascii=False), value, provider_request_id=f"fake-{len(self.requests)}", provider="fake", model=self.model)

    async def connection_test(self) -> dict:
        return {"ok": True, "provider": "fake", "model": self.model, "protocol": "fake"}


class FakeSearchProvider:
    def __init__(self, batches: Iterable[SearchBatch] | None = None):
        self.batches = list(batches or [])
        self.requests: list[SearchRequest] = []

    async def search(self, request: SearchRequest) -> SearchBatch:
        self.requests.append(request)
        return self.batches.pop(0) if self.batches else SearchBatch()

    async def connection_test(self) -> dict:
        return {"ok": True, "provider": "fake", "protocol": "search"}
