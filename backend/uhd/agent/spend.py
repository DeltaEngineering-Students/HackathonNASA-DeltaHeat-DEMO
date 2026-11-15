"""Spend control for the analyst (CLAUDE-API-PLAN §5 «Cost caps», §6).

* ``cost_usd(usage)`` — dollars for one API response from its ``usage`` and the documented prices (config).
* Daily budget per tier (UTC day) in ``cache_dir/agent_spend.json``, shared by all workers under ``flock``:
  ``check_budget(tier)`` before a chat (→ 503 ``agent_budget_exhausted``), ``add_spend(tier, usd)`` after each turn.
* ``log_request(...)`` — one JSONL line per chat in ``cache_dir/agent_log/<UTC-date>.jsonl``, kept
  ``agent_log_days``. Team: question/answer text; public: SHA-256 + length only. Never IPs, tokens or keys.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from uhd.config import Settings, get_settings
from uhd.errors import APIError

_lock = threading.Lock()
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
              "web_search_requests")


def usage_dict(u: Any) -> dict[str, int]:
    """Plain counts from an SDK ``usage`` object (or a dict)."""
    get = (lambda k: u.get(k)) if isinstance(u, dict) else (lambda k: getattr(u, k, None))  # noqa: E731
    out = {k: int(get(k) or 0) for k in USAGE_KEYS[:4]}
    stu = get("server_tool_use")
    if isinstance(stu, dict):
        out["web_search_requests"] = int(stu.get("web_search_requests") or 0)
    else:
        out["web_search_requests"] = int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
    if isinstance(u, dict) and "web_search_requests" in u:
        out["web_search_requests"] = int(u["web_search_requests"] or 0)
    return out


def cost_usd(usage: dict[str, int], s: Settings | None = None) -> float:
    s = s or get_settings()
    return (usage.get("input_tokens", 0) * s.agent_price_input
            + usage.get("output_tokens", 0) * s.agent_price_output
            + usage.get("cache_read_input_tokens", 0) * s.agent_price_cache_read
            + usage.get("cache_creation_input_tokens", 0) * s.agent_price_cache_write) / 1e6 \
        + usage.get("web_search_requests", 0) * s.agent_price_web_search


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def seconds_to_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((nxt - now).total_seconds()))


@contextlib.contextmanager
def _locked_json(path: Path) -> Iterator[dict]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                data = json.loads(f.read() or "{}")
                if not isinstance(data, dict):
                    data = {}
            except ValueError:
                data = {}
            yield data
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data))
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _spend_path(s: Settings) -> Path:
    return s.cache_dir / "agent_spend.json"


def daily_budget(tier: str, s: Settings) -> float:
    return s.agent_daily_budget_team_usd if tier == "team" else s.agent_daily_budget_public_usd


def request_cap(tier: str, s: Settings) -> float:
    return s.agent_request_cap_team_usd if tier == "team" else s.agent_request_cap_public_usd


def spent_today(tier: str, s: Settings | None = None) -> float:
    s = s or get_settings()
    with _locked_json(_spend_path(s)) as d:
        return float((d.get(_today()) or {}).get(tier, 0.0))


def check_budget(tier: str, s: Settings | None = None) -> None:
    s = s or get_settings()
    if spent_today(tier, s) >= daily_budget(tier, s):
        e = APIError(503, "agent_budget_exhausted", "the analyst's daily budget is used up; it resets at 00:00 UTC")
        e.headers = {"Retry-After": str(seconds_to_midnight_utc())}
        raise e


def add_spend(tier: str, usd: float, s: Settings | None = None) -> float:
    """Add to today's spend; returns the new total. Keeps only the last 7 days."""
    s = s or get_settings()
    day = _today()
    with _locked_json(_spend_path(s)) as d:
        for k in sorted(d)[:-7]:
            d.pop(k, None)
        row = d.setdefault(day, {})
        row[tier] = round(float(row.get(tier, 0.0)) + float(usd), 6)
        return row[tier]


def count_request(tier: str, s: Settings | None = None) -> None:
    s = s or get_settings()
    with _locked_json(_spend_path(s)) as d:
        row = d.setdefault(_today(), {})
        row[f"{tier}_requests"] = int(row.get(f"{tier}_requests", 0)) + 1


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


def log_request(entry: dict, *, tier: str, question: str, answer: str, s: Settings | None = None) -> None:
    s = s or get_settings()
    d = s.cache_dir / "agent_log"
    try:
        d.mkdir(parents=True, exist_ok=True)
        row = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tier": tier, **entry,
               "question_len": len(question), "answer_len": len(answer)}
        if tier == "team":
            row["question"], row["answer"] = question[:4000], answer[:20000]
        else:
            row["question_sha"], row["answer_sha"] = _hash(question), _hash(answer)
        with _lock, open(d / f"{_today()}.jsonl", "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
        cutoff = time.time() - s.agent_log_days * 86400
        for p in d.glob("*.jsonl"):
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
    except OSError:
        pass
