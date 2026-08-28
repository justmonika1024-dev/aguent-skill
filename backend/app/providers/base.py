"""Provider-independent request and result contracts."""
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ParameterProfile:
    temperature: float | None = 0.2
    max_output_tokens: int = 4000


@dataclass(frozen=True)
class NodeLLMRequest:
    node_key: str
    system_prompt: str
    user_payload: Any
    output_schema: dict[str, Any]
    schema_name: str
    parameter_profile: ParameterProfile = field(default_factory=ParameterProfile)
    request_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCallResult:
    raw_text: str
    parsed_json: dict[str, Any]
    provider_request_id: str | None = None
    provider: str = ""
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None


class LLMProvider(Protocol):
    async def generate(self, request: NodeLLMRequest) -> LLMCallResult: ...
    async def connection_test(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SearchRequest:
    query: str
    search_type: str = "auto"
    num_results: int = 5
    max_characters: int = 1500
    query_id: str | None = None


@dataclass
class SearchResult:
    url: str
    canonical_url: str
    title: str = ""
    text: str = ""
    status: str = "VALID"
    evidence_type: str = "EXTRACTED_TEXT"
    query_ids: list[str] = field(default_factory=list)


@dataclass
class SearchBatch:
    results: list[SearchResult] = field(default_factory=list)
    request_id: str | None = None
    cost_dollars: float | None = None
    search_time: str | None = None
    failures: list[dict[str, Any]] = field(default_factory=list)


class SearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> SearchBatch: ...
    async def connection_test(self) -> dict[str, Any]: ...
