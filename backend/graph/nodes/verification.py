from __future__ import annotations

from backend import agents

from backend.graph.nodes.common import (
    packet_from_state,
)
from backend.graph.state import (
    ResearchState,
)

from backend.models import (
    Importance,
    VerificationStatus,
)

WEAK_STATUSES = {
    VerificationStatus.INSUFFICIENT,
    VerificationStatus.UNVERIFIED,
    VerificationStatus.CONTRADICTS,
    VerificationStatus.OUTDATED,
}

def verification_node(
    state: ResearchState,
) -> dict:
    """
    Verify extracted claims and determine whether the
    research graph has enough evidence to continue.
    """
    
    packet = packet_from_state(state)
    call_counter = {
        "count": state.get(
            "llm_calls_used",
            0,
        )
    }
    agents.verify_claims(
        packet,
        call_counter,
    )
    claims = packet.claims
    total_claims = len(claims)
    
    supported = sum(
        1
        for claim in claims
        if claim.status == VerificationStatus.SUPPORTS
    )
    
    partially_supported = sum(
        1
        for claim in claims
        if claim.status
        == VerificationStatus.PARTIAL
    )
    
    if total_claims:
        
        verification_rate = (
            supported + (0.5*partially_supported)
        )/total_claims
    
    else:
        verification_rate=0.0
        
    evidence_coverage = (
        packet.claim_coverage()
    )
    
    #identify weak claims
    weak_claims = [
        claim
        for claim in claims
        if (
            claim.status in WEAK_STATUSES
            and claim.importance
            in (
                Importance.HIGH,
                Importance.MEDIUM,
            )
        )
    ]
    
    research_gaps = []
    for claim in weak_claims[:8]:

        research_gaps.append(
            f"Find stronger or independent evidence "
            f"for claim: {claim.text}"
        )
        
    iteration = state.get(
        "research_iteration",
        0,
    )

    max_iterations = state.get(
        "max_research_iterations",
        2,
    )
    
    #agentic decision
    insufficient_quality = (
        verification_rate < 0.55
        or not claims
    )
    can_research_more = (
        iteration < max_iterations
    )
    
    needs_more_research = (
        insufficient_quality
        and can_research_more
        and bool(research_gaps)
    )
    
    contradictory = any(
        claim.status
        == VerificationStatus.CONTRADICTS

        for claim in claims
    )
    
    notes = list(
        packet.stage_notes
    )
    
    notes.append(
        "[verifier] "
        f"verification_rate={verification_rate:.2f}; "
        f"coverage={evidence_coverage:.2f}; "
        f"gaps={len(research_gaps)}; "
        f"needs_more_research={needs_more_research}"
    )
    
    return {
        "claims": claims,
        "verification_rate": verification_rate,
        "evidence_coverage":evidence_coverage,
        "research_gaps":research_gaps,
        "needs_more_research":needs_more_research,
        "needs_conflict_resolution":contradictory,
        "research_reason": (
            "verification quality below threshold"
            if needs_more_research
            else None
        ),
        "llm_calls_used":call_counter["count"],
        "current_stage":"verification",
        "stage_notes": notes,
    }