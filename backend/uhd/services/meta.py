"""/api/meta payload."""

from __future__ import annotations

from uhd import __version__
from uhd.config import get_settings
from uhd.services import analysis, places, rasters, science
from uhd.tiles import palettes, pyramid, render


def meta() -> dict:
    s = get_settings()
    ys = rasters.years(s.tiles_aoi) or list(range(analysis.YEARS[0], analysis.YEARS[1] + 1))
    cities = []
    for a in rasters.CITY_AOIS:
        cities.append({"id": a, "name": rasters.CITY_NAMES_UK[a], "bbox": rasters.bbox_wgs84(a),
                       "place_id": a, "has_data": a in rasters.aois()})
    return {
        "api_version": __version__,
        "data_version": science.data_version(),
        "years": ys,
        "default_years": [ys[0], ys[-1]],
        "coverage": {"aoi": s.tiles_aoi, "bbox": rasters.bbox_wgs84(s.tiles_aoi), "crs": "EPSG:3035", "res_m": 60},
        "cities": cities,
        "layers": {
            "tile_url": "/tiles/{layer}/{year}/{z}/{x}/{y}.png?theme={theme}",
            "tiles_version": render.tiles_version(),  # append as &v= → tiles cached immutably until it changes
            "min_zoom": render.MIN_Z, "max_zoom": render.MAX_Z, "native_zoom": 11, "tile_size": render.TILE,
            "ids": [l for l in render.LAYERS if l != "nonbuilt"
                    and (not l.endswith("_fill") or (render.fill_enabled() and l in render.FILL_SERVED))],
            # item 17: layers never offered as a layer choice / never named in the UI (helpers of gap / lst)
            "internal": [l for l in ("gap_fill", "nonbuilt") if l in render.LAYERS],
            # item 13: draw ON TOP of gap (item 30: not lst) to fade everything that is not built that year; slider «Приглушити
            # не-забудову» 0–100 % = the layer's raster-opacity (default 0.7); same tiles_version/clip/sea rules
            "overlays": {"nonbuilt": ({
                "url": "/tiles/nonbuilt/{year}/{z}/{x}/{y}.png?theme={theme}", "internal": True,
                "label_uk": "Приглушити не-забудову",
                "alpha": render.NONBUILT_ALPHA, "default_strength": 0.7, "levels": render.NONBUILT_LEVELS,
                "applies_to": ["gap"],  # item 30: Температура shows the whole surface
                "colors": {th: "#%02X%02X%02X" % c for th, c in render.NONBUILT_COLOR.items()},
                "rule_uk": "Приглушено все, що в цей рік не забудова (класи Esri/IO + екстраполяція 2013–2016 і "
                           "2024–2025, як в аналізі); на дрібних масштабах — пропорційно частці забудови.",
                "warm_zooms": {"country": [9, 10], "cities": [9, 13]}} if pyramid.nonbuilt_available() else None)},
            "dndvi_base_year": render.DNDVI_BASE,
            "gap_reference_uk": "Поблизу Києва/Харкова/Львова — еталон міста (як у звітах); деінде — згладжене поле "
                                "стабільного лісу навколо (σ≈10 км). Див. METHOD.md.",
            "scales": palettes.meta(),
            "reference_color": palettes.REFERENCE_COLOR,
            "no_data": "transparent",
            # display-only fill of year-specific LST holes (median of the nearest valid summers; science gapfill.py):
            # draw under/over the base layer at lower opacity, never used by any analysis number
            "fill": ({"gap": "gap_fill", "lst": None, "internal": True, "label_uk": "заповнено з сусідніх років"}
                     if render.fill_enabled() else None),
        },
        "presets": [{k: v for k, v in p.items()} for p in places.search_presets("")],
        "limits": {"min_area_km2": s.min_area_km2, "max_area_km2": s.max_area_km2, "max_vertices": s.max_vertices,
                   "max_bbox_side_km_city": s.max_bbox_side_km, "max_bbox_side_km": s.max_bbox_side_km_derived,
                   "max_bbox_km2": s.max_bbox_km2},
        "verdict_rule": {"p_lt": analysis.P_SIGNIFICANT, "min_years": analysis.MIN_YEARS_FOR_VERDICT},
        "science_ready": science.available(),
        "agent_configured": s.agent_configured,
        "notes_uk": {
            "lst": "LST — денна температура підстильної поверхні (близько 11:00 за місцевим сонячним часом), а не приземна температура повітря (2 м).",
        },
    }
