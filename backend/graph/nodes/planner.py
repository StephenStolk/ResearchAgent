from __future__ import annotations

from backend import agents
from backend.graph.nodes.common import packet_from_state
from backend.graph.state import ResearchState


def planner_node(
    state: ResearchState,
) -> dict:

    packet = packet_from_state(state)

    call_counter = {
        "count": state.get(
            "llm_calls_used",
            0,
        )
    }

    queries = agents.plan_queries(
        state["topic"],
        call_counter,
        packet,
    )

    notes = list(
        state.get("stage_notes", [])
    )

    notes.extend(packet.stage_notes)

    return {
        "queries": queries,

        "current_stage": "planner",

        "llm_calls_used":
            call_counter["count"],

        "stage_notes": notes,
    }