"""Registry of retrieval mechanisms. New scrapers/APIs (Bing, a News API,
Crunchbase, a standards-body index, ...) plug in here by subclassing
SourceAdapter and adding an instance to ALL_ADAPTERS - the pipeline never
needs to change. `select_adapters` uses each adapter's relevance_hints so,
e.g., a filings query also queries SEC EDGAR without every query paying
that cost.
"""

from __future__ import annotations

from backend.sources.base import SourceAdapter
from backend.sources.duckduckgo import DuckDuckGoAdapter
from backend.sources.sec_edgar import SecEdgarAdapter
from backend.sources.wikipedia import WikipediaAdapter

ALL_ADAPTERS: list[SourceAdapter] = [
    DuckDuckGoAdapter(),   # broad general-web coverage - always included
    WikipediaAdapter(),    # background/concept/definition grounding
    SecEdgarAdapter(),     # primary-source company filings
]


def select_adapters(query: str) -> list[SourceAdapter]:
    """DuckDuckGo always runs (broad coverage). Others opt in only when
    the query matches their relevance_hints, keeping call volume bounded
    (blueprint §30: control calls aggressively)."""
    query_lower = query.lower()
    selected = [a for a in ALL_ADAPTERS if a.name == "duckduckgo"]
    for adapter in ALL_ADAPTERS:
        if adapter.name == "duckduckgo":
            continue
        if any(hint in query_lower for hint in adapter.relevance_hints):
            selected.append(adapter)
    return selected
