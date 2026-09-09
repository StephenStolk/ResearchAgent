from backend.charts import (
    build_all_charts,
    build_bar_chart,
    build_correlation_chart,
    build_line_chart,
    build_pie_chart,
    populate_metric_values,
)
from backend.models import Claim, ClaimType, Importance, ResearchPacket, VerificationStatus
from backend.numeric import parse_metric_value


def test_parse_metric_value_currency_with_scale():
    value, unit = parse_metric_value("Acme reported revenue of $4.2 billion in Q1")
    assert value == 4.2e9
    assert unit == "USD"


def test_parse_metric_value_percent():
    value, unit = parse_metric_value("Market share reached 23.5%")
    assert value == 23.5
    assert unit == "%"


def test_parse_metric_value_returns_none_when_no_number():
    value, unit = parse_metric_value("The company grew significantly")
    assert value is None and unit is None


def _verified_metric_claim(text, metric, date=None, importance=Importance.HIGH):
    return Claim(
        text=text,
        claim_type=ClaimType.METRIC,
        metric=metric,
        date=date,
        importance=importance,
        status=VerificationStatus.SUPPORTS,
        evidence_ids=["e1"],
    )


def test_populate_metric_values_fills_only_metric_claims():
    packet = ResearchPacket(topic="Acme")
    packet.claims.append(_verified_metric_claim("Revenue was $4.2 billion", "revenue"))
    packet.claims.append(Claim(text="Acme makes staplers", claim_type=ClaimType.FACT))
    populate_metric_values(packet)
    assert packet.claims[0].metric_value == 4.2e9
    assert packet.claims[1].metric_value is None


def test_build_bar_chart_needs_at_least_two_numeric_claims():
    packet = ResearchPacket(topic="Acme")
    packet.claims.append(_verified_metric_claim("Revenue was $4.2 billion", "revenue"))
    populate_metric_values(packet)
    assert build_bar_chart(packet) is None  # only one numeric claim

    packet.claims.append(_verified_metric_claim("Profit was $1.1 billion", "profit"))
    populate_metric_values(packet)
    chart = build_bar_chart(packet)
    assert chart is not None
    assert chart.chart_type == "bar"
    assert len(chart.series[0].values) == 2
    assert chart.claim_ids


def test_build_line_chart_requires_three_dated_points_same_metric():
    packet = ResearchPacket(topic="Acme")
    packet.claims.append(_verified_metric_claim("Revenue was $4.0B", "revenue", date="2025-01-01"))
    packet.claims.append(_verified_metric_claim("Revenue was $4.5B", "revenue", date="2025-04-01"))
    populate_metric_values(packet)
    assert build_line_chart(packet) is None  # only 2 points

    packet.claims.append(_verified_metric_claim("Revenue was $5.0B", "revenue", date="2025-07-01"))
    populate_metric_values(packet)
    chart = build_line_chart(packet)
    assert chart is not None
    assert chart.x_labels == ["2025-01-01", "2025-04-01", "2025-07-01"]


def test_build_pie_chart_requires_percent_claims():
    packet = ResearchPacket(topic="Acme")
    packet.claims.append(_verified_metric_claim("Segment A holds 40%", "segment_a_share"))
    populate_metric_values(packet)
    assert build_pie_chart(packet) is None

    packet.claims.append(_verified_metric_claim("Segment B holds 35%", "segment_b_share"))
    populate_metric_values(packet)
    chart = build_pie_chart(packet)
    assert chart is not None
    assert chart.chart_type == "pie"


def test_build_correlation_chart_computes_pearson_r():
    packet = ResearchPacket(topic="Acme")
    dates = ["2025-01-01", "2025-04-01", "2025-07-01"]
    revenue_vals = ["$4.0B", "$5.0B", "$6.0B"]
    marketing_vals = ["$1.0B", "$1.25B", "$1.5B"]
    for d, r, m in zip(dates, revenue_vals, marketing_vals):
        packet.claims.append(_verified_metric_claim(f"Revenue was {r}", "revenue", date=d))
        packet.claims.append(_verified_metric_claim(f"Marketing spend was {m}", "marketing spend", date=d))

    populate_metric_values(packet)
    chart = build_correlation_chart(packet)
    assert chart is not None
    assert chart.chart_type == "correlation"
    assert "Pearson r" in chart.note
    # perfectly correlated linear series -> r should be very close to 1
    assert "1.0" in chart.note or "0.99" in chart.note or "1.00" in chart.note


def test_build_all_charts_never_invents_claim_or_source_ids():
    packet = ResearchPacket(topic="Acme")
    dates = ["2025-01-01", "2025-04-01", "2025-07-01"]
    for d, v in zip(dates, ["$4.0B", "$5.0B", "$6.0B"]):
        packet.claims.append(_verified_metric_claim(f"Revenue was {v}", "revenue", date=d))
    build_all_charts(packet)

    all_claim_ids = {c.id for c in packet.claims}
    for chart in packet.charts:
        assert set(chart.claim_ids).issubset(all_claim_ids)
