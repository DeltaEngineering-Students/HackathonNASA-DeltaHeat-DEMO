"""Documented colour scales for the map layers (also exposed in /api/meta).

``gap`` stops are exactly the F7 design stops (map.py): heat orange→magenta for hotter-than-forest,
muted sage for cooler-than-forest; ultramarine (#1D3FBF / #7F9BFF) is reserved for the forest reference outline.
Values outside the domain are clamped; no-data is fully transparent.
"""

from __future__ import annotations

import numpy as np

Stop = tuple[float, tuple[int, int, int]]

SCALES: dict[str, dict] = {
    "gap": {
        "title_uk": "Різниця з лісом навколо міста (LST зони − LST еталону)", "unit": "°C", "kind": "diverging",
        # −6…+16: the hottest districts reach 13 °C (single pixels more); at +12 up to half of built pixels saturated
        "domain": [-6, 16], "neutral": 0,
        "stops": {
            # F7 hues; light: sage → off-white → peach → orange → pink → magenta → deep plum
            "light": [(-6, (92, 140, 122)), (-2, (206, 220, 212)), (0, (240, 239, 236)), (2, (250, 224, 200)),
                      (5, (252, 170, 112)), (8, (234, 84, 140)), (12, (128, 18, 96)), (16, (64, 6, 52))],
            # dark: lightness rises monotonically with heat and hue steps orange → coral → magenta → pale pink,
            # so 6 / 9 / 12 / 15 °C read as different colours (the old ramp was pink from 7 to 12 °C)
            # near-zero stops lifted above the dark basemap land (#1C2438, L*≈14) to L*≈29–36 (ΔL ≥ 14), opaque:
            # transparent means «немає даних», so a ≈0 gap must never look like a hole (MAP-TASKS 5, PM 15.11)
            "dark": [(-6, (50, 96, 86)), (-2, (0x34, 0x46, 0x5A)), (0, (0x42, 0x4A, 0x60)), (1, (0x5A, 0x4A, 0x50)),
                     (2, (0x6A, 0x4E, 0x48)), (4, (140, 72, 38)), (6, (204, 110, 40)), (9, (232, 84, 96)), (12, (210, 60, 150)),
                     (16, (250, 196, 232))],
        },
    },
    "lst": {
        "title_uk": "Денна температура поверхні (LST), медіана за літо", "unit": "°C", "kind": "sequential",
        "domain": [15, 50],
        "stops": {
            "light": [(15, (92, 140, 122)), (22, (206, 220, 212)), (27, (240, 239, 236)), (31, (250, 224, 200)),
                      (36, (252, 170, 112)), (42, (234, 84, 140)), (50, (128, 18, 96))],
            "dark": [(15, (50, 96, 86)), (22, (30, 46, 58)), (27, (26, 32, 52)), (31, (78, 46, 48)),
                     (36, (196, 92, 44)), (42, (214, 58, 128)), (50, (240, 120, 186))],
        },
    },
    "ndvi": {
        "title_uk": "Зелень (NDVI), медіана за літо", "unit": "", "kind": "sequential", "domain": [0, 0.9],
        "stops": {
            # item 29 (Костопіль read as forest): neutral grey-beige up to ~0.3 (sealed / bare / dry), green only from
            # ~0.4, forest green at 0.8+; a town with gardens (~0.4–0.6) stays visibly lighter than closed forest
            "light": [(0.0, (240, 239, 236)), (0.3, (222, 214, 192)), (0.4, (204, 212, 176)), (0.6, (150, 186, 136)),
                      (0.8, (52, 112, 76)), (0.9, (28, 76, 56))],
            "dark": [(0.0, (26, 32, 52)), (0.3, (70, 66, 60)), (0.4, (64, 84, 66)), (0.6, (70, 120, 88)),
                     (0.8, (120, 186, 128)), (0.9, (168, 216, 166))],
        },
    },
    "dndvi": {
        "title_uk": "Зміна зелені (NDVI року − NDVI базового року)", "unit": "", "kind": "diverging",
        "domain": [-0.3, 0.3], "neutral": 0,
        "stops": {
            "light": [(-0.3, (128, 18, 96)), (-0.15, (234, 84, 140)), (-0.05, (250, 224, 200)), (0, (240, 239, 236)),
                      (0.05, (206, 220, 212)), (0.15, (120, 170, 130)), (0.3, (32, 84, 70))],
            "dark": [(-0.3, (240, 120, 186)), (-0.15, (214, 58, 128)), (-0.05, (78, 46, 48)), (0, (26, 32, 52)),
                     (0.05, (30, 46, 58)), (0.15, (72, 128, 100)), (0.3, (170, 214, 170))],
        },
    },
}
REFERENCE_COLOR = {"light": "#1D3FBF", "dark": "#7F9BFF"}
THEMES = ("light", "dark")


def version() -> str:
    """Short hash of all scales: part of the tile cache key and of ``tiles_version`` (palette change → new tiles)."""
    import hashlib
    import json

    return hashlib.sha256(json.dumps(SCALES, sort_keys=True).encode()).hexdigest()[:8]


def _hex(c: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % c


def meta() -> dict:
    out = {}
    for k, s in SCALES.items():
        out[k] = {kk: vv for kk, vv in s.items() if kk != "stops"}
        out[k]["stops"] = {th: [{"value": v, "color": _hex(c)} for v, c in st] for th, st in s["stops"].items()}
    return out


_LUT_N = 1024
_luts: dict[tuple[str, str], np.ndarray] = {}


def lut(layer: str, theme: str) -> tuple[np.ndarray, float, float]:
    """1024-entry RGB lookup over the domain."""
    s = SCALES[layer]
    lo, hi = s["domain"]
    key = (layer, theme)
    if key not in _luts:
        st = s["stops"][theme]
        xs = np.linspace(lo, hi, _LUT_N)
        sx = [v for v, _ in st]
        _luts[key] = np.stack([np.interp(xs, sx, [c[i] for _, c in st]) for i in range(3)], -1).round().astype(np.uint8)
    return _luts[key], lo, hi


def colorize(values: np.ndarray, layer: str, theme: str = "light") -> np.ndarray:
    """float array (NaN = no data) → RGBA uint8."""
    table, lo, hi = lut(layer, theme)
    valid = np.isfinite(values)
    idx = np.clip(((np.where(valid, values, lo) - lo) / (hi - lo) * (_LUT_N - 1)).round(), 0, _LUT_N - 1).astype(np.int32)
    rgba = np.zeros(values.shape + (4,), np.uint8)
    rgba[..., :3] = table[idx]
    rgba[..., 3] = np.where(valid, 255, 0)
    return rgba


PALETTE_LEVELS = 127  # index 0 = transparent no-data, 1…127 = the scale (≈0.17 °C per step for gap)


def indexed(values: np.ndarray, layer: str, theme: str = "light") -> tuple[np.ndarray, bytes]:
    """float array → (uint8 index image, 128-colour RGB palette) for a palette PNG (RB-03: ~5× smaller tiles)."""
    s = SCALES[layer]
    lo, hi = s["domain"]
    st = s["stops"][theme]
    xs = np.linspace(lo, hi, PALETTE_LEVELS)
    sx = [v for v, _ in st]
    pal = np.stack([np.interp(xs, sx, [c[i] for _, c in st]) for i in range(3)], -1).round().astype(np.uint8)
    valid = np.isfinite(values)
    idx = np.clip(((np.where(valid, values, lo) - lo) / (hi - lo) * (PALETTE_LEVELS - 1)).round(), 0,
                  PALETTE_LEVELS - 1).astype(np.uint8) + 1
    idx[~valid] = 0
    return idx, bytes(3) + pal.tobytes()
