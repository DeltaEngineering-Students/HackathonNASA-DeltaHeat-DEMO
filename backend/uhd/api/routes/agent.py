"""AI analyst endpoints (decision #19). Inert until ANTHROPIC_API_KEY is set."""

from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from uhd.agent import loop, spend, tools
from uhd.config import get_settings
from uhd.errors import APIError

router = APIRouter(prefix="/api/agent")
_hits_lock = threading.Lock()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=20000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=40)
    context: dict[str, Any] | None = Field(None, description="UI context: report_id, place_id, layer, year (≤ 4 KB)")

    @field_validator("context")
    @classmethod
    def _small_context(cls, v):
        if v is not None and len(json.dumps(v, ensure_ascii=False, default=str)) > 4096:
            raise ValueError("context is limited to 4 KB")
        return v


def _is_team(token: str | None) -> bool:
    t = get_settings().agent_team_token
    return bool(t and token and secrets.compare_digest(t, token))


def _rate_limit(key: str, per_hour: int, per_minute: int | None = None) -> None:
    """Per-IP hourly limit shared by all workers and surviving reloads (RB-12): timestamps in one JSON file under
    ``cache_dir`` updated under ``flock``."""
    import fcntl

    now = time.time()
    path = get_settings().cache_dir / "agent_rate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _hits_lock, open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                data = json.loads(f.read() or "{}")
            except ValueError:
                data = {}
            data = {k: [t for t in v if now - t < 3600] for k, v in data.items()}
            data = {k: v for k, v in data.items() if v}
            q = data.setdefault(key[:64], [])
            if len(q) >= per_hour:
                raise APIError(429, "rate_limited", "too many analyst requests, try again later")
            if per_minute and sum(1 for t in q if now - t < 60) >= per_minute:
                e = APIError(429, "rate_limited_burst", "too many analyst requests in a minute")
                e.headers = {"Retry-After": "60"}
                raise e
            q.append(now)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(data))
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def client_ip(request: Request) -> str:
    """Socket peer, or the visitor's IP from CF-Connecting-IP / X-Forwarded-For when the peer is a trusted proxy."""
    peer = request.client.host if request.client else "?"
    if peer in get_settings().agent_trusted_proxies:
        fwd = request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0]
        if fwd.strip():
            return fwd.strip()[:64]
    return peer


@router.get("/tools")
def list_tools(x_uhd_team_token: str | None = Header(None)) -> dict:
    s = get_settings()
    team = _is_team(x_uhd_team_token)
    return {
        "configured": s.agent_configured, "model": s.agent_model, "team": team,
        "sandbox_enabled": s.agent_sandbox_enabled,
        "public_enabled": s.agent_public_enabled,
        "effort": loop.tier_params(team, s)["effort"],
        "server_tools": ["web_search_20260209", "web_fetch_20260209"] if loop.tier_params(team, s)["web"] else [],
        "budget": {"daily_usd": spend.daily_budget("team" if team else "public", s),
                   "exhausted": spend.spent_today("team" if team else "public", s)
                   >= spend.daily_budget("team" if team else "public", s)},
        "tools": [{**t.schema(), "public": t.public, "rest": t.rest,
                   "enabled": t in tools.available_tools(team, s.agent_sandbox_enabled)} for t in tools.TOOLS],
    }


@router.post("/chat")
def chat(req: ChatRequest, request: Request, x_uhd_team_token: str | None = Header(None)):
    s = get_settings()
    if not s.agent_configured:
        raise loop.not_configured()
    team = _is_team(x_uhd_team_token)
    tier = "team" if team else "public"
    if not team and not s.agent_public_enabled:
        raise APIError(503, "agent_team_only", "the analyst is available to the team only for now")
    spend.check_budget(tier, s)  # → 503 agent_budget_exhausted (Retry-After until 00:00 UTC)
    if not team:
        _rate_limit(client_ip(request), s.agent_public_rate_per_hour,
                    s.agent_public_burst_per_minute)
    spend.count_request(tier, s)
    gen = loop.run_chat([m.model_dump() for m in req.messages], team=team, context=req.context)

    def sse():
        try:
            for ev in gen:
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        except APIError as e:
            yield f"event: error\ndata: {json.dumps(e.body(), ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
