"""Shared outbound HTTP client (generic User-Agent, no personal data) + tiny disk JSON cache."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from uhd.config import get_settings

_client: httpx.Client | None = None
_lock = threading.Lock()


def client() -> httpx.Client:
    global _client
    with _lock:
        if _client is None:
            s = get_settings()
            _client = httpx.Client(timeout=s.http_timeout_s, headers={"User-Agent": s.user_agent},
                                   follow_redirects=True)
        return _client


class DiskCache:
    """JSON files keyed by sha256(key); optional TTL (seconds)."""

    def __init__(self, name: str):
        self.name = name

    @property
    def root(self) -> Path:
        p = get_settings().cache_dir / self.name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode()).hexdigest()
        return self.root / h[:2] / f"{h}.json"

    def get(self, key: str, ttl: float | None = None) -> Any | None:
        p = self._path(key)
        try:
            if ttl is not None and time.time() - p.stat().st_mtime > ttl:
                return None
            return json.loads(p.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def put(self, key: str, value: Any) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        os.replace(tmp, p)


class SlotLimiter:
    """Minimum interval between calls shared by *all* worker processes (REVIEW M7).

    The next free time slot is kept in a small file under ``cache_dir`` and updated under an exclusive ``flock`` that is
    held only for the read-modify-write (microseconds), never while sleeping. A caller reserves the next slot only if it
    starts within ``max_wait_s``; otherwise it gets ``False`` immediately (no thread is parked for long), so with N
    workers the upstream still sees ≤ 1 request per ``min_interval_s``.
    """

    def __init__(self, name: str, min_interval_s: float):
        self.name = name
        self.min_interval_s = min_interval_s

    @property
    def path(self) -> Path:
        d = get_settings().cache_dir
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self.name}.slot"

    def reserve(self, max_wait_s: float = 0.0) -> float | None:
        """Seconds to wait before the call (≤ max_wait_s), or None when the limiter is busy."""
        import fcntl

        with open(self.path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                try:
                    nxt = float(f.read().strip() or 0)
                except ValueError:
                    nxt = 0.0
                now = time.time()
                start = max(now, nxt)
                if start - now > max_wait_s:
                    return None
                f.seek(0)
                f.truncate()
                f.write(f"{start + self.min_interval_s:.6f}")
                f.flush()
                return start - now
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def acquire(self, max_wait_s: float = 0.0) -> bool:
        wait = self.reserve(max_wait_s)
        if wait is None:
            return False
        if wait > 0:
            time.sleep(wait)
        return True
