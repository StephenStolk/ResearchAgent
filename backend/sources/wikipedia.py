from __future__ import annotations

import requests

from backend.cache import cache_get, cache_set
from backend.config import FETCH_TIMEOUT_SECONDS, PIPELINE_VERSION, SEARCH_CACHE_TTL
from backend.sources.base import RawResult, SourceAdapter

WIKI_API = "https://en.wikipedia.org/w/api.php"


class WikipediaAdapter(SourceAdapter):
    """Background/concept/definition retrieval. Wikipedia is tier-2 (a
    tertiary source) but is excellent for the 'what is this concept'
    grounding an overview query needs, and for entity disambiguation
    (blueprint §7's optional entity-resolution queries)."""

    name = "wikipedia"
    relevance_hints = ("overview", "concept", "what is", "background", "definition", "history of")

    def search(self, query: str, max_results: int = 5) -> list[RawResult]:
        cached = cache_get("search:wiki", query, {"max_results": max_results, "v": PIPELINE_VERSION})
        if cached is not None:
            return cached
        try:
            resp = requests.get(
                WIKI_API,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": max_results,
                    "format": "json",
                },
                timeout=FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": "ResearchAgent/0.1"},
            )
            resp.raise_for_status()
            data = resp.json()
            results: list[RawResult] = []
            for item in data.get("query", {}).get("search", []):
                title = item.get("title", "")
                results.append({
                    "title": title,
                    "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    "body": _strip_html(item.get("snippet", "")),
                    "publisher": "Wikipedia",
                })
            cache_set("search:wiki", query, results, {"max_results": max_results, "v": PIPELINE_VERSION}, SEARCH_CACHE_TTL)
            return results
        except requests.RequestException as exc:
            print(f"[wikipedia] query failed: {query!r} ({exc})")
            return []


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text)
