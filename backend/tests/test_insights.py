from unittest.mock import patch

from backend import agents
from backend.config import LLMUnavailable
from backend.models import Claim, ClaimType, Evidence, ResearchPacket, Source, VerificationStatus


def _packet_with_verified_claim(passage: str) -> ResearchPacket:
    packet = ResearchPacket(topic="Acme Corp")
    src = packet.add_source(Source.from_search_result("https://example.com/a"))
    ev = Evidence(source_id=src.id, passage=passage)
    packet.evidence.append(ev)
    packet.claims.append(Claim(
        text=passage[:50],
        claim_type=ClaimType.FACT,
        status=VerificationStatus.SUPPORTS,
        evidence_ids=[ev.id],
    ))
    return packet


def test_generate_insights_falls_back_to_heuristic_and_stays_cited():
    packet = _packet_with_verified_claim(
        "Acme Corp has pursued a multi-year strategy of expanding into cloud infrastructure, "
        "investing heavily in data center capacity across three continents to meet enterprise demand."
    )
    with patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")):
        agents.generate_insights(packet)

    assert len(packet.insights) >= 1
    for insight in packet.insights:
        assert insight.evidence_ids
        assert insight.source_ids
        valid_evidence_ids = {e.id for e in packet.evidence}
        assert set(insight.evidence_ids).issubset(valid_evidence_ids)


def test_generate_insights_skips_when_no_evidence():
    packet = ResearchPacket(topic="Acme Corp")
    agents.generate_insights(packet)
    assert packet.insights == []
    assert any("no evidence" in note for note in packet.stage_notes)


def test_generate_insights_uses_llm_result_when_available():
    packet = _packet_with_verified_claim("Acme Corp reported strong quarterly growth in cloud revenue.")
    ev_id = packet.evidence[0].id
    fake_llm_result = [
        {"type": "TREND", "title": "Cloud growth", "body": "Acme's cloud revenue is trending upward.", "evidence_ids": [ev_id]}
    ]
    with patch("backend.agents.call_llm_json", return_value=fake_llm_result):
        agents.generate_insights(packet)

    assert len(packet.insights) == 1
    assert packet.insights[0].type == "TREND"
    assert packet.insights[0].evidence_ids == [ev_id]


def test_generate_insights_rejects_llm_items_with_invalid_evidence_ids():
    packet = _packet_with_verified_claim("Acme Corp reported strong quarterly growth in cloud revenue.")
    fake_llm_result = [
        {"type": "TREND", "title": "Made up", "body": "Not grounded.", "evidence_ids": ["e_doesnotexist"]}
    ]
    with patch("backend.agents.call_llm_json", return_value=fake_llm_result):
        agents.generate_insights(packet)

    assert packet.insights == []  # unsourced insight must be dropped
