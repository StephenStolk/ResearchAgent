from __future__ import annotations
from typing import TypedDict

from backend.models import (
    ChartSpec,
    Claim,
    Conflict,
    ContentViews,
    Evidence,
    Insight,
    VerificationStatus,
    ReportStatus,
    Source,
)

class ResearchState(TypedDict, total=False):
    """
    Canonical state passed between all LangGraph research nodes.

    ResearchPacket remains our external/domain representation.

    ResearchState is the internal orchestration state used while the research graph is executing.
    """
    
    #identity
    job_id: str
    topic: str
    
    #planning
    queries: list[str]
    
    # How many times we've returned to research because the verifier decided evidence was insufficient.
    research_iteration: int
    max_research_iterations: int
    
    #research data
    sources: list[Source]
    evidence: list[Evidence]
    
    #knowledge
    claims: list[Claim]
    conflicts: list[Conflict]
    insights: list[Insight]
    
    open_questions: list[str]
    
    #output
    summary: str | None
    content: ContentViews | None
    
    charts: list[ChartSpec]
    
    #quality
    report_status: ReportStatus
    evidence_coverage: float
    verification_rate: float
    unresolved_conflicts: int
    
    #agent routing
    needs_more_research: bool
    needs_conflict_resolution: bool
    research_reason: str | None
    
    #runtime
    current_stage: str

    stage_notes: list[str]
    stage_timings_ms: dict[str, int]
    errors: list[str]
    
    #budget
    llm_calls_used: int
    
    #iterative research
    follow_up_queries: list[str]
    
    #to avoid fetching repetitive sources
    fetched_source_ids: list[str]
    
    #to avoid rerunning extraction on the same evidence
    processed_evidence_ids: list[str]
    
    #verification generated gaps
    research_gaps: list[str]
    
    

from backend.models import ResearchPacket


def create_research_state(
    packet: ResearchPacket,
    *,
    max_research_iterations: int = 2,
) -> ResearchState:
    """
    Convert a fresh ResearchPacket into graph execution state.
    """

    return ResearchState(
        job_id=packet.job_id,
        topic=packet.topic,

        queries=[],

        research_iteration=0,
        max_research_iterations=max_research_iterations,

        sources=list(packet.sources),
        evidence=list(packet.evidence),

        claims=list(packet.claims),
        conflicts=list(packet.conflicts),
        insights=list(packet.insights),

        open_questions=list(packet.open_questions),

        summary=packet.summary,
        content=packet.content,
        charts=list(packet.charts),

        report_status=packet.status,

        evidence_coverage=0.0,
        verification_rate=0.0,
        unresolved_conflicts=0,

        needs_more_research=False,
        needs_conflict_resolution=False,
        research_reason=None,

        current_stage="initialized",

        stage_notes=list(packet.stage_notes),
        stage_timings_ms=dict(packet.stage_timings_ms),

        errors=[],

        llm_calls_used=0,
        follow_up_queries=[],
        fetched_source_ids=[],
        processed_evidence_ids=[],
        research_gaps=[],
    )
    


def state_to_packet(state: ResearchState) -> ResearchPacket:
    """
    Convert graph execution state into the canonical
    ResearchPacket returned by the API.
    """
    
    packet = ResearchPacket(
        job_id=state["job_id"],
        topic=state["topic"],
    )
    
    packet.sources = state.get("sources", [])
    packet.evidence = state.get("evidence", [])
    packet.claims = state.get("claims", [])
    packet.conflicts = state.get("conflicts", [])
    packet.insights = state.get("insights", [])
    packet.open_questions = state.get(
        "open_questions",
        [],
    )
    
    packet.summary = state.get("summary")
    packet.content = state.get("content")

    packet.charts = state.get("charts", [])
    
    packet.stage_notes = state.get(
        "stage_notes",
        [],
    )

    packet.stage_timings_ms = state.get(
        "stage_timings_ms",
        {},
    )
    
    packet.status = state.get(
        "report_status",
        VerificationStatus.NEEDS_REVIEW,
    )
    
    return packet
    
    
