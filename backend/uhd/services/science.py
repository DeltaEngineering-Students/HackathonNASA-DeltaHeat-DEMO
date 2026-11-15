"""Thin adapter over the data-science package ``uhd.science`` (owned by the data-science engineer).

Interface: uhd/docs/METHOD.md §0 — analyze(geometry, years, name), DATA_VERSION, list_scenes(geometry, year),
land_change, climate_projection(lat, lon), layer_raster/gap_raster (tiles), cities(), reference_for(...);
optional list_presets(). ``ScienceError(code, message_uk)`` is mapped to HTTP 422.
Everything here degrades gracefully: missing package → ``ScienceNotReady`` (HTTP 503 ``science_not_ready``),
unless UHD_SCIENCE_FAKE=1, which serves deterministic fixture reports (clearly flagged ``fixture: true``).
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from uhd.config import get_settings
from uhd.errors import APIError

log = logging.getLogger(__name__)
METHOD_VERSION_FALLBACK = "unknown"


class ScienceNotReady(APIError):
    def __init__(self, what: str = "analysis"):
        super().__init__(503, "science_not_ready", f"the {what} engine is not deployed yet")


_override: ModuleType | None = None  # tests inject a module here


def set_module(mod: ModuleType | None) -> None:
    global _override
    _override = mod


def module() -> ModuleType:
    if _override is not None:
        return _override
    if get_settings().science_fake:
        from uhd.services import science_fake

        return science_fake
    try:
        mod = importlib.import_module("uhd.science")
    except ImportError as e:
        log.debug("uhd.science not importable", extra={"err": str(e)})
        raise ScienceNotReady() from e
    if not hasattr(mod, "analyze"):
        raise ScienceNotReady()
    return mod


def available() -> bool:
    try:
        module()
        return True
    except ScienceNotReady:
        return False


def data_version() -> str:
    """Version of the derived data: science.DATA_VERSION, else ``{data_dir}/VERSION``, else 'dev'."""
    try:
        v = getattr(module(), "DATA_VERSION", None)
        if v:
            return str(v)
    except ScienceNotReady:
        pass
    p: Path = get_settings().data_dir / "VERSION"
    try:
        return p.read_text().strip() or "dev"
    except OSError:
        return "dev"


def tiles_method_version() -> str:
    try:
        return str(getattr(module(), "TILES_VERSION", "tiles"))
    except ScienceNotReady:
        return "tiles"


def method_version() -> str:
    try:
        return str(getattr(module(), "METHOD_VERSION", METHOD_VERSION_FALLBACK))
    except ScienceNotReady:
        return METHOD_VERSION_FALLBACK


def _map_error(e: Exception) -> APIError | None:
    """``uhd.science.ScienceError(code, message_uk)`` → HTTP 422 with the same code."""
    code, msg = getattr(e, "code", None), getattr(e, "message_uk", None)
    if isinstance(code, str) and isinstance(msg, str):
        return APIError(422, code, msg)
    return None


def analyze(geometry_wgs84: dict, years: tuple[int, int] | None, name: str | None = None) -> dict:
    mod = module()
    try:
        return mod.analyze(geometry_wgs84, list(years) if years else None, name=name)
    except APIError:
        raise
    except Exception as e:
        if (mapped := _map_error(e)) is not None:
            raise mapped from e
        raise


def helper(name: str, *args: Any, **kwargs: Any) -> Any:
    fn = getattr(module(), name, None)
    if fn is None:
        raise ScienceNotReady(name)
    try:
        return fn(*args, **kwargs)
    except APIError:
        raise
    except Exception as e:
        if (mapped := _map_error(e)) is not None:
            raise mapped from e
        raise


def has_helper(name: str) -> bool:
    try:
        return callable(getattr(module(), name, None))
    except ScienceNotReady:
        return False


def list_presets() -> list[dict] | None:
    if not has_helper("list_presets"):
        return None
    return helper("list_presets")
