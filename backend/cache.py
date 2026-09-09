"""File-backed cache — blueprint section 22 ("Caching Without Redis").

Keyed by namespace + normalized key + relevant version numbers, so a
prompt/pipeline/schema bump automatically invalidates old entries
instead of silently mixing old and new logic. A future Redis-backed
implementation can satisfy the same three functions.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from backend.config import CACHE_DIR
from backend.models import content_hash


def _path_for(namespace: str, key: str, versions: dict) -> Path:
    version_tag = json.dumps(versions, sort_keys=True)
    digest = content_hash(f"{key}::{version_tag}")
    d = Path(CACHE_DIR) / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{digest}.json"


def cache_get(namespace: str, key: str, versions: dict) -> Optional[Any]:
    path = _path_for(namespace, key, versions)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if record.get("expires_at", 0) < time.time():
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return record.get("value")


def cache_set(namespace: str, key: str, value: Any, versions: dict, ttl_seconds: int) -> None:
    path = _path_for(namespace, key, versions)
    record = {
        "stored_at": time.time(),
        "expires_at": time.time() + ttl_seconds,
        "versions": versions,
        "value": value,
    }
    try:
        path.write_text(json.dumps(record))
    except OSError:
        pass  # cache is best-effort; never fail the pipeline over it


def cache_clear(namespace: Optional[str] = None) -> None:
    base = Path(CACHE_DIR) / namespace if namespace else Path(CACHE_DIR)
    if not base.exists():
        return
    for f in base.rglob("*.json"):
        try:
            f.unlink()
        except OSError:
            pass
