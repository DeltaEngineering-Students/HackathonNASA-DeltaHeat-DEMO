"""Runtime settings (environment variables, prefix ``UHD_``; ``ANTHROPIC_API_KEY`` without prefix)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UHD_", env_file=".env", extra="ignore")

    # --- data ---------------------------------------------------------------
    landsat_dir: Path = Path("/srv/landsat")  # raw composites, READ-ONLY
    data_dir: Path = Path("/root/uhd/data")  # derived data written by precompute scripts
    cache_dir: Path = Path("/root/uhd/cache")  # tiles, geocoder, weather, climate caches
    reports_dir: Path = Path("/root/uhd/reports")  # stored reports (reproducible: params + data_version)
    tiles_aoi: str = "ukraine"  # AOI whose composites back the raster tiles

    # --- web ----------------------------------------------------------------
    frontend_dist: Path = _BACKEND_DIR.parent / "frontend" / "dist"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: str = "INFO"
    log_json: bool = True
    # app origin for export links / QR when the request carries no usable host (e.g. "https://example.org")
    public_base_url: str | None = None

    # --- analysis limits ------------------------------------------------------
    min_area_km2: float = 0.5  # PLAN.md; frontend enforces the same
    max_area_km2: float = 5000.0
    max_vertices: int = 20000
    max_bbox_km2: float = 14400.0  # EPSG:3035 bbox of the whole (multi)polygon: caps raster windows (REVIEW H1)
    analyze_concurrency: int = 2             # cold science computations at once per worker (RB-01)
    max_body_bytes: int = 2_000_000          # 20 000 vertices ≈ 0.8 MB of GeoJSON (RB-05)
    tile_cache_min_free_gb: float = 40.0     # stop persisting tiles below this much free disk (RB-04)
    tile_cache_max_gb: float = 25.0          # `python -m uhd.tiles.evict` trims the cache to this size (LRU by atime)
    max_bbox_side_km: float = 150.0          # inside the Kyiv/Kharkiv/Lviv city AOIs (= science MAX_SIDE_PX)
    max_bbox_side_km_derived: float = 72.0   # elsewhere (= science MAX_SIDE_PX_DERIVED: derived reference ring)

    # --- external services ------------------------------------------------------
    user_agent: str = "UrbanHeatDetective/0.1 (NASA Space Apps 2026 hackathon prototype)"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    nominatim_min_interval_s: float = 1.1  # Nominatim usage policy: max 1 request/s
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    http_timeout_s: float = 15.0
    # science fixture mode (tests / frontend dev before the science package exists)
    science_fake: bool = False

    # --- AI analyst (decision #19) --------------------------------------------
    anthropic_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "UHD_ANTHROPIC_API_KEY")
    )
    agent_model: str = "claude-opus-5-5"
    agent_effort: str = "high"  # team tier
    agent_max_tokens: int = 64000
    agent_max_turns: int = 12
    agent_team_token: str | None = None  # header X-UHD-Team-Token → full tool set
    agent_public_rate_per_hour: int = 30
    agent_sandbox_enabled: bool = False
    agent_sandbox_timeout_s: float = 20.0
    agent_sandbox_memory_mb: int = 2048
    # interpreter for run_analysis; must be readable/executable by `nobody` (the app venv under /root is not)
    agent_sandbox_python: str | None = None
    agent_web_max_uses: int = 5
    agent_fallbacks: bool = True  # server-side refusal fallbacks (beta)
    # per-tier request parameters (CLAUDE-API-PLAN §2.5)
    agent_public_enabled: bool = True     # False → public chats get 503 agent_team_only
    agent_effort_public: str = "medium"
    agent_max_tokens_public: int = 16000
    agent_max_turns_public: int = 6
    agent_web_public: bool = False        # web search/fetch for public visitors (plan §10 #5: off)
    agent_web_team: bool = True           # team: on, allow-listed domains only
    agent_timeout_s: float = 120.0
    agent_public_burst_per_minute: int = 8
    # reverse proxies (e.g. the Cloudflare mirror's connector) whose CF-Connecting-IP / X-Forwarded-For we trust for
    # the per-IP limit; anything else uses the socket peer (UHD_AGENT_TRUSTED_PROXIES='["10.0.0.5"]')
    agent_trusted_proxies: list[str] = []
    # cost caps (USD). Prices per MTok for claude-opus-5-5 (claude-api skill, cached 2026-11-03)
    agent_price_input: float = 4.00
    agent_price_output: float = 20.00
    agent_price_cache_read: float = 0.20
    agent_price_cache_write: float = 5.00     # 5-minute TTL (1.25×)
    agent_price_web_search: float = 0.01      # $10 per 1 000 searches
    agent_daily_budget_public_usd: float = 10.0
    agent_daily_budget_team_usd: float = 20.0
    agent_request_cap_public_usd: float = 0.50
    agent_request_cap_team_usd: float = 2.00
    agent_log_days: int = 14

    @property
    def agent_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
