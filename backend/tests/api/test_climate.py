import numpy as np

from uhd.config import get_settings


def _write_cmip6(root):
    d = root / "extra" / "cmip6"
    d.mkdir(parents=True)
    lat = np.arange(44, 53, 0.25, dtype=np.float32)
    lon = np.arange(22, 41, 0.25, dtype=np.float32)
    for m, off in (("A", 0.0), ("B", 1.0)):
        for scen, years, base in (("historical", range(2005, 2015), 26.0), ("ssp245", range(2041, 2051), 28.0),
                                  ("ssp245", range(2071, 2081), 29.0), ("ssp585", range(2041, 2051), 28.5),
                                  ("ssp585", range(2071, 2081), 31.0)):
            for y in years:
                shp = (len(lat), len(lon))
                np.savez(d / f"{m}_{scen}_{y}.npz", jja_mean=np.full(shp, base + off, np.float32),
                         hot30=np.full(shp, 10 if scen == "historical" else 30, np.uint8),
                         hot35=np.zeros(shp, np.uint8), lat=lat, lon=lon)


def test_climate_fallback_summary(client):
    _write_cmip6(get_settings().landsat_dir)
    b = client.get("/api/climate", params={"lat": 50.45, "lon": 30.52}).json()
    assert b["variable"] == "tasmax" and b["models"] == ["A", "B"]
    assert b["baseline"]["jja_tasmax"]["median"] == 26.5
    assert b["scenarios"]["ssp585"]["late"]["delta_jja_tasmax"] == {"median": 5.0, "min": 5.0, "max": 5.0, "n_models": 2}
    assert b["scenarios"]["ssp245"]["mid"]["delta_hot30_days"]["median"] == 20.0
    assert client.get("/api/climate", params={"lat": 10, "lon": 10}).json()["error"] == "outside_coverage"
