#utility to convert packet to state
from __future__ import annotations

from backend.graph.state import ResearchState
from backend.models import ResearchPacket

def packet_from_state(
    state: ResearchState
) -> ResearchPacket:
    
    packet = ResearchPacket(
        job_id=state["job_id"],
        topic=state["topic"],
    )
    
    packet.sources = list(
        state.get("sources", [])
    )

    packet.evidence = list(
        state.get("evidence", [])
    )

    packet.claims = list(
        state.get("claims", [])
    )
    
    packet.conflicts = list(
        state.get("conflicts", [])
    )

    packet.insights = list(
        state.get("insights", [])
    )

    packet.open_questions = list(
        state.get("open_questions", [])
    )
    
    packet.summary = state.get("summary")
    packet.content = state.get("content")

    packet.charts = list(
        state.get("charts", [])
    )
    
    packet.stage_notes = list(
        state.get("stage_notes", [])
    )

    packet.stage_timings_ms = dict(
        state.get("stage_timings_ms", {})
    )

    return packet
