from __future__ import annotations

import time

from duckduckgo_search import DDGS

from backend.cache import cache_get, cache_set
from backend.config import PIPELINE_VERSION, SEARCH_CACHE_TTL
from backend.sources.base import RawResult, SourceAdapter


class DuckDuckGoAdapter(SourceAdapter):
    """General web search - the default, broad-coverage retrieval
    mechanism. Cached and retried once (blueprint §24: provider
    failure -> retry with backoff, then degrade)."""

    name = "duckduckgo"

    def search(self, query: str, max_results: int = 8) -> list[RawResult]:
        cached = cache_get("search:ddg", query, {"max_results": max_results, "v": PIPELINE_VERSION})
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                raw = DDGS().text(query, max_results=max_results) or []
                results: list[RawResult] = [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("href") or item.get("url", ""),
                        "body": item.get("body", ""),
                    }
                    for item in raw
                    if item.get("href") or item.get("url")
                ]
                cache_set("search:ddg", query, results, {"max_results": max_results, "v": PIPELINE_VERSION}, SEARCH_CACHE_TTL)
                return results
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.5)
        print(f"[duckduckgo] query failed after retry: {query!r} ({last_error})")
        return []
