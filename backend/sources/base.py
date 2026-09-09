"""Pluggable retrieval-adapter interface.

Blueprint §8 asks for domain-specific source policies (SEC/regulators for
filings, company IR for metrics, standards bodies for standards, etc).
Rather than hardcoding one search provider, every retrieval mechanism
implements this small interface and registers itself in `registry.py`, so
new scrapers/APIs can be added without touching the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class RawResult(TypedDict, total=False):
    title: str
    url: str
    body: str
    publisher: str
    published_at: str


class SourceAdapter(ABC):
    """One retrieval mechanism (a search API, a wiki API, a filings
    index, ...). Adapters are query-in/results-out and must not raise -
    they return [] on failure so one bad provider never sinks a job
    (blueprint §24)."""

    name: str = "base"
    # Adapters can self-report whether they're worth calling for a given
    # query, so the registry can route (e.g. only hit a filings adapter
    # for financial-sounding queries) - see registry.select_adapters.
    relevance_hints: tuple[str, ...] = ()

    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> list[RawResult]:
        ...
