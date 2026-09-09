from unittest.mock import patch

from backend import pipeline
from backend.config import LLMUnavailable
from backend.models import ReportStatus
from backend.sources.base import SourceAdapter


class _FakeAdapter(SourceAdapter):
    name = "fake"

    def __init__(self, results):
        self._results = results

    def search(self, query: str, max_results: int = 8):
        return self._results


SEARCH_RESULTS = [
    {"title": "Acme Corp overview", "url": "https://example.com/acme-overview", "body": "..."},
    {"title": "Acme filing", "url": "https://sec.gov/acme-10k", "body": "..."},
]

# Includes dated metric mentions so the line/bar chart builders have
# something real to work with in the end-to-end smoke test.
PAGE_TEXT = (
    "Acme Corp reported revenue of $4.2 billion in Q1 2025. "
    "In Q2 2025 revenue grew to $4.8 billion. "
    "In Q3 2025 revenue reached $5.1 billion. "
    "The company also announced a new product line targeting enterprise customers. "
    "Analysts noted continued growth in the cloud services segment."
)


def test_run_research_end_to_end_without_llm_or_real_network():
    with patch("backend.pipeline.select_adapters", return_value=[_FakeAdapter(SEARCH_RESULTS)]), \
         patch("backend.pipeline.fetch_page", return_value=PAGE_TEXT), \
         patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key configured")), \
         patch("backend.pipeline.cache_set"):
        packet = pipeline.run_research("Acme Corp")

    assert packet.topic == "Acme Corp"
    assert len(packet.sources) == 2
    assert len(packet.evidence) > 0
    assert len(packet.claims) > 0
    assert packet.summary
    assert packet.status in (ReportStatus.VERIFIED, ReportStatus.PARTIAL, ReportStatus.NEEDS_REVIEW)
    assert "planner" in packet.stage_timings_ms
    assert "content_builder" in packet.stage_timings_ms
    assert "chart_builder" in packet.stage_timings_ms
    assert "insights" in packet.stage_timings_ms
    # Every chart must cite real claims/sources already in the packet.
    for chart in packet.charts:
        assert chart.claim_ids
        assert all(cid in {c.id for c in packet.claims} for cid in chart.claim_ids)
    for insight in packet.insights:
        assert insight.evidence_ids


def test_quality_gate_is_needs_review_with_no_sources():
    with patch("backend.pipeline.select_adapters", return_value=[_FakeAdapter([])]), \
         patch("backend.agents.call_llm_json", side_effect=LLMUnavailable("no key")), \
         patch("backend.pipeline.cache_set"):
        packet = pipeline.run_research("Totally Obscure Topic Xyz")

    assert packet.status == ReportStatus.NEEDS_REVIEW
    assert packet.charts == []
