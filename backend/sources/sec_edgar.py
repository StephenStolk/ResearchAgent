from __future__ import annotations

import requests

from backend.cache import cache_get, cache_set
from backend.config import FETCH_TIMEOUT_SECONDS, PIPELINE_VERSION, SEARCH_CACHE_TTL
from backend.sources.base import RawResult, SourceAdapter

EDGAR_FTS_API = "https://efts.sec.gov/LATEST/search-index?q={q}&forms=10-K,10-Q,8-K"


class SecEdgarAdapter(SourceAdapter):
    """Primary-source retrieval for company filings (blueprint §8: 'domain-
    specific source policies... SEC/regulators for filings'). No API key
    required; SEC's full-text search is free and public."""

    name = "sec_edgar"
    relevance_hints = ("revenue", "filing", "10-k", "10-q", "sec", "earnings", "financial", "quarter")

    def search(self, query: str, max_results: int = 5) -> list[RawResult]:
        cached = cache_get("search:edgar", query, {"max_results": max_results, "v": PIPELINE_VERSION})
        if cached is not None:
            return cached
        try:
            resp = requests.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": query, "forms": "10-K,10-Q,8-K"},
                timeout=FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": "ResearchAgent research@example.com"},
            )
            resp.raise_for_status()
            data = resp.json()
            results: list[RawResult] = []
            for hit in data.get("hits", {}).get("hits", [])[:max_results]:
                src = hit.get("_source", {})
                cik = src.get("ciks", [""])[0] if src.get("ciks") else ""
                accession = hit.get("_id", "")
                results.append({
                    "title": f"{src.get('display_names', ['SEC filing'])[0]} - {src.get('form', '')} filing",
                    "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                    "body": src.get("root_form", ""),
                    "publisher": "SEC EDGAR",
                })
            cache_set("search:edgar", query, results, {"max_results": max_results, "v": PIPELINE_VERSION}, SEARCH_CACHE_TTL)
            return results
        except requests.RequestException as exc:
            print(f"[sec_edgar] query failed: {query!r} ({exc})")
            return []
        except (KeyError, ValueError) as exc:
            print(f"[sec_edgar] malformed response for {query!r}: {exc}")
            return []
