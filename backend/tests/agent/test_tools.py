from __future__ import annotations

import json

import jsonschema
import pytest

from tests.conftest import POZNIAKY
from uhd.agent import loop, sandbox, tools
from uhd.config import get_settings
from uhd.errors import APIError


def test_schemas_are_valid_json_schema():
    for t in tools.TOOLS:
        jsonschema.Draft202012Validator.check_schema(t.input_schema)
        assert t.input_schema["type"] == "object" and t.description


def test_expected_tool_names():
    names = {t.name for t in tools.TOOLS}
    assert {"list_reports", "get_report", "list_scenes", "get_scene_stats", "zone_timeseries", "land_change",
            "rank_zones", "climate_projection", "get_weather", "create_report", "set_map_view",
            "run_analysis"} <= names


def test_public_vs_team_tool_sets():
    pub = {t.name for t in tools.available_tools(team=False, sandbox_enabled=True)}
    team_off = {t.name for t in tools.available_tools(team=True, sandbox_enabled=False)}
    team_on = {t.name for t in tools.available_tools(team=True, sandbox_enabled=True)}
    assert "run_analysis" not in pub and "run_analysis" not in team_off and "run_analysis" in team_on


def test_tools_use_same_numbers_as_rest(client):
    rest = client.post("/api/analyze", json={"place_id": "kyiv-pozniaky"}).json()
    res, err = tools.execute("create_report", {"place_id": "kyiv-pozniaky"})
    assert not err and res["report_id"] == rest["report_id"] and res["gap_summary"] == rest["gap_summary"]
    ts, err = tools.execute("zone_timeseries", {"report_id": rest["report_id"], "variables": ["gap"]})
    assert [r["gap"] for r in ts["series"]] == [s["gap"] for s in rest["series"]]
    rep, _ = tools.execute("get_report", {"report_id": rest["report_id"]})
    assert "geometry" not in rep["params"] and rep["trend"] == rest["trend"]
    lc, _ = tools.execute("land_change", {"report_id": rest["report_id"]})
    assert lc["land_change"] == rest["land_change"]
    lst, _ = tools.execute("list_reports", {})
    assert lst["reports"][0]["report_id"] == rest["report_id"]


def test_rank_zones(client):
    res, err = tools.execute("rank_zones", {"metric": "gap_last", "place_ids": ["kyiv-pozniaky", "kyiv-teremky"]})
    assert not err and [r["rank"] for r in res["ranking"]] == [1, 2]
    vals = [r["value"] for r in res["ranking"]]
    assert vals == sorted(vals, reverse=True)
    allc, err = tools.execute("rank_zones", {"metric": "all", "place_ids": ["kyiv-pozniaky", "kyiv-teremky"]})
    assert not err and allc["sorted_by"] == "gap_mean" and len(allc["zones"]) == 2
    z = allc["zones"][0]
    assert {"gap_mean", "gap_last", "trend_per_decade", "trend_verdict", "ndvi_trend_per_decade", "new_built_km2",
            "report_id", "place_id", "excluded_years"} <= set(z)
    assert allc["zones"][0]["gap_mean"] >= allc["zones"][1]["gap_mean"]


def test_scene_tools_and_map_view(client):
    sc, err = tools.execute("list_scenes", {"place_id": "kyiv-pozniaky", "year": 2013})
    assert not err and sc["count"] > 0
    st, err = tools.execute("get_scene_stats", {"scene_id": sc["scenes"][0]["id"], "place_id": "kyiv-pozniaky"})
    assert not err and st["zone_lst"] is not None
    mv, err = tools.execute("set_map_view", {"layer": "gap", "year": 2025, "place_ids": ["kyiv-pozniaky"]})
    assert not err and mv["map_view"]["layer"] == "gap"


def test_invalid_input_and_unknown_tool():
    res, err = tools.execute("get_report", {"report_id": "nope"})
    assert err and res["error"] == "invalid_input"
    res, err = tools.execute("get_report", {"report_id": "0123456789abcdef"})
    assert err and res["error"] == "report_not_found"
    res, err = tools.execute("bogus", {})
    assert err and res["error"] == "unknown_tool"


def test_sandbox_disabled_by_default():
    res, err = tools.execute("run_analysis", {"code": "print(1)"})
    assert err and res["error"] == "sandbox_disabled"


def test_sandbox_runs_with_limits_when_forced():
    out = sandbox.run("import numpy as np\nprint(len(REPORTS), np.arange(3).sum())", [{"a": 1}], force=True,
                      require_isolation=False)
    assert out["ok"] and out["stdout"].split() == ["1", "3"]
    out = sandbox.run("open('x.txt','w').write('hi')", [], force=True, require_isolation=False)
    assert not out["ok"]  # cannot write (read-only cwd / RLIMIT_FSIZE=0)


def test_sandbox_requires_isolation_off_linux():
    import sys

    if sys.platform.startswith("linux"):
        pytest.skip("isolation may be available")
    with pytest.raises(APIError) as e:
        sandbox.run("print(1)", [], force=True)
    assert e.value.code == "sandbox_unavailable"


def test_agent_endpoints_inert_without_key(client):
    b = client.get("/api/agent/tools").json()
    assert b["configured"] is False and any(t["name"] == "get_report" for t in b["tools"])
    r = client.post("/api/agent/chat", json={"messages": [{"role": "user", "content": "Привіт"}]})
    assert r.status_code == 503 and r.json()["error"] == "agent_not_configured"


def test_build_tools_caching_and_server_tools():
    pub = loop.build_tools(team=False, s=get_settings())
    assert not any("type" in t for t in pub)  # public: no web tools (plan §10 #5)
    team = loop.build_tools(team=True, s=get_settings())
    assert team[0]["type"] == "web_search_20260209" and team[1]["type"] == "web_fetch_20260209"
    for ts in (pub, team):
        assert ts[-1]["cache_control"] == {"type": "ephemeral"}
        assert all(t.get("eager_input_streaming") for t in ts if "input_schema" in t)
        assert sum("cache_control" in t for t in ts) == 1
        json.dumps(ts)
    assert loop.build_tools(team=False, s=get_settings()) == pub  # byte-stable between requests
    sysb = loop.build_system()
    assert "cache_control" not in sysb[0] and sysb[1]["cache_control"] == {"type": "ephemeral"}


def test_execute_refuses_tools_outside_allowed_set():
    allowed = {t.name for t in tools.available_tools(team=False, sandbox_enabled=True)}
    res, err = tools.execute("run_analysis", {"code": "print(1)"}, allowed)
    assert err and res["error"] == "tool_not_allowed"
    res, err = tools.execute("get_report", {"report_id": "0123456789abcdef"}, allowed)
    assert err and res["error"] == "report_not_found"  # allowed tools still run


def test_sandbox_timeout_kills_forked_children(monkeypatch, tmp_path):
    import os
    import time

    monkeypatch.setenv("UHD_AGENT_SANDBOX_TIMEOUT_S", "1")
    get_settings.cache_clear()
    marker = tmp_path / "alive"
    code = (f"import os, time\nif os.fork() == 0:\n    time.sleep(3)\n    os.system('echo x > {marker}')\n"
            "    os._exit(0)\ntime.sleep(30)\n")
    t0 = time.time()
    out = sandbox.run(code, [], force=True, require_isolation=False)
    assert out == {"ok": False, "error": "timeout", "timeout_s": 1.0} and time.time() - t0 < 5
    time.sleep(3.5)
    assert not marker.exists()  # the grandchild died with the process group
    get_settings.cache_clear()


def test_get_report_tool_words_report_like_rest_and_timeseries_has_excluded(client):
    rep = client.post("/api/analyze", json={"geometry": client.get("/api/places/kyiv-pozniaky").json()["geometry"]}).json()
    rest = client.get(f"/api/reports/{rep['report_id']}").json()
    tool, err = tools.execute("get_report", {"report_id": rep["report_id"]})
    assert not err and tool["verdict_text_uk"] == rest["verdict_text_uk"]  # SCI-05
    ts, err = tools.execute("zone_timeseries", {"report_id": rep["report_id"], "variables": ["gap"]})
    assert not err and all("excluded" in r for r in ts["series"])  # SCI-06
    ts, err = tools.execute("zone_timeseries", {"report_id": rep["report_id"], "variables": ["excluded"]})
    assert not err


def test_agent_rate_limit_is_shared_through_a_file(client, monkeypatch):
    from uhd.api.routes import agent as ag

    for _ in range(3):
        ag._rate_limit("1.2.3.4", 3)
    with pytest.raises(APIError) as e:
        ag._rate_limit("1.2.3.4", 3)
    assert e.value.code == "rate_limited"
    data = json.loads((get_settings().cache_dir / "agent_rate.json").read_text())
    assert len(data["1.2.3.4"]) == 3  # another worker reads the same file
    ag._rate_limit("5.6.7.8", 3)


def test_agent_context_size_limited(client):
    r = client.post("/api/agent/chat", json={"messages": [{"role": "user", "content": "x"}], "context": {"a": "x" * 5000}})
    assert r.status_code == 422


def _fake_overview(monkeypatch):
    rows = [
        {"place_id": "osm:R1", "name": "Рівне", "kind": "city", "oblast": "Рівненська область", "gap_mean": 3.0,
         "trend": {"verdict": "significant"}, "report_id": "a" * 16},
        {"place_id": "osm:R2", "name": "Сарни", "kind": "city", "oblast": "Рівненська область", "gap_mean": 1.0,
         "trend": {"verdict": "not_significant"}},
        {"place_id": "osm:R3", "name": "Сімферополь", "kind": "city", "oblast": "Республіка Крим", "gap_mean": 5.0,
         "trend": {"verdict": "not_significant"}, "occupied": {"name": "АР Крим"}, "caveats": ["occupied"]},
        {"place_id": "sevastopol", "name": "Севастополь", "kind": "city", "oblast": "Севастополь", "gap_mean": 7.0,
         "trend": {"verdict": "significant"}},
        {"place_id": "kyiv", "name": "Київ", "kind": "city", "oblast": "Київ", "gap_mean": 4.0, "trend": {}},
    ]
    monkeypatch.setattr(tools, "_overview_doc", lambda: {"version": "v", "method_version": "m", "years": [2013, 2025],
                                                         "places": rows})


@pytest.mark.parametrize("q,stems", [("Crimea", ["крим", "севастопол"]), ("rivnenska", ["рівнен"]),
                                     ("Rivne oblast", ["рівнен"]), ("Рівненська область", ["рівнен"]),
                                     ("Kyiv", ["київ"]), ("Kyiv oblast", ["київська"]), ("Atlantis", [])])
def test_resolve_region(q, stems):
    assert tools.resolve_region(q) == stems


def test_compare_regions(monkeypatch):
    _fake_overview(monkeypatch)
    res, err = tools.execute("compare_regions", {"oblasts": ["Crimea", "Rivne oblast", "Atlantis"]})
    assert not err and res["unresolved"] == ["Atlantis"]
    crimea, rivne = res["regions"]
    assert crimea["n_places"] == 2 and crimea["occupied"] is True and crimea["gap_mean_median"] == 6.0
    assert crimea["hottest_places"][0]["name"] == "Севастополь" and crimea["n_significant_trend"] == 1
    assert crimea["caveats"] == [{"code": "occupied"}] and "destruction" in crimea["agent_note"]
    assert rivne["n_places"] == 2 and rivne["gap_mean_median"] == 2.0 and rivne["occupied"] is False
    assert rivne["places_covered"] == 2 and "coverage_note" in rivne and "coverage_note" in crimea
    assert rivne["share_significant_trend_pct"] == 50 and "caveats" not in rivne
    from uhd.agent.caveats import check_caveats

    assert [m.code for m in check_caveats("Розрив 5 °C, поверхня.", [res])] == ["war_zone"]


def test_compare_regions_registered_public():
    assert "compare_regions" in {t.name for t in tools.available_tools(team=False, sandbox_enabled=False)}


def test_compare_regions_no_coverage_note_when_enough_places(monkeypatch):
    _fake_overview(monkeypatch)
    doc = tools._overview_doc()
    doc["places"] += [{"place_id": f"osm:X{i}", "name": f"М{i}", "oblast": "Рівненська область", "gap_mean": 2.0 + i}
                      for i in range(2)]
    monkeypatch.setattr(tools, "_overview_doc", lambda: doc)
    reg = tools.execute("compare_regions", {"oblasts": ["Rivne"]})[0]["regions"][0]
    assert reg["places_covered"] == 4 and "coverage_note" not in reg


def test_prompt_demands_coverage_statement():
    from uhd.agent.prompts import SYSTEM_PROMPT

    assert "places_covered" in SYSTEM_PROMPT and "below 3" in SYSTEM_PROMPT
