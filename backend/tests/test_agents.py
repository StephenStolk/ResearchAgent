from unittest.mock import patch

from backend import agents
from backend.config import LLMUnavailable
from backend.models import (
    Claim,
    ClaimType,
    Evidence,
    Importance,
    ResearchPacket,
    Source,
    VerificationStatus,
)


def _packet_with_evidence(passage: str) -> tuple[ResearchPacket, Evidence]:
    packet = ResearchPacket(topic="Acme Corp")
    src = packet.add_source(Source.from_search_result("https://example.com/a"))
    ev = Evidence(source_id=src.id, passage=passage)
    packet.evidence.append(ev)
    return packet, ev


def test_plan_queries_falls_back_when_llm_unavailable():
    with patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")):
        queries = agents.plan_queries("Acme Corp")
    assert 4 <= len(queries) <= 8
    assert all("Acme Corp" in q for q in queries)


def test_heuristic_extract_pulls_numeric_sentences():
    packet, ev = _packet_with_evidence("Acme reported revenue of $4.2 billion last quarter. It also makes staplers.")
    with patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")):
        agents.extract_claims(packet)
    assert len(packet.claims) >= 1
    assert all(c.evidence_ids for c in packet.claims)


def test_heuristic_verify_supports_when_words_overlap():
    packet, ev = _packet_with_evidence("Acme Corp announced record profits of ten million dollars in Q1.")
    claim = Claim(
        text="Acme Corp announced record profits in Q1",
        claim_type=ClaimType.METRIC,
        importance=Importance.HIGH,
        evidence_ids=[ev.id],
    )
    packet.claims.append(claim)
    with patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")):
        agents.verify_claims(packet)
    assert claim.status in (VerificationStatus.SUPPORTS, VerificationStatus.PARTIAL)


def test_fact_check_flags_absolute_language_and_downgrades_weak_claims():
    packet, ev = _packet_with_evidence("Acme is a leading company.")
    claim = Claim(
        text="Acme dominates the market",
        importance=Importance.HIGH,
        evidence_ids=[ev.id],
        status=VerificationStatus.SUPPORTS,
        verification_confidence=0.4,
    )
    packet.claims.append(claim)
    agents.fact_check(packet)
    assert any("Absolute language" in f for f in packet.content.flags)
    assert claim.status == VerificationStatus.PARTIAL


def test_resolve_conflicts_detects_disagreeing_metric_claims():
    packet = ResearchPacket(topic="Acme Corp")
    packet.claims.append(Claim(text="Revenue was $4B", metric="revenue", claim_type=ClaimType.METRIC))
    packet.claims.append(Claim(text="Revenue was $6B", metric="revenue", claim_type=ClaimType.METRIC))
    agents.resolve_conflicts(packet)
    assert len(packet.conflicts) == 1
    assert packet.conflicts[0].resolved is False


def test_resolve_conflicts_no_conflict_when_claims_agree():
    packet = ResearchPacket(topic="Acme Corp")
    packet.claims.append(Claim(text="Revenue was $4B", metric="revenue", claim_type=ClaimType.METRIC))
    packet.claims.append(Claim(text="Revenue was $4B", metric="revenue", claim_type=ClaimType.METRIC))
    agents.resolve_conflicts(packet)
    assert len(packet.conflicts) == 0


def test_synthesize_falls_back_to_templated_summary():
    packet, ev = _packet_with_evidence("Acme reported revenue of $4.2 billion.")
    packet.claims.append(Claim(
        text="Acme reported revenue of $4.2 billion",
        claim_type=ClaimType.METRIC,
        status=VerificationStatus.SUPPORTS,
        evidence_ids=[ev.id],
    ))
    with patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")):
        agents.synthesize(packet)
    assert packet.summary and "4.2 billion" in packet.summary


def test_synthesize_with_no_verified_claims_writes_explicit_note():
    packet = ResearchPacket(topic="Acme Corp")
    agents.synthesize(packet)
    assert "Insufficient" in packet.summary


def test_build_content_never_invents_facts_beyond_existing_claims():
    packet, ev = _packet_with_evidence("Acme reported revenue of $4.2 billion.")
    packet.claims.append(Claim(
        text="Acme reported revenue of $4.2 billion",
        claim_type=ClaimType.METRIC,
        metric="revenue",
        importance=Importance.HIGH,
        status=VerificationStatus.SUPPORTS,
        evidence_ids=[ev.id],
    ))
    packet.summary = "Acme reported revenue of $4.2 billion."
    agents.build_content(packet)
    assert packet.content.metrics[0]["value_text"] == "Acme reported revenue of $4.2 billion"
    assert len(packet.content.executive_brief) == 1


def test_answer_question_falls_back_to_keyword_relevant_claims():
    packet, ev = _packet_with_evidence("Acme reported revenue of $4.2 billion in Q1.")
    packet.claims.append(Claim(
        text="Acme reported revenue of $4.2 billion in Q1",
        claim_type=ClaimType.METRIC,
        status=VerificationStatus.SUPPORTS,
        evidence_ids=[ev.id],
    ))
    with patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")):
        result = agents.answer_question(packet, "What was Acme's revenue?")
    assert "4.2 billion" in result["answer"]
    assert result["claim_ids"]
