from __future__ import annotations

from backend.config import MAX_SOURCES_TO_FETCH
from backend.graph.nodes.common import packet_from_state
from backend.graph.state import ResearchState
from backend.models import Evidence
from backend.sources.registry import select_adapters
from backend.tools import (
    chunk_passages,
    fetch_page,
    results_to_sources,
)


def research_node(
    state: ResearchState,
) -> dict:
    """
    Discover and retrieve new sources.
    First iteration: use planner queries
    Later iterations: use verification-generated follow-up queries
    Sources already fetched in earlier iterations are skipped.
    """

    packet = packet_from_state(state)

    follow_up = state.get(
        "follow_up_queries",
        [],
    )

    queries = (
        follow_up
        if follow_up
        else state.get("queries", [])
    )

    fetched_source_ids = set(
        state.get(
            "fetched_source_ids",
            [],
        )
    )

    adapters_used: set[str] = set()

    # DISCOVERY
   
    for query in queries:

        for adapter in select_adapters(query):

            adapters_used.add(
                adapter.name
            )

            try:
                results = adapter.search(query)

            except Exception as exc:
                packet.stage_notes.append(
                    f"[research] adapter={adapter.name} "
                    f"query={query!r} failed: {exc}"
                )
                continue

            try:
                sources = results_to_sources(
                    results
                )

            except Exception as exc:
                packet.stage_notes.append(
                    f"[research] result normalization "
                    f"failed for {adapter.name}: {exc}"
                )
                continue

            for source in sources:
                packet.add_source(source)

    # RANK SOURCES
    
    ranked_sources = sorted(
        packet.sources,
        key=lambda source:
            source.authority_score,
        reverse=True,
    )

    fetched_this_iteration = 0

   
    #FETCH ONLY NEW SOURCES
   

    for source in ranked_sources:

        if fetched_this_iteration >= MAX_SOURCES_TO_FETCH:
            break

        if source.id in fetched_source_ids:
            continue

        try:
            text = fetch_page(
                source.url
            )

        except Exception as exc:
            packet.stage_notes.append(
                f"[research] fetch failed "
                f"url={source.url}: {exc}"
            )

            continue

        if not text:
            continue

        fetched_this_iteration += 1

        fetched_source_ids.add(
            source.id
        )

        for passage in chunk_passages(text):

            packet.evidence.append(
                Evidence(
                    source_id=source.id,
                    passage=passage,
                )
            )

    iteration = (
        state.get(
            "research_iteration",
            0,
        )
        + 1
    )

    packet.stage_notes.append(
        "[research] "
        f"iteration={iteration}; "
        f"queries={len(queries)}; "
        f"new_fetches={fetched_this_iteration}; "
        f"total_sources={len(packet.sources)}; "
        f"total_evidence={len(packet.evidence)}; "
        f"adapters={','.join(sorted(adapters_used)) or 'none'}"
    )

    return {
        "sources": packet.sources,
        "evidence": packet.evidence,

        "fetched_source_ids":
            list(fetched_source_ids),

        "research_iteration":
            iteration,

        # A follow-up query should only be used once.
        "follow_up_queries": [],

        "current_stage": "research",

        "stage_notes":
            packet.stage_notes,
    }