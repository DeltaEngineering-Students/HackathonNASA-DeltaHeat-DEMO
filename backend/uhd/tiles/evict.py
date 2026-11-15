"""Keep the tile cache bounded (RB-04): delete tile dirs of old ``tiles_version``s and then the least recently used
tiles until the cache is ≤ ``UHD_TILE_CACHE_MAX_GB`` and the disk has ≥ ``UHD_TILE_CACHE_MIN_FREE_GB`` free.

    python -m uhd.tiles.evict [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil

from uhd.config import get_settings
from uhd.logging_setup import setup_logging
from uhd.services import science
from uhd.tiles import render

log = logging.getLogger("uhd.tiles.evict")


def run(dry_run: bool = False) -> dict:
    s = get_settings()
    root = s.cache_dir / "tiles"
    root.mkdir(parents=True, exist_ok=True)  # (also run the pyramid part when no tile was cached yet)
    cur = render.cache_tag()
    removed_dirs = []
    for d in root.iterdir():
        if d.is_dir() and d.name != cur:
            removed_dirs.append(d.name)
            if not dry_run:
                shutil.rmtree(d, ignore_errors=True)
    if (root / cur).is_dir():  # dndvi tiles of an older per-layer tag (e.g. before the water mask)
        for d in (root / cur).iterdir():
            if d.is_dir() and d.name.startswith("dndvi-") and not d.name.startswith(render.dndvi_dir_prefix()):
                removed_dirs.append(f"{cur}/{d.name}")
                if not dry_run:
                    shutil.rmtree(d, ignore_errors=True)
    pyr = s.cache_dir / "pyramid"
    cur_dv = re.sub(r"[^A-Za-z0-9._-]+", "_", science.data_version())
    if pyr.is_dir():
        for d in pyr.iterdir():
            if d.is_dir() and d.name != cur_dv:
                removed_dirs.append(f"pyramid/{d.name}")
                if not dry_run:
                    shutil.rmtree(d, ignore_errors=True)
        from uhd.tiles import pyramid

        cur_dir = pyr / cur_dv
        if cur_dir.is_dir():  # gap pyramids of an older reffield.npz (layer dirs «gap@<tag>»)
            for aoi_d in cur_dir.iterdir():
                if not aoi_d.is_dir():
                    continue
                for ld in aoi_d.iterdir():
                    base = ld.name.split("@")[0]
                    tracked = base in pyramid.REFFIELD_LAYERS or base in pyramid.SHARE_LAYERS
                    if ld.is_dir() and tracked and ld.name != pyramid.layer_dirname(base):
                        removed_dirs.append(f"pyramid/{cur_dv}/{aoi_d.name}/{ld.name}")
                        if not dry_run:
                            shutil.rmtree(ld, ignore_errors=True)
    files = []
    total = 0
    for dp, _, fns in os.walk(root / cur):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_atime, st.st_size, p))
            total += st.st_size
    files.sort()  # oldest access first
    cap = s.tile_cache_max_gb * 2**30
    free = shutil.disk_usage(s.cache_dir).free
    need_free = s.tile_cache_min_free_gb * 2**30
    n = 0
    for _, size, p in files:
        if total <= cap and free >= need_free:
            break
        if not dry_run:
            try:
                os.remove(p)
            except OSError:
                continue
        total -= size
        free += size
        n += 1
    out = {"removed_dirs": removed_dirs, "removed_files": n, "cache_gb": round(total / 2**30, 2),
           "free_gb": round(free / 2**30, 1)}
    log.info("tile cache evicted", extra=out)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    setup_logging("INFO", True)
    print(run(a.dry_run))


if __name__ == "__main__":
    main()
