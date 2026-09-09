"""Orchestrates the full research pipeline end to end (blueprint section 40):

Search -> Fetch -> Evidence -> Claims -> Verification -> Fact Check ->
Conflict Resolution -> Canonical Research Packet -> Content Views.

Each stage is wrapped so a single stage failing doesn't crash the whole
job (section 24: graceful degradation) - the packet just carries a note
and a lower report status (section 25: quality gates).
"""

from __future__ import annotations

import time
from pathlib import Path

from backend import agents
from backend.cache import cache_get, cache_set
from backend.charts import build_all_charts
from backend.config import MAX_SOURCES_TO_FETCH, PIPELINE_VERSION
from backend.models import Evidence, ReportStatus, ResearchPacket
from backend.sources.registry import select_adapters
from backend.tools import chunk_passages, fetch_page, results_to_sources

JOB_CACHE_TTL = 60 * 60 * 24 * 3  # 3 days


def _time_stage(packet: ResearchPacket, name: str, fn) -> None:
    start = time.time()
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - never let one stage kill the job
        packet.stage_notes.append(f"[{name}] stage failed entirely: {exc}")
    packet.stage_timings_ms[name] = int((time.time() - start) * 1000)


def _collect_sources(packet: ResearchPacket, queries: list[str]) -> None:
    """Modular, multi-adapter retrieval (blueprint §8): each query is
    routed to every relevant adapter (general web + domain-specific ones
    like Wikipedia/SEC EDGAR when the query matches), and every adapter
    is independently fault-tolerant, so one provider going down never
    blocks the others."""
    adapters_used = set()
    for query in queries:
        for adapter in select_adapters(query):
            adapters_used.add(adapter.name)
            results = adapter.search(query)
            for source in results_to_sources(results):
                packet.add_source(source)
    packet.stage_notes.append(
        f"[retriever] collected {len(packet.sources)} unique sources from {len(queries)} queries "
        f"via adapters: {', '.join(sorted(adapters_used)) or 'none'}"
    )


def _fetch_evidence(packet: ResearchPacket) -> None:
    # Highest-authority sources first, capped by budget (section 23: performance)
    ranked = sorted(packet.sources, key=lambda s: s.authority_score, reverse=True)
    fetched = 0
    for source in ranked:
        if fetched >= MAX_SOURCES_TO_FETCH:
            break
        text = fetch_page(source.url)
        if not text:
            continue
        fetched += 1
        for passage in chunk_passages(text):
            packet.evidence.append(Evidence(source_id=source.id, passage=passage))
    packet.stage_notes.append(f"[fetcher] fetched {fetched}/{len(ranked)} sources, {len(packet.evidence)} passages")


def _apply_quality_gates(packet: ResearchPacket) -> None:
    """Blueprint section 25: don't publish a report just because the LLM
    produced valid JSON."""
    coverage = packet.claim_coverage()
    verified_count = sum(1 for c in packet.claims if c.status.value == "SUPPORTS")
    total_claims = len(packet.claims)
    verification_rate = (verified_count / total_claims) if total_claims else 0.0
    unresolved_conflicts = sum(1 for c in packet.conflicts if not c.resolved)

    if not packet.evidence or not packet.claims:
        packet.status = ReportStatus.NEEDS_REVIEW
    elif coverage >= 0.7 and verification_rate >= 0.4 and unresolved_conflicts == 0:
        packet.status = ReportStatus.VERIFIED
    elif coverage >= 0.3 or verification_rate >= 0.2:
        packet.status = ReportStatus.PARTIAL
    else:
        packet.status = ReportStatus.NEEDS_REVIEW

    packet.stage_notes.append(
        f"[quality_gate] coverage={coverage:.2f} verification_rate={verification_rate:.2f} "
        f"unresolved_conflicts={unresolved_conflicts} -> status={packet.status.value}"
    )


def run_research(topic: str) -> ResearchPacket:
    packet = ResearchPacket(topic=topic)
    call_counter = {"count": 0}

    queries: list[str] = []
    _time_stage(packet, "planner", lambda: queries.extend(agents.plan_queries(topic, call_counter, packet)))
    _time_stage(packet, "retriever", lambda: _collect_sources(packet, queries))
    _time_stage(packet, "fetcher", lambda: _fetch_evidence(packet))
    _time_stage(packet, "extractor", lambda: agents.extract_claims(packet, call_counter))
    _time_stage(packet, "verifier", lambda: agents.verify_claims(packet, call_counter))
    _time_stage(packet, "fact_checker", lambda: agents.fact_check(packet, call_counter))
    _time_stage(packet, "conflict_resolver", lambda: agents.resolve_conflicts(packet))
    _time_stage(packet, "insights", lambda: agents.generate_insights(packet, call_counter))
    _time_stage(packet, "synthesizer", lambda: agents.synthesize(packet, call_counter))
    _time_stage(packet, "content_builder", lambda: agents.build_content(packet))
    _time_stage(packet, "chart_builder", lambda: build_all_charts(packet))
    _apply_quality_gates(packet)

    save_job(packet)
    return packet


# --- job store (section 21: API design around a job_id) -----------------

def save_job(packet: ResearchPacket) -> None:
    cache_set("jobs", packet.job_id, packet.model_dump(mode="json"), {"v": PIPELINE_VERSION}, JOB_CACHE_TTL)


def load_job(job_id: str) -> ResearchPacket | None:
    data = cache_get("jobs", job_id, {"v": PIPELINE_VERSION})
    if data is None:
        return None
    return ResearchPacket.model_validate(data)
