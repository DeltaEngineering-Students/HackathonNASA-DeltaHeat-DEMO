#!/usr/bin/env python3
"""Overture Maps buildings (OSM + Microsoft + Google + Esri footprints, with height / floors where known) for
Ukraine, via DuckDB over the public S3 GeoParquet (anonymous, bbox-pruned reads).

Output: ROOT/extra/overture/buildings_ukraine_<release>.parquet
  id, subtype, class, height, num_floors, roof_height?, sources (dataset names), bbox (xmin..ymax), geometry (WKB, EPSG:4326)
Also places/land_use are small and could be added later.
usage: overture_buildings.py [release]   (default: newest release on S3)
"""
import os, sys, re, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

BBOX = (22.0, 44.3, 40.3, 52.4)   # lon/lat box of Ukraine (rows are then clipped to this box by bbox)


def newest_release():
    r = subprocess.run(["curl", "-s", "-A", C.UA,
                        "https://overturemaps-us-west-2.s3.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"],
                       capture_output=True, text=True).stdout
    return sorted(re.findall(r"<Prefix>release/([0-9][^<]*)/</Prefix>", r))[-1]


def main():
    import duckdb
    log = C.setup_log("overture")
    rel = sys.argv[1] if len(sys.argv) > 1 else newest_release()
    out = f"{C.ROOT}/extra/overture/buildings_ukraine_{rel}.parquet"
    if os.path.exists(out):
        log.info("exists %s", out); return
    C.check_disk()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET extension_directory='{C.ROOT}/../.duckdb'")
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'; SET threads=4; SET memory_limit='3GB';")
    con.execute("SET http_retries=10; SET http_timeout=120000;")
    src = f"s3://overturemaps-us-west-2/release/{rel}/theme=buildings/type=building/*"
    x0, y0, x1, y1 = BBOX
    t0 = time.time()
    log.info("overture %s -> %s", rel, out)
    con.execute(f"""
      COPY (
        SELECT id, subtype, class, height, num_floors, roof_height,
               list_transform(sources, s -> s.dataset) AS sources, bbox, geometry
        FROM read_parquet('{src}', hive_partitioning=1)
        WHERE bbox.xmin < {x1} AND bbox.xmax > {x0} AND bbox.ymin < {y1} AND bbox.ymax > {y0}
      ) TO '{out}.tmp' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)""")
    os.replace(out + ".tmp", out)
    n, nh = con.execute(f"SELECT count(*), count(height) FROM read_parquet('{out}')").fetchone()
    log.info("overture done: %d buildings (%d with height) in %.0fs", n, nh, time.time() - t0)
    C.manifest_update("overture/buildings", path=out, release=rel, rows=n, rows_with_height=nh,
                      bytes=os.path.getsize(out), crs="EPSG:4326 (WKB)", bbox=BBOX)


if __name__ == "__main__":
    main()
