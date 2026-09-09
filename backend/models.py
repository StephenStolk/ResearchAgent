"""
Core data model for the research pipeline.

This module defines the ResearchPacket contract described in the system
blueprint (§8-14, §36): Source -> Evidence -> Claim -> ResearchPacket.
Every later stage (verification, synthesis, content building, scenario
engine, ASK) reads and writes these objects instead of passing raw prose
between agents. Keeping this as a stable, independent module means the
pipeline stages can be built and tested one at a time.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def canonicalize_url(url: str) -> str:
    """Normalize a URL for dedup purposes: lowercase host, strip
    fragment/tracking-heavy query noise, drop trailing slash."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
   
    tracking_prefixes = ("utm_", "gclid", "fbclid", "ref", "igshid")
    
    if parts.query:
        kept = [
            key_value
            for key_value in parts.query.split("&")
            if key_value and not key_value.split("=")[0].lower().startswith(tracking_prefixes)
        ]
        query = "&".join(kept)
    else:
        query = ""
        
    return urlunsplit((scheme, netloc, path, query, ""))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


class SourceTier(str, Enum):
    PRIMARY = "tier1_primary" # official filings, company IR, standards bodies
    SECONDARY = "tier2_secondary" # reputable reporting/analysis
    AGGREGATOR = "tier3_aggregator" # blogs, forums, social - discovery only


class Source(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("s"))
    url: str
    canonical_url: str
    title: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: float = Field(default_factory=time.time)
    tier: SourceTier = SourceTier.SECONDARY
    authority_score: float = 0.5   # 0-1, set by search/fetch scoring
    content_hash: Optional[str] = None  # set once the page is fetched

    @classmethod
    def from_search_result(cls, url: str, title: str | None = None, publisher: str | None = None) -> "Source":
        return cls(url=url, canonical_url=canonicalize_url(url), title=title, publisher=publisher)


class Evidence(BaseModel):
    """A located passage inside a Source. This is what a Claim actually cites - not the whole page."""
    id: str = Field(default_factory=lambda: _new_id("e"))
    source_id: str
    passage: str
    locator: Optional[str] = None  # e.g. paragraph index, char offsets
    retrieved_at: float = Field(default_factory=time.time)


class ClaimType(str, Enum):
    FACT = "FACT"
    METRIC = "METRIC"
    EVENT = "EVENT"
    OPINION = "OPINION"
    FORECAST = "FORECAST"


class Importance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VerificationStatus(str, Enum):
    SUPPORTS = "SUPPORTS"
    PARTIAL = "PARTIAL"
    CONTRADICTS = "CONTRADICTS"
    INSUFFICIENT = "INSUFFICIENT"
    OUTDATED = "OUTDATED"
    UNVERIFIED = "UNVERIFIED"


class Claim(BaseModel):
    """One atomic, checkable proposition (blueprint §10). Extraction only fills text/entities/type/importance/evidence_ids/extraction_confidence; verification fills status/verification_confidence later."""
    id: str = Field(default_factory=lambda: _new_id("c"))
    text: str
    entity_ids: list[str] = Field(default_factory=list)
    metric: Optional[str] = None
    metric_value: Optional[float] = None   # normalized numeric value, if parseable
    metric_unit: Optional[str] = None      # "USD", "%", "count", etc.
    date: Optional[str] = None
    claim_type: ClaimType = ClaimType.FACT
    importance: Importance = Importance.MEDIUM
    evidence_ids: list[str] = Field(default_factory=list)
    extraction_confidence: float = 0.5
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_confidence: Optional[float] = None
    verification_notes: Optional[str] = None


class InsightType(str, Enum):
    TREND = "TREND"
    CONCEPT = "CONCEPT"
    COMPARISON = "COMPARISON"


class Insight(BaseModel):
    """Elaborated, multi-sentence context beyond an atomic claim - a trend, background concept, or comparison. Still fully traceable: every Insight cites the evidence/sources it was built from, same as
    a Claim, so nothing here is unsourced commentary."""
    id: str = Field(default_factory=lambda: _new_id("in"))
    type: InsightType
    title: str
    body: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    SCATTER = "scatter"
    CORRELATION = "correlation"


class ChartSeries(BaseModel):
    name: str
    values: list[Optional[float]] = Field(default_factory=list)


class ChartSpec(BaseModel):
    """Chart-ready data, built only from numeric Claim values already in the packet - the chart agents never invent numbers. Every chart carries citation source_ids so the UI can render a footnote."""
    id: str = Field(default_factory=lambda: _new_id("chart"))
    chart_type: ChartType
    title: str
    x_labels: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    note: Optional[str] = None  # e.g. correlation coefficient, caveats


class Conflict(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("cf"))
    claim_ids: list[str]
    description: str
    resolved: bool = False
    resolution_notes: Optional[str] = None


class ReportStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ContentViews(BaseModel):
    """Presentation formats built from the verified packet (blueprint
    section 15). The content builder never invents facts here - every
    entry traces back to a claim already in the packet."""
    article_sections: list[dict] = Field(default_factory=list)      # [{heading, body, claim_ids}]
    executive_brief: list[str] = Field(default_factory=list)         # top 5-10 claim texts
    timeline: list[dict] = Field(default_factory=list)               # [{date, text, claim_id}]
    metrics: list[dict] = Field(default_factory=list)                # [{metric, value_text, claim_id}]
    flags: list[str] = Field(default_factory=list)                   # fact-check notes (section 12)


class PipelineVersions(BaseModel):
    """Versioning strategy from blueprint §35. Included in cache keys so
    old reports never get silently mixed with new pipeline logic."""
    pipeline_version: str = "0.1.0"
    schema_version: int = 1
    source_policy_version: int = 1


class ResearchPacket(BaseModel):
    """The canonical, stable contract between backend intelligence and
    every UI surface (blueprint §36, §40). Nothing downstream (synthesis,
    content builder, ASK, scenario engine) should read raw search/fetch
    output directly - only this object."""
    job_id: str = Field(default_factory=lambda: _new_id("job"))
    topic: str
    status: ReportStatus = ReportStatus.NEEDS_REVIEW
    created_at: float = Field(default_factory=time.time)
    versions: PipelineVersions = Field(default_factory=PipelineVersions)

    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    # populated by the synthesizer once claims are verified
    summary: Optional[str] = None
    content: Optional[ContentViews] = None

    # per-stage timing/notes for observability (section 26) and
    # graceful-degradation transparency (section 24)
    stage_notes: list[str] = Field(default_factory=list)
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)

    def add_source(self, source: Source) -> Source:
        """Dedup by canonical_url before appending; returns the stored
        (possibly pre-existing) Source."""
        for existing in self.sources:
            if existing.canonical_url == source.canonical_url:
                return existing
        self.sources.append(source)
        return source

    def high_importance_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.importance == Importance.HIGH]

    def claim_coverage(self) -> float:
        """Fraction of HIGH-importance claims that have at least one
        evidence reference - a quality gate metric (blueprint §25)."""
        high = self.high_importance_claims()
        if not high:
            return 1.0
        covered = sum(1 for c in high if c.evidence_ids)
        return covered / len(high)

    def source_ids_for_claims(self, claim_ids: list[str]) -> list[str]:
        """Trace claims -> evidence -> sources, for building citations on
        insights/charts. Order-preserving, deduped."""
        evidence_by_id = {e.id: e for e in self.evidence}
        seen: list[str] = []
        claims_by_id = {c.id: c for c in self.claims}
        for cid in claim_ids:
            claim = claims_by_id.get(cid)
            if not claim:
                continue
            for eid in claim.evidence_ids:
                ev = evidence_by_id.get(eid)
                if ev and ev.source_id not in seen:
                    seen.append(ev.source_id)
        return seen
