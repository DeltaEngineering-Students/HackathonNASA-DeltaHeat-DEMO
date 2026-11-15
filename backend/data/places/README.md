# data/places

Small boundary files read at runtime by `uhd.science` (and served by the backend as overlays).

| file | content | built by |
|---|---|---|
| `kyiv.geojson`, `kharkiv.geojson`, `demo.geojson` | preset districts / localities / demo zones | `scripts/precompute_places.py`, `scripts/precompute_demo.py` |
| `war_oblasts.geojson` | whole oblasts with occupation or fighting since 2014/2022 (`war_zone` caveat) | `scripts/precompute_war_areas.py` |
| `occupied.geojson` | temporarily occupied territory, hromada level (`occupied` caveat, overlay `occupied`) | `scripts/precompute_occupied.py` |

## occupied.geojson

- **Snapshot:** 15.09.2026, the date of the last amendment in the consolidated text (наказ Мінрозвитку № 1984 від
  15.09.2026). Every label says «станом на 15.09.2026».
- **Source 1, the official list:** Наказ Міністерства розвитку громад та територій України від 28.02.2025 № 376
  «Про затвердження Переліку територій, на яких ведуться (велися) бойові дії або тимчасово окупованих Російською
  Федерацією» (зареєстровано в Мін'юсті, z0380-25), in its consolidated text.
  - Text: https://zakon.rada.gov.ua/laws/show/z0380-25
  - Annex tables: https://zakon.rada.gov.ua/laws/file/text/141/f543637n58.docx, `…n59.docx`, `…n63.docx`
  - The tables have one row per settlement and period: KATOTTH code, status, start date and end date.
- **Terms for source 1:** an official document. Under Закон України «Про авторське право і суміжні права» № 2811-IX,
  ст. 10, «не є об'єктами авторського права … акти органів державної влади … (закони, укази, постанови, рішення
  тощо), а також їх офіційні переклади». Reuse is free. We credit the source anyway.
- **Source 2, boundaries:** OpenStreetMap hromada relations (`boundary=administrative`, `admin_level=7`, tag
  `katotth`), fetched by one Overpass API query. The raw response is cached.
- **Terms for source 2:** © OpenStreetMap contributors, Open Database License 1.0 (https://www.openstreetmap.org/copyright):
  «You are free to copy, distribute, transmit and adapt our data, as long as you credit OpenStreetMap and its
  contributors. If you alter or build upon our data, you may distribute the result only under the same licence.»
  This file is a derived database, so it is likewise under ODbL 1.0.
- **Crimea and Sevastopol:** drawn as whole units from `war_oblasts.geojson` (also OSM, ODbL). Every listed settlement
  there is occupied. Crimea is part of Ukraine and is handled like the other regions.
- **Attribution (also in the file's `properties.attribution`):** «Мінрозвитку України (наказ № 376 від 28.02.2025,
  zakon.rada.gov.ua); © OpenStreetMap contributors».

### Rule

- **Currently occupied settlement:** it has a row with status «Тимчасово окупована Російською Федерацією територія
  України» and no end date.
- **Occupied hromada:** at least 50 % of its listed settlements are currently occupied. KATOTTH hromada prefix = the
  first 9 characters of the code.
- **Partly occupied hromadas:** a hromada with a share between 50 % and 100 % is drawn only if its administrative
  centre (KATOTTH settlement number 001) is occupied. Such hromadas are listed in `partial_hromadas`. For example,
  Очаківська громада is not drawn: three Кінбурн villages are occupied, but Очаків is not.
- **Resolution:** this is a hromada-level outline, coarse by roughly the size of a hromada at the front. It is not a
  front line.
- **Use in a report:** a zone gets the `occupied` caveat when more than 50 % of it lies inside. Other zones in the
  oblasts of `war_oblasts.geojson` keep `war_zone` («зона бойових дій»).

### Not used

DeepStateMap shows no licence or terms. ISW/CTP layers are copyrighted («Institute for the Study of War and American
Enterprise Institute's Critical Threats Project»), their terms pages could not be read by automated clients, and ISW
has objected to some reuses of its maps. Neither is used.

### Refresh

```sh
# 1. check zakon.rada.gov.ua/laws/show/z0380-25 for a newer amendment; update SNAPSHOT_DATE (and ANNEXES if the
#    annex file names changed) in scripts/precompute_occupied.py
# 2. on the server (re-downloads the annexes, one Overpass query with backoff):
cd /root/uhd/dev/backend && nice -n 19 uv run python scripts/precompute_occupied.py --force
# 3. copy data/places/occupied.geojson back into the repo, run tests/science, bump METHOD_VERSION, commit
```
