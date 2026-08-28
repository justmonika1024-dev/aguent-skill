import asyncio
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .base import SearchBatch, SearchRequest, SearchResult

_TRACKING = re.compile(r"^(utm_|spm$)", re.IGNORECASE)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    host = parts.hostname.lower() if parts.hostname else parts.netloc.lower()
    netloc = host + ((f":{parts.port}") if parts.port and parts.port not in (80, 443) else "")
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, urlencode(query), ""))


class ExaSearchProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.exa.ai", timeout: float = 20, max_retries: int = 2, client: httpx.AsyncClient | None = None):
        self.api_key, self.base_url, self.timeout, self.max_retries = api_key, base_url.rstrip("/"), timeout, max_retries
        self._client = client

    async def search(self, request: SearchRequest) -> SearchBatch:
        payload = {"query": request.query, "type": request.search_type, "numResults": request.num_results, "contents": {"text": {"maxCharacters": request.max_characters}}}
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(f"{self.base_url}/search", json=payload, headers={"x-api-key": self.api_key})
                    if response.status_code in (401, 402):
                        response.raise_for_status()
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < self.max_retries:
                            await asyncio.sleep(0)
                            continue
                    response.raise_for_status()
                    body = response.json()
                    results = []
                    for item in body.get("results", []):
                        url = item.get("url", "")
                        canonical = canonicalize_url(url)
                        text = item.get("text") or ""
                        status = "VALID" if canonical and urlsplit(canonical).netloc else "INVALID_URL"
                        results.append(SearchResult(url=url, canonical_url=canonical, title=item.get("title", ""), text=text, status=status, evidence_type="EXTRACTED_TEXT" if text else "TITLE_ONLY", query_ids=[request.query_id] if request.query_id else []))
                    return SearchBatch(results=results, request_id=body.get("requestId"), cost_dollars=body.get("costDollars"), search_time=body.get("searchTime"))
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt >= self.max_retries:
                        raise
            raise RuntimeError("Exa request failed")
        finally:
            if own:
                await client.aclose()

    async def connection_test(self) -> dict[str, Any]:
        try:
            await self.search(SearchRequest("test", num_results=1))
            return {"ok": True, "provider": "exa"}
        except Exception as exc:
            return {"ok": False, "provider": "exa", "error": str(exc)}
