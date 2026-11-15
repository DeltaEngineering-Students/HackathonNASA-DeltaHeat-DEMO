"""Report store on disk (``{reports_dir}/{id}.json``) with an in-memory LRU in front."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

from uhd.config import get_settings
from uhd.errors import bad_request, not_found

_ID = re.compile(r"^[0-9a-f]{16}$")
_mem: OrderedDict[str, dict] = OrderedDict()
_mem_lock = threading.Lock()
MEM_MAX = 256


def _dir() -> Path:
    p = get_settings().reports_dir
    p.mkdir(parents=True, exist_ok=True)
    return p


def valid_id(rid: str) -> bool:
    return bool(_ID.match(rid))


def clear_memory() -> None:
    with _mem_lock:
        _mem.clear()


def _remember(rid: str, rep: dict) -> None:
    with _mem_lock:
        _mem[rid] = rep
        _mem.move_to_end(rid)
        while len(_mem) > MEM_MAX:
            _mem.popitem(last=False)


def get(rid: str) -> dict | None:
    if not valid_id(rid):
        return None
    with _mem_lock:
        if rid in _mem:
            _mem.move_to_end(rid)
            return _mem[rid]
    try:
        rep = json.loads((_dir() / f"{rid}.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    _remember(rid, rep)
    return rep


def require(rid: str) -> dict:
    if not valid_id(rid):
        raise bad_request("invalid_report_id", "report_id must be 16 hex characters")
    rep = get(rid)
    if rep is None:
        raise not_found("report_not_found", f"no such report: {rid}")
    return rep


def put(rep: dict) -> None:
    rid = rep["report_id"]
    p = _dir() / f"{rid}.json"
    tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(rep, ensure_ascii=False))
    os.replace(tmp, p)
    _remember(rid, rep)


def summary(rep: dict) -> dict:
    t = rep.get("trend") or {}
    gs = rep.get("gap_summary") or {}
    z = rep.get("zone") or {}
    return {"report_id": rep["report_id"], "name": z.get("name"), "place_id": (rep.get("params") or {}).get("place_id"),
            "created_at": rep.get("created_at"), "years": (rep.get("params") or {}).get("years"),
            "area_km2": z.get("area_km2"), "gap_last": gs.get("last"), "gap_mean": gs.get("mean"),
            "slope_per_decade": t.get("slope_per_decade"), "p": t.get("p"), "verdict": t.get("verdict"),
            "data_version": (rep.get("params") or {}).get("data_version")}


def list_reports(limit: int = 50) -> list[dict]:
    files = sorted(_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, min(limit, 500))]
    out = []
    for f in files:
        rep = get(f.stem)
        if rep:
            out.append(summary(rep))
    return out
