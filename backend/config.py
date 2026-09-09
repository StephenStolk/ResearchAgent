"""Shared configuration and LLM client for the research pipeline.

Centralizing this here means every agent module calls the same
budgeted, cache-aware entry point instead of constructing its own
ChatOpenAI client (blueprint section 30: cost & rate-limit strategy).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from langchain_openai import ChatOpenAI

# --- Query planning ---------------------------------------------------
MIN_QUERIES = int(os.getenv("RESEARCH_MIN_QUERIES", "4"))
MAX_QUERIES = int(os.getenv("RESEARCH_MAX_QUERIES", "8"))
SEARCH_RESULTS_PER_QUERY = int(os.getenv("RESEARCH_SEARCH_RESULTS_PER_QUERY", "8"))

# --- Fetch / evidence ---------------------------------------------------
MAX_SOURCES_TO_FETCH = int(os.getenv("RESEARCH_MAX_SOURCES_TO_FETCH", "10"))
FETCH_TIMEOUT_SECONDS = int(os.getenv("RESEARCH_FETCH_TIMEOUT", "8"))
MAX_RESPONSE_BYTES = int(os.getenv("RESEARCH_MAX_RESPONSE_BYTES", str(3 * 1024 * 1024)))
PASSAGE_CHUNK_CHARS = int(os.getenv("RESEARCH_PASSAGE_CHUNK_CHARS", "700"))

# --- LLM call budget per job (blueprint section 30) ---------------------
MAX_LLM_CALLS_PER_JOB = int(os.getenv("RESEARCH_MAX_LLM_CALLS", "12"))

# --- Cache ---------------------------------------------------------------
CACHE_DIR = os.getenv("RESEARCH_CACHE_DIR", ".cache")
SEARCH_CACHE_TTL = int(os.getenv("RESEARCH_SEARCH_CACHE_TTL", str(60 * 60 * 6)))     # 6h
PAGE_CACHE_TTL = int(os.getenv("RESEARCH_PAGE_CACHE_TTL", str(60 * 60 * 24)))        # 24h
LLM_CACHE_TTL = int(os.getenv("RESEARCH_LLM_CACHE_TTL", str(60 * 60 * 24 * 7)))      # 7d

PIPELINE_VERSION = "0.1.0"
PROMPT_VERSIONS = {
    "planner": "planner_v1",
    "extractor": "extractor_v1",
    "verifier": "verifier_v1",
    "fact_checker": "fact_checker_v1",
    "synthesizer": "synthesizer_v1",
    "ask": "ask_v1",
    "scenario": "scenario_v1",
}

MODEL_NAME = os.getenv("RESEARCH_MODEL", "openrouter/free")
BASE_URL = os.getenv("RESEARCH_LLM_BASE_URL", "https://openrouter.ai/api/v1")

_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=MODEL_NAME, temperature=0, base_url=BASE_URL)
    return _llm


class LLMCallBudgetExceeded(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    """Raised when the model can't be reached or the API key is missing.
    Callers should catch this and fall back to a deterministic heuristic
    (see each agent's fallback path) rather than crash the whole job -
    blueprint section 24, graceful degradation."""


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    call_counter: dict[str, int] | None = None,
    stage: str = "unknown",
) -> Any:
    """Call the LLM and parse a JSON response. Raises LLMUnavailable on
    any failure (network, auth, malformed output after one retry) so the
    caller can degrade gracefully instead of crashing the pipeline."""
    if call_counter is not None:
        used = call_counter.get("count", 0)
        if used >= MAX_LLM_CALLS_PER_JOB:
            raise LLMCallBudgetExceeded(f"LLM call budget exceeded at stage={stage}")
        call_counter["count"] = used + 1

    llm = get_llm()
    messages = [
        {"role": "system", "content": system_prompt + "\n\nRespond with JSON only. No prose, no markdown fences."},
        {"role": "user", "content": user_prompt},
    ]
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = llm.invoke(messages)
            raw = _strip_code_fences(response.content if isinstance(response.content, str) else str(response.content))
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a degrade point
            last_error = exc
    raise LLMUnavailable(f"stage={stage}: {last_error}")


def with_fallback(fn: Callable[[], Any], fallback: Callable[[], Any], stage: str, on_error: Callable[[str, Exception], None] | None = None) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        if on_error:
            on_error(stage, exc)
        return fallback()
