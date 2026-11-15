#!/bin/bash
# Extra datasets queue (resumable; run by systemd unit landsat-extras):
#   1. GHSL built-up surface 2015/2020/2025 + building height 2018 (global, 100 m)   -- now
#   2. Global Local Climate Zones v3 (filtered, 100 m, global)                       -- now
#   3. NASA NEX-GDDP-CMIP6 tasmax cut to Europe                                      -- after Landsat ingest
set -u
X=/root/landsat/extra; LOG=/root/landsat/logs/extras.log
mkdir -p $X/ghsl $X/lcz
log() { echo "$(date '+%F %T') $*" >> $LOG; }
# heartbeat for the watchdog (disk usage grows while downloading)
( while true; do log "heartbeat $(du -sm $X | cut -f1) MB"; sleep 300; done ) &
HB=$!; trap 'kill $HB 2>/dev/null' EXIT

fetch() {  # url dest
  [ -f "$2" ] && return 0
  for i in 1 2 3 4 5 6; do
    /root/bench/.venv/bin/python /root/landsat/pget.py "$1" "$2" 16 >> $LOG 2>&1 && { log "downloaded $(basename $2) $(du -h $2 | cut -f1)"; return 0; }
    log "retry $i $(basename $2)"; sleep $((60*i))
  done
  return 1
}

PIDS=""
G=https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL
for p in GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2015_GLOBE_R2023A_54009_100 \
         GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A_54009_100 \
         GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2025_GLOBE_R2023A_54009_100 \
         GHS_BUILT_H_GLOBE_R2023A/GHS_BUILT_H_AGBH_E2018_GLOBE_R2023A_54009_100; do
  n=$(basename $p)
  [ -f $X/ghsl/$n.done ] && continue
  ( fetch "$G/$p/V1-0/${n}_V1_0.zip" "$X/ghsl/$n.zip" && \
    unzip -o -q "$X/ghsl/$n.zip" -d "$X/ghsl/$n" && rm "$X/ghsl/$n.zip" && touch $X/ghsl/$n.done && log "unzipped $n" ) &
  PIDS="$PIDS $!"
done
( fetch "https://zenodo.org/records/8419340/files/lcz_filter_v3.tif?download=1" "$X/lcz/lcz_filter_v3.tif" ) &
PIDS="$PIDS $!"
wait $PIDS   # not plain wait: the heartbeat loop never ends
ls $X/ghsl/*.done 2>/dev/null | wc -l | grep -q '^4$' || { log "GHSL incomplete"; exit 1; }
[ -f $X/lcz/lcz_filter_v3.tif ] || { log "LCZ incomplete"; exit 1; }
curl -sfL -o "$X/lcz/readme.txt" "https://zenodo.org/records/8419340/files/readme.txt?download=1" || true
touch $X/GHSL_DONE $X/LCZ_DONE
log "GHSL + LCZ DONE"

log "waiting for Landsat ingest to finish before CMIP6"
until grep -q "INGEST FINISHED: \['kyiv', 'kharkiv', 'lviv', 'ukraine'\]" /root/landsat/logs/ingest.log; do sleep 120; done
log "CMIP6 start"
/root/bench/.venv/bin/python -W ignore /root/landsat/cmip6.py >> $LOG 2>&1 || exit 1
touch $X/CMIP6_DONE
log "ALL EXTRAS DONE"
