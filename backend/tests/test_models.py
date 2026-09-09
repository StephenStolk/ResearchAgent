from backend.models import (
    Claim,
    ClaimType,
    Evidence,
    Importance,
    ResearchPacket,
    Source,
    canonicalize_url,
)


def test_canonicalize_url_strips_tracking_params_and_trailing_slash():
    a = canonicalize_url("https://Example.com/Article/?utm_source=x&id=5")
    b = canonicalize_url("https://example.com/Article?id=5")
    assert a == b


def test_add_source_dedupes_by_canonical_url():
    packet = ResearchPacket(topic="NVIDIA finances")
    s1 = Source.from_search_result("https://example.com/a?utm_source=x", title="A")
    s2 = Source.from_search_result("https://example.com/a", title="A (mirror)")

    packet.add_source(s1)
    stored = packet.add_source(s2)

    assert len(packet.sources) == 1
    assert stored.id == s1.id


def test_claim_coverage_only_counts_high_importance_claims():
    packet = ResearchPacket(topic="Test")
    src = packet.add_source(Source.from_search_result("https://example.com/x"))
    ev = Evidence(source_id=src.id, passage="Revenue was $10B.")
    packet.evidence.append(ev)

    covered = Claim(
        text="Revenue was $10B",
        claim_type=ClaimType.METRIC,
        importance=Importance.HIGH,
        evidence_ids=[ev.id],
    )
    uncovered = Claim(
        text="The company is well known",
        importance=Importance.LOW,
    )
    packet.claims.extend([covered, uncovered])

    assert packet.claim_coverage() == 1.0

    packet.claims.append(Claim(text="Unsupported high-importance claim", importance=Importance.HIGH))
    assert 0 < packet.claim_coverage() < 1.0
