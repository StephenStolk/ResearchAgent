"""Search & Source Collection (section 8) and Fetch & Evidence Extraction
(section 9). Search is treated strictly as a retrieval tool: results are
stored with metadata and scored, never treated as final evidence on their
own (that's what fetch + passage extraction is for).
"""

from __future__ import annotations

import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from duckduckgo_search import DDGS

from backend.cache import cache_get, cache_set
from backend.config import (
    FETCH_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    PASSAGE_CHUNK_CHARS,
    PAGE_CACHE_TTL,
    SEARCH_CACHE_TTL,
    PIPELINE_VERSION,
)
from backend.models import Source, SourceTier, canonicalize_url, content_hash

# --- Source tiering (blueprint section 8: domain-specific source policies) ---
TIER1_DOMAINS = (
    "sec.gov", ".gov", "federalreserve.gov", "europa.eu", "who.int",
    "iso.org", "ietf.org", "w3.org",
)
TIER1_SUFFIXES = ("investor.com", "ir.")  # heuristic: investor-relations subdomains
TIER2_DOMAINS = (
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "apnews.com",
    "nytimes.com", "economist.com", "cnbc.com", "techcrunch.com",
)
TIER3_HINT_DOMAINS = ("reddit.com", "medium.com", "quora.com", "x.com", "twitter.com", "facebook.com")


def score_tier(url: str) -> tuple[SourceTier, float]:
    host = urlparse(url).netloc.lower()
    if any(host.endswith(d) or d in host for d in TIER1_DOMAINS) or any(s in host for s in TIER1_SUFFIXES):
        return SourceTier.PRIMARY, 0.95
    if any(host.endswith(d) for d in TIER2_DOMAINS):
        return SourceTier.SECONDARY, 0.75
    if any(d in host for d in TIER3_HINT_DOMAINS):
        return SourceTier.AGGREGATOR, 0.3
    return SourceTier.SECONDARY, 0.5


def search_web(query: str, max_results: int = 8) -> list[dict]:
    """Run one query, with a short cache and one retry on failure."""
    cached = cache_get("search", query, {"max_results": max_results, "v": PIPELINE_VERSION})
    if cached is not None:
        return cached

    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            results = DDGS().text(query, max_results=max_results) or []
            cache_set("search", query, results, {"max_results": max_results, "v": PIPELINE_VERSION}, SEARCH_CACHE_TTL)
            return results
        except Exception as exc:  # noqa: BLE001 - provider failure, degrade per section 24
            last_error = exc
            time.sleep(0.5)
    print(f"[search] query failed after retry: {query!r} ({last_error})")
    return []


def results_to_sources(results: list[dict]) -> list[Source]:
    sources = []
    for item in results:
        url = item.get("href") or item.get("url")
        if not url:
            continue
        tier, authority = score_tier(url)
        src = Source(
            url=url,
            canonical_url=canonicalize_url(url),
            title=item.get("title"),
            publisher=item.get("publisher") or urlparse(url).netloc,
            tier=tier,
            authority_score=authority,
        )
        sources.append(src)
    return sources


_TAG_RE = re.compile(r"<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")


def _extract_text(html: str) -> str:
    """Lightweight HTML-to-text extraction: strip script/style/nav/footer
    blocks, then all remaining tags. Deliberately dependency-light; a
    production build would swap this for trafilatura/readability."""
    cleaned = _TAG_RE.sub(" ", html)
    cleaned = _ANY_TAG_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    cleaned = _BLANKLINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def fetch_page(url: str) -> Optional[str]:
    """Fetch and extract text for one URL. SSRF-conscious: http/https only,
    size-capped, timeout-bounded (blueprint section 27)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None

    cached = cache_get("page", url, {"v": PIPELINE_VERSION})
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": "ResearchAgent/0.1 (+evidence-extraction)"},
            stream=True,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return None

        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                break
            chunks.append(chunk)
        raw = b"".join(chunks).decode(resp.encoding or "utf-8", errors="ignore")
        text = _extract_text(raw)
        cache_set("page", url, text, {"v": PIPELINE_VERSION}, PAGE_CACHE_TTL)
        return text
    except requests.RequestException as exc:
        print(f"[fetch] failed for {url}: {exc}")
        return None


def chunk_passages(text: str, chunk_chars: int = PASSAGE_CHUNK_CHARS) -> list[str]:
    """Chunk on paragraph boundaries where possible, falling back to a
    hard split so no passage exceeds chunk_chars * 1.5."""
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip() and len(p.strip()) > 40]
    passages: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) <= chunk_chars:
            buffer = f"{buffer} {para}".strip()
        else:
            if buffer:
                passages.append(buffer)
            buffer = para
    if buffer:
        passages.append(buffer)

    # Hard-split any passage that's still too long (e.g. one giant paragraph)
    final: list[str] = []
    for p in passages:
        if len(p) <= chunk_chars * 1.5:
            final.append(p)
        else:
            for i in range(0, len(p), chunk_chars):
                final.append(p[i:i + chunk_chars])
    return final[:40]  # cap passages per page to bound downstream token usage
