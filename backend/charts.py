"""Chart-builder agents. Each function inspects verified, numeric claims
already in the packet and emits a ChartSpec - never invents data. This is
deliberately heuristic/deterministic (no LLM call) so charts are cheap,
fast, and fully reproducible from the packet alone.
"""

from __future__ import annotations

import math
from collections import defaultdict

from backend.models import ChartSeries, ChartSpec, ChartType, ClaimType, ResearchPacket, VerificationStatus
from backend.numeric import parse_metric_value


def populate_metric_values(packet: ResearchPacket) -> None:
    """Parse metric_value/metric_unit onto every METRIC claim that
    doesn't have one yet. Run once, right after extraction."""
    for claim in packet.claims:
        if claim.claim_type != ClaimType.METRIC or claim.metric_value is not None:
            continue
        value, unit = parse_metric_value(claim.text)
        if value is not None:
            claim.metric_value = value
            claim.metric_unit = unit


def _verified_numeric_claims(packet: ResearchPacket):
    return [
        c for c in packet.claims
        if c.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)
        and c.claim_type == ClaimType.METRIC
        and c.metric_value is not None
    ]


def build_bar_chart(packet: ResearchPacket) -> ChartSpec | None:
    """One bar per distinct verified metric claim - good for comparing
    different metrics or the same metric across sources/entities."""
    claims = _verified_numeric_claims(packet)
    if len(claims) < 2:
        return None
    top = sorted(claims, key=lambda c: c.importance != "HIGH")[:8]
    return ChartSpec(
        chart_type=ChartType.BAR,
        title=f"Key metrics — {packet.topic}",
        x_labels=[(c.metric or c.text[:24]) for c in top],
        series=[ChartSeries(name="Value", values=[c.metric_value for c in top])],
        claim_ids=[c.id for c in top],
        source_ids=packet.source_ids_for_claims([c.id for c in top]),
        note="Units vary by metric — see labels/claim text for context.",
    )


def build_line_chart(packet: ResearchPacket) -> ChartSpec | None:
    """Time series for a metric that has 3+ dated observations."""
    claims = [c for c in _verified_numeric_claims(packet) if c.date and c.metric]
    by_metric: dict[str, list] = defaultdict(list)
    for c in claims:
        by_metric[c.metric.strip().lower()].append(c)

    best_metric, best_claims = None, []
    for metric, group in by_metric.items():
        if len(group) >= 3 and len(group) > len(best_claims):
            best_metric, best_claims = metric, group
    if not best_metric:
        return None

    best_claims.sort(key=lambda c: c.date or "")
    return ChartSpec(
        chart_type=ChartType.LINE,
        title=f"{best_metric.title()} over time",
        x_labels=[c.date for c in best_claims],
        series=[ChartSeries(name=best_metric, values=[c.metric_value for c in best_claims])],
        claim_ids=[c.id for c in best_claims],
        source_ids=packet.source_ids_for_claims([c.id for c in best_claims]),
    )


def build_pie_chart(packet: ResearchPacket) -> ChartSpec | None:
    """Proportional breakdown - only built when several claims report a
    '%'-unit metric under the same category (e.g. market share), so the
    slices are actually comparable."""
    claims = [c for c in _verified_numeric_claims(packet) if c.metric_unit == "%"]
    if len(claims) < 2:
        return None
    top = sorted(claims, key=lambda c: c.metric_value or 0, reverse=True)[:6]
    return ChartSpec(
        chart_type=ChartType.PIE,
        title=f"Share breakdown — {packet.topic}",
        x_labels=[(c.metric or c.text[:24]) for c in top],
        series=[ChartSeries(name="Share (%)", values=[c.metric_value for c in top])],
        claim_ids=[c.id for c in top],
        source_ids=packet.source_ids_for_claims([c.id for c in top]),
        note="Percentages are as individually reported and may not sum to 100.",
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return None
    return cov / denom


def build_correlation_chart(packet: ResearchPacket) -> ChartSpec | None:
    """Scatter + Pearson correlation between two distinct metrics that
    share dated observations. Correlation, not causation — the note says
    so explicitly."""
    claims = [c for c in _verified_numeric_claims(packet) if c.date and c.metric]
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    for c in claims:
        by_metric[c.metric.strip().lower()][c.date] = c.metric_value

    metrics = [m for m, series in by_metric.items() if len(series) >= 3]
    if len(metrics) < 2:
        return None

    m1, m2 = metrics[0], metrics[1]
    shared_dates = sorted(set(by_metric[m1]) & set(by_metric[m2]))
    if len(shared_dates) < 3:
        return None

    xs = [by_metric[m1][d] for d in shared_dates]
    ys = [by_metric[m2][d] for d in shared_dates]
    r = _pearson(xs, ys)
    if r is None:
        return None

    related_claims = [c for c in claims if c.metric.strip().lower() in (m1, m2) and c.date in shared_dates]
    return ChartSpec(
        chart_type=ChartType.CORRELATION,
        title=f"{m1.title()} vs {m2.title()}",
        x_labels=shared_dates,
        series=[ChartSeries(name=m1, values=xs), ChartSeries(name=m2, values=ys)],
        claim_ids=[c.id for c in related_claims],
        source_ids=packet.source_ids_for_claims([c.id for c in related_claims]),
        note=f"Pearson r = {r:.2f}. Correlation only — not evidence of causation.",
    )


def build_all_charts(packet: ResearchPacket) -> None:
    populate_metric_values(packet)
    builders = [build_bar_chart, build_line_chart, build_pie_chart, build_correlation_chart]
    for build in builders:
        chart = build(packet)
        if chart is not None:
            packet.charts.append(chart)
    packet.stage_notes.append(f"[chart_builder] built {len(packet.charts)} chart(s) from verified numeric claims")
