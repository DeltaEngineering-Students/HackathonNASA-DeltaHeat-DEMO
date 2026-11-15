"""Run the analyst test questions against the real Claude API (needs ANTHROPIC_API_KEY; costs money).

    uv run python -m uhd.agent.evalrun tests/agent/questions.yaml [--only q01_headline,q02_…] [--first 5] [--team]
    uv run python -m uhd.agent.evalrun tests/agent/questions.yaml --url https://host/api/agent/chat [--team --token-file F]

With ``--url`` the questions go to a deployed ``POST /api/agent/chat`` (SSE) instead of the in-process loop, so no key
is needed locally; ``--team`` then sends the team token read from ``--token-file`` (never printed).

Checks the tool-call expectations, the number validator and the caveat checker; prints one JSON line per question
(tools, cost, latency, validation, missing caveats) and a summary with the total cost. Each run is also written to
``evals/runs/<UTC-time>.jsonl`` (gitignored) with the answers, for the manual checks (mentions_verdict,
facts_vs_hypotheses …). The key is read from the environment only and is never printed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from uhd.agent import loop
from uhd.agent.tools import BY_NAME


def load(path: str) -> list[dict]:
    qs = yaml.safe_load(open(path))
    for q in qs:
        for t in q.get("expect_tools", []) + q.get("any_of", []) + q.get("forbid_tools", []):
            if t not in BY_NAME and t not in ("web_search", "web_fetch"):
                raise ValueError(f"{q['id']}: unknown tool {t}")
    return qs


def _remote_events(url: str, token: str | None, q: dict):
    import httpx

    body = {"messages": [*q.get("history", []), {"role": "user", "content": q["question"]}], "context": q.get("context")}
    headers = {"X-UHD-Team-Token": token} if token else {}
    with httpx.stream("POST", url, json=body, headers=headers, timeout=httpx.Timeout(300, connect=20)) as r:
        if r.status_code != 200:
            r.read()
            try:
                err = r.json()
            except ValueError:
                err = {"code": f"http_{r.status_code}"}
            yield {"type": "error", "error": err, "status": r.status_code}
            return
        ev_type = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev_type = line[6:].strip()
            elif line.startswith("data:"):
                ev = json.loads(line[5:])
                ev.setdefault("type", ev_type)
                yield ev


def run_one(q: dict, team: bool, url: str | None = None, token: str | None = None) -> dict:
    called, web, done, steps = [], [], None, 0
    t0 = time.time()
    events = (_remote_events(url, token if team else None, q) if url else
              loop.run_chat([*q.get("history", []), {"role": "user", "content": q["question"]}], team=team, context=q.get("context")))
    for ev in events:
        if ev["type"] == "tool_call":
            called.append(ev["name"])
        elif ev["type"] == "web":
            web.append(ev["name"])
        elif ev["type"] == "validation":
            steps += 1
        elif ev["type"] in ("done", "error"):
            done = ev
    dt = time.time() - t0
    miss = [t for t in q.get("expect_tools", []) if t not in called]
    any_ok = not q.get("any_of") or any(t in called for t in q["any_of"])
    forbidden = [t for t in q.get("forbid_tools", []) if t in called]
    is_done = bool(done and done["type"] == "done")
    val_ok = bool(is_done and done.get("validation", {}).get("ok"))
    cav = (done or {}).get("caveats") or []
    ok = is_done and not miss and any_ok and not forbidden and (val_ok or "validator_ok" not in q.get("checks", [])) \
        and not cav
    return {"id": q["id"], "ok": ok, "called": called, "web": web, "missing": miss, "any_of_ok": any_ok,
            "forbidden": forbidden, "validator_ok": val_ok, "repairs": steps,
            "unsourced": [u["text"] for u in (done or {}).get("validation", {}).get("unsourced", [])] if is_done else [],
            "caveats_missing": [c["code"] for c in cav], "error": None if is_done else (done or {}).get("error"),
            "cost_usd": (done or {}).get("cost_usd"), "usage": (done or {}).get("usage"), "seconds": round(dt, 1),
            "table_rows": max(0, sum(1 for ln in ((done or {}).get("answer") or "").splitlines()
                                     if ln.strip().startswith("|")) - 2),
            "answer_chars": len((done or {}).get("answer") or ""),
            "manual_checks": q.get("checks", []), "question": q["question"],
            "answer": (done or {}).get("answer", "")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--first", type=int, help="run only the first N questions")
    ap.add_argument("--team", action="store_true")
    ap.add_argument("--out", default="evals/runs")
    ap.add_argument("--url", help="deployed POST /api/agent/chat endpoint (no local key needed)")
    ap.add_argument("--token-file", help="file holding the team token (with --url --team)")
    a = ap.parse_args(argv)
    token = Path(a.token_file).read_text().strip() if a.token_file else None
    if a.url and a.team and not token:
        ap.error("--url --team needs --token-file")
    qs = load(a.path)
    if a.only:
        ids = set(a.only.split(","))
        qs = [q for q in qs if q["id"] in ids]
    if not a.team:
        qs = [q for q in qs if not q.get("team_only")]
    if a.first:
        qs = qs[: a.first]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + (".team" if a.team else ".public") + ".jsonl")
    total, n_ok, rows = 0.0, 0, []
    with open(path, "w", encoding="utf-8") as f:
        for q in qs:
            r = run_one(q, a.team, a.url, token)
            rows.append(r)
            total += r["cost_usd"] or 0.0
            n_ok += r["ok"]
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(json.dumps({k: v for k, v in r.items() if k not in ("answer", "question", "usage")},
                             ensure_ascii=False), flush=True)
        costs = sorted(r["cost_usd"] or 0 for r in rows)
        summary = {"summary": True, "n": len(rows), "ok": n_ok, "total_cost_usd": round(total, 4),
                   "median_cost_usd": costs[len(costs) // 2] if costs else None,
                   "max_cost_usd": costs[-1] if costs else None,
                   "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None,
                   "file": str(path)}
        f.write(json.dumps(summary) + "\n")
    print(json.dumps(summary), flush=True)
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
