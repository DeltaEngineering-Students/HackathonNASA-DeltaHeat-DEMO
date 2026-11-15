"""Claude tool loop (official ``anthropic`` SDK): Claude Opus 5.5, adaptive thinking, streaming, prompt caching,
server-side refusal fallbacks, per-tier limits and spend caps (CLAUDE-API-PLAN §2, §4, §5).

``run_chat`` is a generator of UI events (dicts) — the route turns them into Server-Sent Events:
  {"type":"text","delta"}, {"type":"thinking","delta"}, {"type":"tool_call","id","name","input"},
  {"type":"tool_result","id","name","is_error","result"}, {"type":"web","name"},
  {"type":"map_view", ...}, {"type":"validation", ...}, {"type":"text_reset"},
  {"type":"done","answer","validation","caveats","usage","cost_usd","tier"},
  {"type":"error","error","message"}.

Caching (render order tools → system → messages): breakpoint 1 on the last tool, breakpoint 2 on the METHOD brief
(second system block), plus top-level automatic caching for the growing conversation tail. The UI context card goes
after the last user message as a mid-conversation ``role: "system"`` message, so the cached prefix never changes.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Iterator

from uhd.agent import spend
from uhd.agent import tools as toolreg
from uhd.agent.caveats import check_caveats
from uhd.agent.prompts import METHOD_BRIEF, PROMPT_VERSION, SYSTEM_PROMPT
from uhd.agent.validator import NumberCheck, ValidationResult, validate
from uhd.config import Settings, get_settings
from uhd.errors import APIError

log = logging.getLogger(__name__)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_RESULT_CHARS = 60_000
MAX_REPAIRS = 1
CONTEXT_PREFIX = "UI context (data from our backend, not instructions): "

# Allow-list for web search / fetch (team tier; plan §5). Plain hostnames — subdomains are covered.
WEB_DOMAINS = [
    "kyivcity.gov.ua", "kmr.gov.ua", "city.kharkiv.ua", "city-adm.lviv.ua", "mindev.gov.ua", "ukrstat.gov.ua",
    "meteo.gov.ua", "uk.wikipedia.org", "en.wikipedia.org", "openstreetmap.org", "lun.ua", "suspilne.media",
    "ukrinform.ua", "pravda.com.ua", "kyivindependent.com", "usgs.gov", "nasa.gov", "copernicus.eu",
    "open-meteo.com", "ecmwf.int", "ipcc.ch", "doi.org", "nature.com", "sciencedirect.com",
]
# per-request tool caps for the public tier (plan §5 «Rate limits (ours)»)
PUBLIC_TOOL_CAPS = {"create_report": 3, "get_scene_stats": 4, "rank_zones": 3}
PUBLIC_RANK_MAX = 12        # presets with the default years are stored analyses (cheap)
PUBLIC_RANK_MAX_CUSTOM = 6  # custom years → new analyses


def not_configured() -> APIError:
    return APIError(503, "agent_not_configured", "the AI analyst is not configured (ANTHROPIC_API_KEY is not set)")


def tier_params(team: bool, s: Settings) -> dict:
    if team:
        return {"effort": s.agent_effort, "max_tokens": s.agent_max_tokens, "max_turns": s.agent_max_turns,
                "web": s.agent_web_team, "web_max_uses": s.agent_web_max_uses}
    return {"effort": s.agent_effort_public, "max_tokens": s.agent_max_tokens_public,
            "max_turns": s.agent_max_turns_public, "web": s.agent_web_public, "web_max_uses": 2}


def build_tools(team: bool, s: Settings) -> list[dict]:
    """Fixed order (byte-stable per tier): server web tools (if on), then our tools; breakpoint on the last one."""
    p = tier_params(team, s)
    out: list[dict] = []
    if p["web"]:
        out += [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": p["web_max_uses"],
             "allowed_domains": WEB_DOMAINS},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": p["web_max_uses"],
             "allowed_domains": WEB_DOMAINS, "max_content_tokens": 8000},
        ]
    for t in toolreg.available_tools(team, s.agent_sandbox_enabled):
        out.append({**t.schema(), "eager_input_streaming": True})
    out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def build_system() -> list[dict]:
    return [{"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": METHOD_BRIEF, "cache_control": {"type": "ephemeral"}}]


def _client(s: Settings):
    import anthropic

    return anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=2, timeout=s.agent_timeout_s)


# ------------------------------------------------------------------ context card
def context_card(context: dict | None) -> dict | None:
    """Compact facts about what the user is looking at (report headline, trends, caveat codes) — also a validator
    source, so a question about the open report needs no tool call."""
    if not context:
        return None
    from uhd.services import reports

    card: dict[str, Any] = {k: context.get(k) for k in ("report_id", "place_id", "layer", "year")
                            if context.get(k) is not None}
    card["lang"] = context.get("lang") if context.get("lang") in ("en", "uk") else "uk"
    rid = context.get("report_id")
    rep = reports.get(rid) if isinstance(rid, str) and reports.valid_id(rid) else None
    if rep:
        z = rep.get("zone") or {}
        card["report"] = {
            "summary": reports.summary(rep),
            "zone": {k: z.get(k) for k in ("name", "area_km2", "basis", "city", "occupied", "war_region")},
            "gap_summary": rep.get("gap_summary"),
            **{k: _trend(rep.get(k)) for k in ("trend", "ref_trend", "zone_trend", "ndvi_trend")},
            "gap_driver": rep.get("gap_driver"),
            "series": [{"year": r.get("year"), "gap": r.get("gap"), "excluded": r.get("excluded")}
                       for r in rep.get("series") or []],
            "caveats": [{"code": c.get("code")} for c in rep.get("caveats") or [] if isinstance(c, dict)],
            "years": rep.get("years"), "data_version": rep.get("data_version"),
            "method_version": rep.get("method_version"),
        }
    elif rid:
        card["report_note"] = "report not found"
    return card or None


def _trend(t: Any) -> Any:
    if not isinstance(t, dict):
        return t
    return {k: t.get(k) for k in ("slope_per_decade", "ci95", "p", "n_years", "verdict")}


def _to_messages(history: list[dict], card: dict | None, as_user_text: bool = False) -> list[dict]:
    msgs = [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]
    if card and msgs and msgs[-1]["role"] == "user":
        txt = CONTEXT_PREFIX + json.dumps(card, ensure_ascii=False, sort_keys=True, default=str)
        if as_user_text:  # fallback when a (fallback) model rejects mid-conversation system messages
            msgs[-1] = {"role": "user", "content": f"{msgs[-1]['content']}\n\n[{txt}]"}
        else:
            msgs.append({"role": "system", "content": txt})
    return msgs


# ------------------------------------------------------------------ validation
def _web_texts(content: list[Any]) -> list[str]:
    """Text of web search / fetch results — a separate source class: numbers there never count as our data."""
    out = []
    for b in content:
        if getattr(b, "type", "") in ("web_fetch_tool_result", "web_search_tool_result"):
            try:
                c = b.content
                c = c.model_dump() if hasattr(c, "model_dump") else (
                    [x.model_dump() if hasattr(x, "model_dump") else x for x in c] if isinstance(c, list) else c)
                out.append(json.dumps(c, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001
                pass
    return out


_HYP = ("гіпотези з інтернету", "hypotheses from the web")


def validate_answer(answer: str, data: list[Any], web: list[str], question: str) -> ValidationResult:
    """Data part (before «Гіпотези з інтернету») must match our data sources only. In the web part a number may match
    a web source only in a paragraph that carries an https link; otherwise it must match our data too."""
    low = answer.lower()
    cut = min([i for i in (low.find(h) for h in _HYP) if i >= 0], default=-1)
    if cut < 0 or not web:
        return validate(answer, data, question=question)
    checks: list[NumberCheck] = list(validate(answer[:cut], data, question=question).checked)
    for par in answer[cut:].split("\n\n"):
        srcs = data + web if "https://" in par else data
        checks += validate(par, srcs, question=question).checked
    return ValidationResult(all(c.sourced for c in checks), checks)


def _repair_message(v: ValidationResult, missing: list) -> str:
    parts = ["[automatic check]"]
    if not v.ok:
        bad = ", ".join(c.text for c in v.unsourced)
        parts.append(f"These numbers in your answer were not found in any tool result of this conversation: {bad}. "
                     "Use only numbers returned by tools (call tools if needed), or remove those numbers. Numbers "
                     "from web pages are allowed only under «Гіпотези з інтернету» next to their link.")
    if missing:
        parts.append("Missing or wrong required wording: " + " ".join(f"({m.code}) {m.message}" for m in missing))
    parts.append("Rewrite the whole answer. Do not mention this check, the validator or number formats in the answer.")
    return " ".join(parts)


# ------------------------------------------------------------------ tool guard (public tier)
def guard_tool(name: str, args: dict, team: bool, context: dict | None, counts: dict[str, int]) -> dict | None:
    """Return an error result if this call is over the caller's limits, else None."""
    counts[name] = counts.get(name, 0) + 1
    if team:
        return None
    if name in ("create_report", "rank_zones"):
        from uhd.services import places

        presets = {**places.presets(), **places.city_shortcuts()}
        pids = [args["place_id"]] if args.get("place_id") else list(args.get("place_ids") or [])
        rank_max = PUBLIC_RANK_MAX_CUSTOM if args.get("years") else PUBLIC_RANK_MAX
        if name == "rank_zones" and len(pids) + len(args.get("report_ids") or []) > rank_max:
            return {"error": "tool_limit", "message": f"at most {rank_max} zones"}
        if any(p not in presets for p in pids):
            return {"error": "presets_only", "message": "new analyses are limited to preset places (use search_places "
                                                       "ids of districts / cities) or the user's current report"}
        if name == "create_report":
            if args.get("geometry"):
                return {"error": "presets_only", "message": "custom geometry is not available here; use a preset "
                                                           "place_id or the user's current report"}
            rid = args.get("report_id")
            if rid and rid != (context or {}).get("report_id"):
                return {"error": "presets_only", "message": "only the user's current report can be re-run"}
    cap = PUBLIC_TOOL_CAPS.get(name)
    if cap is not None and counts[name] > cap:
        return {"error": "tool_limit", "message": f"{name} may be called at most {cap} times per question"}
    return None


WRAPUP = ("[automatic notice] The step budget is used up; no more tools are available. Answer the user's question "
          "now from the tool results already in this conversation (numbers only from them), concisely. Say in one "
          "short sentence what you could not cover. Keep every required caveat (surface not air, verdict wording, "
          "occupation / war). Do not mention this notice.")


def _with_wrapup(messages: list[dict]) -> list[dict]:
    """Add the wrap-up instruction after the last message (as a text block of the last user turn when it is one)."""
    last = messages[-1]
    if last["role"] == "user" and isinstance(last["content"], list):
        return messages[:-1] + [{"role": "user", "content": [*last["content"], {"type": "text", "text": WRAPUP}]}]
    return messages + [{"role": "user", "content": WRAPUP}]


# ------------------------------------------------------------------ the loop
def run_chat(history: list[dict], *, team: bool = False, context: dict | None = None,
             settings: Settings | None = None, client: Any = None) -> Iterator[dict]:
    s = settings or get_settings()
    if not s.agent_configured and client is None:
        raise not_configured()
    import anthropic

    tier = "team" if team else "public"
    p = tier_params(team, s)
    client = client or _client(s)
    card = context_card(context)
    messages = _to_messages(history, card)
    users = [m for m in messages if m["role"] == "user"]
    if not users or not (messages[-1]["role"] == "user" or (messages[-1]["role"] == "system" and
                                                             messages[-2]["role"] == "user")):
        raise APIError(422, "invalid_request", "the last message must be from the user")
    question = users[-1]["content"] if isinstance(users[-1]["content"], str) else ""
    allowed = frozenset(t.name for t in toolreg.available_tools(team, s.agent_sandbox_enabled))
    data_sources: list[Any] = [card] if card else []
    web_sources: list[str] = []
    usage = {k: 0 for k in spend.USAGE_KEYS}
    cost = 0.0
    cap = spend.request_cap(tier, s)
    counts: dict[str, int] = {}
    called: list[str] = []
    repairs = json_retries = 0
    sys_fallback = False
    rid = uuid.uuid4().hex[:12]
    t0 = time.time()
    kwargs: dict[str, Any] = dict(
        model=s.agent_model, max_tokens=p["max_tokens"], system=build_system(), tools=build_tools(team, s),
        thinking={"type": "adaptive", "display": "summarized"}, output_config={"effort": p["effort"]},
        cache_control={"type": "ephemeral"},
    )
    if s.agent_fallbacks:
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    result: dict[str, Any] = {"error": None, "answer": "", "validation": None, "caveats": None}

    def finish(ev: dict) -> dict:
        result["error"] = ev.get("error") if ev["type"] == "error" else None
        spend.log_request({"request_id": rid, "model": s.agent_model, "prompt_version": PROMPT_VERSION,
                           "effort": p["effort"], "tools": called, "usage": usage, "cost_usd": round(cost, 4),
                           "repairs": repairs, "validation_ok": (result["validation"] or {}).get("ok"),
                           "caveats_missing": [m["code"] for m in result["caveats"] or []],
                           "error": result["error"], "ms": int((time.time() - t0) * 1000)},
                          tier=tier, question=question, answer=result["answer"], s=s)
        return ev

    for _turn in range(p["max_turns"]):
        try:
            with client.beta.messages.stream(messages=messages, **kwargs) as stream:
                for ev in stream:
                    et = getattr(ev, "type", "")
                    if et == "text":
                        yield {"type": "text", "delta": ev.text}
                    elif et == "thinking":
                        yield {"type": "thinking", "delta": ev.thinking}
                    elif et == "content_block_start" and getattr(ev.content_block, "type", "") == "server_tool_use":
                        yield {"type": "web", "name": ev.content_block.name}
                msg = stream.get_final_message()
            json_retries = 0
        except ValueError:  # tool input JSON the SDK could not parse at all → re-issue the turn
            json_retries += 1
            if json_retries > 2:
                yield finish({"type": "error", "error": "invalid_tool_json", "message": "model produced invalid "
                                                                                       "tool input"})
                return
            yield {"type": "text_reset"}
            continue
        except anthropic.RateLimitError:
            yield finish({"type": "error", "error": "rate_limited", "message": "Claude API rate limit"})
            return
        except anthropic.BadRequestError as e:
            if card and not sys_fallback and "system" in str(e).lower():
                sys_fallback = True  # model without mid-conversation system messages → card as user text
                messages = _to_messages(history, card, as_user_text=True)
                continue
            log.warning("claude api 400", extra={"err": str(e)[:300]})
            yield finish({"type": "error", "error": "upstream_error", "message": "Claude API error 400"})
            return
        except anthropic.APIStatusError as e:
            log.warning("claude api error", extra={"status": e.status_code, "err": str(e)[:300]})
            code = "upstream_overloaded" if e.status_code in (503, 529) else "upstream_error"
            yield finish({"type": "error", "error": code, "message": f"Claude API error {e.status_code}"})
            return
        except anthropic.APIConnectionError:
            yield finish({"type": "error", "error": "upstream_unreachable", "message": "Claude API is not reachable"})
            return

        u = spend.usage_dict(getattr(msg, "usage", None) or {})
        for k in usage:
            usage[k] += u.get(k, 0)
        turn_cost = spend.cost_usd(u, s)
        cost += turn_cost
        spend.add_spend(tier, turn_cost, s)
        messages.append({"role": "assistant", "content": msg.content})
        web_sources.extend(_web_texts(msg.content))

        if msg.stop_reason == "refusal":
            yield finish({"type": "error", "error": "refused", "message": "the model declined this request"})
            return
        if msg.stop_reason == "max_tokens":
            yield finish({"type": "error", "error": "max_tokens", "message": "answer was cut off"})
            return
        if cost >= cap:
            yield finish({"type": "error", "error": "too_expensive",
                          "message": f"stopped: this answer reached the per-request cap ${cap:.2f}"})
            return
        if msg.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            answer = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
            v = validate_answer(answer, data_sources, web_sources, question)
            missing = check_caveats(answer, data_sources)
            if (not v.ok or missing) and repairs < MAX_REPAIRS:
                repairs += 1
                yield {"type": "validation", "repairing": True, **v.to_dict(),
                       "caveats": [m.to_dict() for m in missing]}
                messages.append({"role": "user", "content": _repair_message(v, missing)})
                yield {"type": "text_reset"}
                continue
            result.update(answer=answer, validation=v.to_dict(), caveats=[m.to_dict() for m in missing])
            yield finish({"type": "done", "answer": answer, "validation": v.to_dict(),
                          "caveats": result["caveats"], "usage": usage, "cost_usd": round(cost, 4), "tier": tier,
                          "request_id": rid})
            return

        results = []
        for b in tool_uses:
            args = b.input if isinstance(b.input, dict) else {}
            called.append(b.name)
            yield {"type": "tool_call", "id": b.id, "name": b.name, "input": args}
            res = guard_tool(b.name, args, team, context, counts)
            if res is not None:
                is_err = True
            else:
                res, is_err = toolreg.execute(b.name, args, allowed)
            if not is_err:
                data_sources.append(res)
            text = json.dumps(res, ensure_ascii=False, default=str)
            if len(text) > MAX_TOOL_RESULT_CHARS:
                text = text[:MAX_TOOL_RESULT_CHARS] + "…[truncated]"
            yield {"type": "tool_result", "id": b.id, "name": b.name, "is_error": is_err, "result": res}
            if b.name == "set_map_view" and not is_err:
                yield {"type": "map_view", **res["map_view"]}
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": text, "is_error": is_err})
        messages.append({"role": "user", "content": results})

    # step budget exhausted: ONE final call without tool use, answer from what was gathered (never end with nothing)
    messages = _with_wrapup(messages)
    for _attempt in range(1 + max(0, MAX_REPAIRS - repairs)):
        if cost >= cap:
            break
        try:
            with client.beta.messages.stream(messages=messages, **{**kwargs, "tool_choice": {"type": "none"}}) as st:
                for ev in st:
                    if getattr(ev, "type", "") == "text":
                        yield {"type": "text", "delta": ev.text}
                msg = st.get_final_message()
        except Exception:  # noqa: BLE001 - any failure here falls back to the old error
            log.warning("final wrap-up call failed", exc_info=True)
            break
        u = spend.usage_dict(getattr(msg, "usage", None) or {})
        for k in usage:
            usage[k] += u.get(k, 0)
        turn_cost = spend.cost_usd(u, s)
        cost += turn_cost
        spend.add_spend(tier, turn_cost, s)
        answer = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text").strip()
        if msg.stop_reason in ("refusal", "max_tokens") or not answer:
            break
        v = validate_answer(answer, data_sources, web_sources, question)
        missing = check_caveats(answer, data_sources)
        if (not v.ok or missing) and _attempt < MAX_REPAIRS - repairs and cost < cap:
            yield {"type": "validation", "repairing": True, **v.to_dict(), "caveats": [m.to_dict() for m in missing]}
            messages = messages + [{"role": "assistant", "content": msg.content},
                                   {"role": "user", "content": _repair_message(v, missing)}]
            yield {"type": "text_reset"}
            continue
        result.update(answer=answer, validation=v.to_dict(), caveats=[m.to_dict() for m in missing])
        yield finish({"type": "done", "answer": answer, "validation": v.to_dict(), "caveats": result["caveats"],
                      "usage": usage, "cost_usd": round(cost, 4), "tier": tier, "request_id": rid,
                      "wrapped_up": True})
        return
    yield finish({"type": "error", "error": "too_many_steps", "message": f"stopped after {p['max_turns']} steps"})
