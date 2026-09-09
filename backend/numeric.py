"""Parse a claim's free-text metric mention into a normalized numeric
value + unit, so chart agents can plot real numbers instead of re-reading
prose. Deliberately conservative: returns (None, None) rather than
guessing when the text is ambiguous.
"""

from __future__ import annotations

import re
from typing import Optional

_CURRENCY_RE = re.compile(
    r"[\$€£]\s?(\d[\d,]*\.?\d*)\s?(billion|bn|million|mn|thousand|k)?",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(\d+\.?\d*)\s?%")
_PLAIN_NUMBER_RE = re.compile(r"\b(\d[\d,]*\.?\d*)\s?(billion|bn|million|mn|thousand|k)\b", re.IGNORECASE)

_SCALE = {
    "billion": 1e9, "bn": 1e9,
    "million": 1e6, "mn": 1e6,
    "thousand": 1e3, "k": 1e3,
}


def parse_metric_value(text: str) -> tuple[Optional[float], Optional[str]]:
    """Returns (value, unit) where unit is one of 'USD', '%', 'count'."""
    match = _CURRENCY_RE.search(text)
    if match:
        raw, scale_word = match.group(1), match.group(2)
        value = float(raw.replace(",", ""))
        if scale_word:
            value *= _SCALE[scale_word.lower()]
        return value, "USD"

    match = _PERCENT_RE.search(text)
    if match:
        return float(match.group(1)), "%"

    match = _PLAIN_NUMBER_RE.search(text)
    if match:
        raw, scale_word = match.group(1), match.group(2)
        value = float(raw.replace(",", "")) * _SCALE[scale_word.lower()]
        return value, "count"

    return None, None
