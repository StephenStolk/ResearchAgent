from __future__ import annotations

import re

from backend import agents
from backend.graph.state import ResearchState
from backend.models import ResearchPacket


def _normalize_claim_text(
    text: str,
) -> str:
    """
    Simple claim dedup normalization.
    Later this can become semantic claim matching.
    """

    text = text.lower().strip()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = re.sub(
        r"[^\w\s%$.-]",
        "",
        text,
    )

    return text


def extraction_node(
    state: ResearchState,
) -> dict:

    processed_ids = set(
        state.get(
            "processed_evidence_ids",
            [],
        )
    )

    all_evidence = state.get(
        "evidence",
        [],
    )

    new_evidence = [
        evidence
        for evidence in all_evidence
        if evidence.id not in processed_ids
    ]

    if not new_evidence:

        return {
            "current_stage": "claim_extraction",
            "stage_notes":
                state.get(
                    "stage_notes",
                    [],
                )
                + [
                    "[extractor] no new evidence "
                    "to process"
                ],
        }

    # each model call bounded.
    evidence_batch = new_evidence[:30]
    extraction_packet = ResearchPacket(
        job_id=state["job_id"],
        topic=state["topic"],
    )

    extraction_packet.sources = list(
        state.get("sources", [])
    )

    extraction_packet.evidence = (
        evidence_batch
    )

    call_counter = {
        "count": state.get(
            "llm_calls_used",
            0,
        )
    }

    agents.extract_claims(
        extraction_packet,
        call_counter,
        max_evidence=len(evidence_batch),
    )

    # Merge newly discovered claims into previous claims

    existing_claims = list(
        state.get(
            "claims",
            [],
        )
    )

    claim_index = {
        _normalize_claim_text(claim.text): claim
        for claim in existing_claims
    }

    newly_added = 0
    merged = 0

    for new_claim in extraction_packet.claims:

        key = _normalize_claim_text(
            new_claim.text
        )

        existing = claim_index.get(key)

        if existing is None:

            existing_claims.append(
                new_claim
            )

            claim_index[key] = (
                new_claim
            )

            newly_added += 1
            continue

        # Same claim discovered from another passage/source.
        existing.evidence_ids = list(
            dict.fromkeys(
                existing.evidence_ids
                + new_claim.evidence_ids
            )
        )

        existing.extraction_confidence = max(
            existing.extraction_confidence,
            new_claim.extraction_confidence,
        )

        merged += 1

    processed_ids.update(
        evidence.id
        for evidence in evidence_batch
    )

    notes = list(
        state.get(
            "stage_notes",
            [],
        )
    )

    notes.extend(
        extraction_packet.stage_notes
    )

    notes.append(
        "[extractor] "
        f"new_claims={newly_added}; "
        f"merged_claims={merged}; "
        f"processed_evidence={len(evidence_batch)}"
    )

    return {
        "claims": existing_claims,
        "processed_evidence_ids": list(processed_ids),
        "llm_calls_used": call_counter["count"],
        "current_stage": "claim_extraction",
        "stage_notes": notes,
    }