"""The agent stages from the blueprint (sections 7, 10-18), each a plain
function over a ResearchPacket. Every stage takes an optional call_counter
dict to share the per-job LLM budget (section 30), and degrades to a
deterministic heuristic if the LLM is unavailable (section 24) rather than
failing the whole job.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.config import (
    LLMUnavailable,
    LLMCallBudgetExceeded,
    MAX_QUERIES,
    MIN_QUERIES,
    PROMPT_VERSIONS,
    call_llm_json,
)
from backend.models import (
    Claim,
    ClaimType,
    Conflict,
    ContentViews,
    Evidence,
    Importance,
    Insight,
    InsightType,
    ReportStatus,
    ResearchPacket,
    VerificationStatus,
)

ABSOLUTE_LANGUAGE = re.compile(
    r"\b(largest|biggest|first|only|dominates?|always|never|guaranteed|will\s+definitely)\b",
    re.IGNORECASE,
)


def _note(packet: ResearchPacket, stage: str, message: str) -> None:
    packet.stage_notes.append(f"[{stage}] {message}")


# ---------------------------------------------------------------------
# 1. Query Planner Agent (blueprint section 7)
# ---------------------------------------------------------------------

def plan_queries(topic: str, call_counter: dict | None = None, packet: ResearchPacket | None = None) -> list[str]:
    system = (
        "You are a research query planner. Given a topic, produce a JSON array of "
        f"{MIN_QUERIES}-{MAX_QUERIES} short web search queries covering: "
        "(1) an overview/background query, (2) a primary-source query (company filings, "
        "official announcements, regulator/standards body), (3) a quantitative query "
        "(revenue, market share, growth, funding, adoption), (4) a recent-developments query, "
        "(5) a risk/contrarian query, (6) a trend/outlook query, (7) a key-concepts/background "
        "query so a reader unfamiliar with the topic has context. Add an entity-resolution query "
        "only if the topic name is ambiguous. Return ONLY a JSON array of strings."
    )
    try:
        result = call_llm_json(system, f"Topic: {topic}", call_counter, stage="planner")
        queries = [q for q in result if isinstance(q, str) and q.strip()] if isinstance(result, list) else []
        if MIN_QUERIES <= len(queries) <= MAX_QUERIES:
            return queries[:MAX_QUERIES]
    except (LLMUnavailable, LLMCallBudgetExceeded) as exc:
        if packet:
            _note(packet, "planner", f"LLM planning unavailable, using heuristic queries ({exc})")
    except Exception as exc:  # noqa: BLE001
        if packet:
            _note(packet, "planner", f"LLM planning failed, using heuristic queries ({exc})")

    # deterministic fallback (section 24: graceful degradation)
    return [
        f"{topic} overview",
        f"{topic} official announcement OR filing",
        f"{topic} revenue growth market share",
        f"{topic} recent news",
        f"{topic} risks criticism",
        f"{topic} trends outlook",
        f"{topic} key concepts explained",
    ]


# ---------------------------------------------------------------------
# 2 & 3. Search/Fetch are in tools.py; this module picks up from Evidence.
# ---------------------------------------------------------------------


# ---------------------------------------------------------------------
# 4. Claim Extraction Agent (blueprint section 10)
# ---------------------------------------------------------------------

def extract_claims(packet: ResearchPacket, call_counter: dict | None = None, max_evidence: int = 30) -> None:
    if not packet.evidence:
        _note(packet, "extractor", "no evidence available, skipping extraction")
        return

    evidence_batch = packet.evidence[:max_evidence]
    system = (
        "You extract atomic, checkable claims from evidence passages. One claim = one checkable "
        "proposition (e.g. split 'X is growing and dominates' into a growth claim and a market-share "
        "claim). For each claim return: text, claim_type (FACT|METRIC|EVENT|OPINION|FORECAST), "
        "importance (HIGH|MEDIUM|LOW), metric (string or null), date (string or null), "
        "evidence_ids (array of the passage ids that support it), extraction_confidence (0-1). "
        "Return ONLY a JSON array of these objects."
    )
    passages_text = "\n".join(f"[{e.id}] {e.passage[:500]}" for e in evidence_batch)
    try:
        result = call_llm_json(system, passages_text, call_counter, stage="extractor")
        valid_ids = {e.id for e in evidence_batch}
        added = 0
        for item in result if isinstance(result, list) else []:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            ev_ids = [i for i in item.get("evidence_ids", []) if i in valid_ids]
            if not ev_ids:
                continue  # never accept a claim with no valid evidence reference
            packet.claims.append(Claim(
                text=item["text"],
                claim_type=_safe_enum(ClaimType, item.get("claim_type"), ClaimType.FACT),
                importance=_safe_enum(Importance, item.get("importance"), Importance.MEDIUM),
                metric=item.get("metric"),
                date=item.get("date"),
                evidence_ids=ev_ids,
                extraction_confidence=float(item.get("extraction_confidence", 0.5)),
            ))
            added += 1
        _note(packet, "extractor", f"extracted {added} claims from {len(evidence_batch)} passages")
    except (LLMUnavailable, LLMCallBudgetExceeded) as exc:
        _note(packet, "extractor", f"LLM extraction unavailable ({exc}); falling back to heuristic extraction")
        _heuristic_extract(packet, evidence_batch)
    except Exception as exc:  # noqa: BLE001
        _note(packet, "extractor", f"LLM extraction failed ({exc}); falling back to heuristic extraction")
        _heuristic_extract(packet, evidence_batch)


_NUMBER_SENTENCE = re.compile(r"([^.]*\d[%$][^.]*\.|[^.]*\$\s?\d[\d,\.]*\s?(?:billion|million|B|M)[^.]*\.)", re.IGNORECASE)


_METRIC_KEYWORDS = ("revenue", "profit", "market share", "funding", "growth", "share", "valuation", "spend")


def _guess_metric_label(sentence: str) -> str | None:
    lower = sentence.lower()
    for kw in _METRIC_KEYWORDS:
        if kw in lower:
            return kw
    return None


def _heuristic_extract(packet: ResearchPacket, evidence_batch: list[Evidence]) -> None:
    """Deterministic fallback: pull sentences that contain a number/currency
    sign as METRIC claims. Coarse, but keeps the pipeline usable with no LLM."""
    added = 0
    for ev in evidence_batch:
        for match in _NUMBER_SENTENCE.findall(ev.passage):
            text = match.strip()
            if len(text) < 15:
                continue
            packet.claims.append(Claim(
                text=text,
                claim_type=ClaimType.METRIC,
                importance=Importance.MEDIUM,
                metric=_guess_metric_label(text),
                evidence_ids=[ev.id],
                extraction_confidence=0.3,
            ))
            added += 1
            if added >= 20:
                return


def _safe_enum(enum_cls, value, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------
# 5. Verification Agent (blueprint section 11)
# ---------------------------------------------------------------------

def verify_claims(packet: ResearchPacket, call_counter: dict | None = None, batch_size: int = 15) -> None:
    if not packet.claims:
        return
    evidence_by_id = {e.id: e for e in packet.evidence}

    for start in range(0, len(packet.claims), batch_size):
        batch = packet.claims[start:start + batch_size]
        payload = []
        for c in batch:
            evidence_texts = [evidence_by_id[eid].passage[:400] for eid in c.evidence_ids if eid in evidence_by_id]
            payload.append({"claim_id": c.id, "claim": c.text, "evidence": evidence_texts})

        system = (
            "You verify claims against their cited evidence. For each item, decide whether the "
            "evidence supports the claim's exact wording - not just similar words. Return status as one of "
            "SUPPORTS, PARTIAL, CONTRADICTS, INSUFFICIENT, OUTDATED, UNVERIFIED. Return ONLY a JSON array "
            "of {claim_id, status, verification_confidence (0-1), notes}."
        )
        try:
            import json as _json
            result = call_llm_json(system, _json.dumps(payload), call_counter, stage="verifier")
            by_id = {c.id: c for c in batch}
            for item in result if isinstance(result, list) else []:
                claim = by_id.get(item.get("claim_id"))
                if not claim:
                    continue
                claim.status = _safe_enum(VerificationStatus, item.get("status"), VerificationStatus.UNVERIFIED)
                claim.verification_confidence = float(item.get("verification_confidence", 0.5))
                claim.verification_notes = item.get("notes")
        except (LLMUnavailable, LLMCallBudgetExceeded) as exc:
            _note(packet, "verifier", f"LLM verification unavailable for batch ({exc}); using heuristic")
            _heuristic_verify(batch, evidence_by_id)
        except Exception as exc:  # noqa: BLE001
            _note(packet, "verifier", f"LLM verification failed for batch ({exc}); using heuristic")
            _heuristic_verify(batch, evidence_by_id)


def _heuristic_verify(claims: list[Claim], evidence_by_id: dict[str, Evidence]) -> None:
    """Deterministic fallback: SUPPORTS if a meaningful word overlap exists
    between claim text and its cited evidence, else INSUFFICIENT."""
    for c in claims:
        evidence_texts = " ".join(evidence_by_id[eid].passage.lower() for eid in c.evidence_ids if eid in evidence_by_id)
        claim_words = {w for w in re.findall(r"[a-z0-9]+", c.text.lower()) if len(w) > 3}
        overlap = sum(1 for w in claim_words if w in evidence_texts)
        ratio = overlap / max(len(claim_words), 1)
        if ratio > 0.5:
            c.status = VerificationStatus.SUPPORTS
            c.verification_confidence = min(0.6, ratio)
        elif ratio > 0.2:
            c.status = VerificationStatus.PARTIAL
            c.verification_confidence = ratio
        else:
            c.status = VerificationStatus.INSUFFICIENT
            c.verification_confidence = ratio
        c.verification_notes = "heuristic word-overlap check (no LLM available)"


# ---------------------------------------------------------------------
# 6. Factual Check Agent - adversarial pass (blueprint section 12)
# ---------------------------------------------------------------------

def fact_check(packet: ResearchPacket, call_counter: dict | None = None) -> None:
    flags: list[str] = []
    for claim in packet.claims:
        if ABSOLUTE_LANGUAGE.search(claim.text):
            flags.append(f"Absolute language in claim {claim.id!r}: {claim.text[:80]}")
            if claim.status == VerificationStatus.SUPPORTS and (claim.verification_confidence or 0) < 0.8:
                claim.status = VerificationStatus.PARTIAL
        if claim.claim_type == ClaimType.METRIC and not claim.date:
            flags.append(f"Metric claim without a date (possible temporal mismatch): {claim.id!r}")
        if not claim.evidence_ids:
            flags.append(f"Claim {claim.id!r} has no evidence reference")

    if packet.content is None:
        packet.content = ContentViews()
    packet.content.flags = flags
    _note(packet, "fact_checker", f"raised {len(flags)} flags across {len(packet.claims)} claims")


# ---------------------------------------------------------------------
# 7. Conflict Resolution Agent (blueprint section 13)
# ---------------------------------------------------------------------

def resolve_conflicts(packet: ResearchPacket) -> None:
    """Heuristic: group METRIC claims by normalized metric name; if two
    claims share a metric but disagree on the stated value/date, record an
    explicit, unresolved Conflict rather than picking or averaging one."""
    by_metric: dict[str, list[Claim]] = {}
    for c in packet.claims:
        if c.claim_type != ClaimType.METRIC or not c.metric:
            continue
        key = c.metric.strip().lower()
        by_metric.setdefault(key, []).append(c)

    for metric, claims in by_metric.items():
        if len(claims) < 2:
            continue
        distinct_texts = {c.text.strip().lower() for c in claims}
        if len(distinct_texts) > 1:
            packet.conflicts.append(Conflict(
                claim_ids=[c.id for c in claims],
                description=(
                    f"Multiple sources report different values for '{metric}'. "
                    "Preserving both rather than averaging or silently picking one."
                ),
                resolved=False,
            ))
    _note(packet, "conflict_resolver", f"found {len(packet.conflicts)} unresolved conflicts")


# ---------------------------------------------------------------------
# 8. Research Synthesizer (blueprint section 14)
# ---------------------------------------------------------------------

def synthesize(packet: ResearchPacket, call_counter: dict | None = None) -> None:
    verified = [c for c in packet.claims if c.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)]
    if not verified:
        packet.summary = "Insufficient verified evidence was found to produce a research summary."
        _note(packet, "synthesizer", "no verified claims available; wrote fallback summary")
        return

    system = (
        "You write a concise research narrative using ONLY the verified claims provided. "
        "Do not invent facts or add anything not present in the claims. "
        "Return JSON: {\"summary\": \"2-4 paragraph narrative\"}."
    )
    claim_lines = "\n".join(f"- ({c.status.value}) {c.text}" for c in verified[:40])
    try:
        result = call_llm_json(system, claim_lines, call_counter, stage="synthesizer")
        summary = result.get("summary") if isinstance(result, dict) else None
        if summary:
            packet.summary = summary
            return
    except (LLMUnavailable, LLMCallBudgetExceeded) as exc:
        _note(packet, "synthesizer", f"LLM synthesis unavailable ({exc}); using templated summary")
    except Exception as exc:  # noqa: BLE001
        _note(packet, "synthesizer", f"LLM synthesis failed ({exc}); using templated summary")

    packet.summary = " ".join(c.text.rstrip(".") + "." for c in verified[:8])


# ---------------------------------------------------------------------
# 9. Content Builder Agent (blueprint section 15)
# ---------------------------------------------------------------------

def build_content(packet: ResearchPacket) -> None:
    if packet.content is None:
        packet.content = ContentViews()

    verified = [c for c in packet.claims if c.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)]
    high = sorted(verified, key=lambda c: c.importance != Importance.HIGH)

    packet.content.executive_brief = [c.text for c in high[:10]]
    packet.content.timeline = [
        {"date": c.date, "text": c.text, "claim_id": c.id}
        for c in verified if c.date
    ]
    packet.content.timeline.sort(key=lambda x: x["date"] or "")
    packet.content.metrics = [
        {"metric": c.metric, "value_text": c.text, "claim_id": c.id}
        for c in verified if c.claim_type == ClaimType.METRIC
    ]
    packet.content.article_sections = [
        {"heading": "Overview", "body": packet.summary or "", "claim_ids": []},
        {"heading": "Key findings", "body": "", "claim_ids": [c.id for c in high[:10]]},
    ]
    if packet.conflicts:
        packet.content.article_sections.append({
            "heading": "Conflicting information",
            "body": "; ".join(c.description for c in packet.conflicts),
            "claim_ids": [cid for conf in packet.conflicts for cid in conf.claim_ids],
        })
    _note(packet, "content_builder", f"built {len(packet.content.executive_brief)}-item brief, "
                                      f"{len(packet.content.timeline)} timeline entries, "
                                      f"{len(packet.content.metrics)} metrics")


# ---------------------------------------------------------------------
# 10. ASK - grounded follow-up (blueprint section 18)
# ---------------------------------------------------------------------

def answer_question(packet: ResearchPacket, question: str, call_counter: dict | None = None) -> dict:
    verified = [c for c in packet.claims if c.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)]
    q_words = {w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 3}

    def score(c: Claim) -> int:
        claim_words = set(re.findall(r"[a-z0-9]+", c.text.lower()))
        return len(q_words & claim_words)

    relevant = sorted(verified, key=score, reverse=True)[:12]
    relevant = [c for c in relevant if score(c) > 0] or verified[:5]

    if not relevant:
        return {"answer": "This research packet doesn't have verified claims to answer that from.", "claim_ids": []}

    system = (
        "Answer the user's question using ONLY the provided verified claims. If the claims don't "
        "cover the question, say so explicitly rather than guessing. Return JSON: "
        "{\"answer\": \"...\", \"claim_ids\": [\"...\"]} where claim_ids are the ones you actually used."
    )
    claims_text = "\n".join(f"[{c.id}] {c.text}" for c in relevant)
    try:
        import json as _json
        result = call_llm_json(
            system,
            _json.dumps({"question": question, "claims": claims_text}),
            call_counter,
            stage="ask",
        )
        if isinstance(result, dict) and result.get("answer"):
            valid_ids = {c.id for c in relevant}
            return {
                "answer": result["answer"],
                "claim_ids": [cid for cid in result.get("claim_ids", []) if cid in valid_ids],
            }
    except Exception:  # noqa: BLE001 - degrade to keyword-relevant claims below
        pass

    return {
        "answer": " ".join(c.text.rstrip(".") + "." for c in relevant[:3]),
        "claim_ids": [c.id for c in relevant[:3]],
    }


# ---------------------------------------------------------------------
# 11. Scenario Engine (blueprint sections 16-17)
# ---------------------------------------------------------------------

def generate_scenario(packet: ResearchPacket, assumptions: list[str] | None, call_counter: dict | None = None) -> dict:
    verified = [c for c in packet.claims if c.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)]
    if not verified:
        return {
            "facts": [], "drivers": [], "assumptions": assumptions or [], "branches": [],
            "note": "No verified facts available to ground a scenario.",
        }

    system = (
        "You build a structured, CONDITIONAL scenario exploration from verified facts - never a "
        "prediction. Model: facts -> drivers -> assumptions -> branches (3-5) -> outcomes -> indicators. "
        "Use conditional language ('if X, then one possible path is...'). Avoid probabilities unless a "
        "defensible quantitative basis exists in the facts. Return JSON: {\"facts\": [...], "
        "\"drivers\": [...], \"assumptions\": [...], \"branches\": [{\"name\":..., \"assumption\":..., "
        "\"outcome\":..., \"indicators\": [...]}]}."
    )
    payload = {"topic": packet.topic, "facts": [c.text for c in verified[:25]], "user_assumptions": assumptions or []}
    try:
        import json as _json
        result = call_llm_json(system, _json.dumps(payload), call_counter, stage="scenario")
        if isinstance(result, dict) and result.get("branches"):
            return result
    except Exception:  # noqa: BLE001
        pass

    return {
        "facts": [c.text for c in verified[:10]],
        "drivers": ["(LLM unavailable - drivers not generated)"],
        "assumptions": assumptions or ["(none supplied)"],
        "branches": [{
            "name": "Baseline continuation",
            "assumption": "Current verified trends continue without a major shift.",
            "outcome": "Not generated - connect an LLM provider for scenario branches.",
            "indicators": [],
        }],
    }


# ---------------------------------------------------------------------
# 12. Insight Agent - elaborated trends/concepts/comparisons (extends
# sections 10-14 beyond atomic claims: still fully cited, just longer-
# form context a reader needs to understand *why* a claim matters).
# ---------------------------------------------------------------------

def generate_insights(packet: ResearchPacket, call_counter: dict | None = None, max_evidence: int = 25) -> None:
    verified_evidence_ids = {eid for c in packet.claims
                              if c.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)
                              for eid in c.evidence_ids}
    evidence_pool = [e for e in packet.evidence if e.id in verified_evidence_ids] or packet.evidence[:max_evidence]
    if not evidence_pool:
        _note(packet, "insights", "no evidence available, skipping insight generation")
        return

    system = (
        "You write elaborated research context from evidence passages: TRENDs (a directional pattern "
        "over time), CONCEPTs (background needed to understand the topic), and COMPARISONs (how the "
        "topic relates to a competitor/alternative/benchmark). Each insight must be 2-4 sentences, "
        "grounded ONLY in the given passages - do not add outside knowledge. Return a JSON array of "
        "{type: TREND|CONCEPT|COMPARISON, title, body, evidence_ids}."
    )
    passages_text = "\n".join(f"[{e.id}] {e.passage[:500]}" for e in evidence_pool[:max_evidence])
    try:
        result = call_llm_json(system, passages_text, call_counter, stage="insights")
        valid_ids = {e.id for e in evidence_pool}
        added = 0
        for item in result if isinstance(result, list) else []:
            if not isinstance(item, dict) or not item.get("title") or not item.get("body"):
                continue
            ev_ids = [i for i in item.get("evidence_ids", []) if i in valid_ids]
            if not ev_ids:
                continue  # no unsourced insights
            packet.insights.append(Insight(
                type=_safe_enum(InsightType, item.get("type"), InsightType.CONCEPT),
                title=item["title"],
                body=item["body"],
                evidence_ids=ev_ids,
                source_ids=_source_ids_for_evidence(packet, ev_ids),
            ))
            added += 1
        _note(packet, "insights", f"generated {added} insights from {len(evidence_pool)} passages")
    except (LLMUnavailable, LLMCallBudgetExceeded) as exc:
        _note(packet, "insights", f"LLM insight generation unavailable ({exc}); using heuristic grouping")
        _heuristic_insights(packet, evidence_pool)
    except Exception as exc:  # noqa: BLE001
        _note(packet, "insights", f"LLM insight generation failed ({exc}); using heuristic grouping")
        _heuristic_insights(packet, evidence_pool)


def _source_ids_for_evidence(packet: ResearchPacket, evidence_ids: list[str]) -> list[str]:
    evidence_by_id = {e.id: e for e in packet.evidence}
    seen: list[str] = []
    for eid in evidence_ids:
        ev = evidence_by_id.get(eid)
        if ev and ev.source_id not in seen:
            seen.append(ev.source_id)
    return seen


def _heuristic_insights(packet: ResearchPacket, evidence_pool: list[Evidence]) -> None:
    """Deterministic fallback: turn the 3 longest verified evidence
    passages into CONCEPT insights, still fully cited, just without LLM
    elaboration/synthesis across passages."""
    longest = sorted(evidence_pool, key=lambda e: len(e.passage), reverse=True)[:3]
    for ev in longest:
        title = ev.passage[:60].rsplit(" ", 1)[0] if " " in ev.passage[:60] else ev.passage[:60]
        packet.insights.append(Insight(
            type=InsightType.CONCEPT,
            title=title + "...",
            body=ev.passage[:400],
            evidence_ids=[ev.id],
            source_ids=_source_ids_for_evidence(packet, [ev.id]),
            confidence=0.3,
        ))
