// English glossary for the tooltips: the same keys as lib/glossary.ts (typed — a missing or extra key fails `tsc`),
// same `seeAlso` links. Wording: uhd/docs/TERMS-EN.md; facts: METHOD.md / API.md (change together with the Ukrainian).
// Rules as in Ukrainian: `short` ≤ 140 chars, `more` ≤ 400; decimal point; «°C» after a no-break space; SSP names
// with U+2011; no zone-specific numbers. Plain words in `short`, scientific terms in `more` only.
import type { GlossaryEntry, GlossaryKey } from '../lib/glossary';

type Entry = Omit<GlossaryEntry, 'seeAlso'>;

/** `seeAlso` is taken from lib/glossary.ts (one source of the link graph). */
export const GLOSSARY_EN: Readonly<Record<GlossaryKey, Entry>> = {
  gap: {
    term: 'Surface heat gap',
    short: 'How many degrees hotter the built-up surface is than the forest around the city on summer days. +8 °C: roofs and asphalt are 8° hotter.',
    more: 'The forest is a natural «zero»: the same satellite images it on the same days, so the weather of a particular summer hardly affects the comparison. A negative number means the area is cooler than the forest (this happens in parks and forests within the city).',
  },
  gapMean: {
    term: 'Mean over N summer seasons',
    short: 'The big number on the card is the mean surface heat gap over all summer seasons with reliable data. Seasons without data are not counted.',
  },
  surfaceVsAir: {
    term: 'Surface, not air',
    short: 'The satellite measures the temperature of the surface — roofs, asphalt, grass — not of the near-surface air (2 m) that you breathe.',
    more: 'A hot surface heats the air and people nearby, so its gap with the forest shows the city’s heat island well. But it is not the weather forecast: the near-surface (2 m) air temperature difference between city and forest is usually smaller. And this is the daytime picture; at night it differs. Scientific term: land surface temperature (LST).',
  },
  lst: {
    term: 'Land surface temperature',
    short: 'How hot the ground, roofs and asphalt are at the moment of the image (about 11:00 solar time), from the Landsat 8 thermal sensor.',
    more: 'The map shows the summer value of each 60 × 60 m square. The card chart shows the surface temperature of your area’s built-up land and of the forest around the city for each summer season; the distance between the lines is the gap.',
  },
  chartLines: {
    term: 'Chart: built-up vs forest',
    short: 'The upper line is the built-up surface of your area, the lower one the forest around the city. The distance between them is the gap.',
    more: 'In Kyiv, Kharkiv and Lviv the forest line is the same for every district of the city. Breaks in a line are summer seasons without reliable data.',
  },

  referenceForest: {
    term: 'Reference forest (forest around the city)',
    short: 'The natural «zero» we compare with: old forests around the city that were not cut in any year. Built-up land is compared with them.',
    more: 'We take only forest present on all land-cover maps 2017–2023, green every summer and not farmland; forest edges are dropped because heat mixes there with fields or roads. Kyiv, Kharkiv and Lviv have one reference per city, so districts can be compared fairly.',
  },
  ring: {
    term: '2–15 km ring',
    short: 'The reference forest is searched in a ring 2 to 15 km from the city boundary: far enough from the city’s heat, but with the same weather.',
    more: 'If the ring has too little forest (under ≈1.8 km²), it is widened to 30 km. Steppe cities (Odesa, Mykolaiv, Zaporizhzhia) have little forest — then the reference is less reliable, and the card warns about it.',
  },
  derivedReference: {
    term: 'Reference forest picked automatically',
    short: 'For cities other than Kyiv, Kharkiv and Lviv we find the city boundary and the forest around it automatically, from a built-up map.',
    more: 'The city boundary is the continuous built-up land around your area (blocks separated by streets, parks or a river merge into one). Around it we take forest in a 2–15 km ring. Such a reference is less precise than in the three big cities.',
  },
  urbanArea: {
    term: 'City boundary',
    short: 'For Kyiv, Kharkiv and Lviv — the official boundary from OpenStreetMap. Elsewhere — found automatically from continuous built-up land.',
  },
  suburb: {
    term: 'Suburb',
    short: 'An area within 15 km of Kyiv, Kharkiv or Lviv (Irpin, Brovary) is compared with the same city’s forest — like its districts.',
  },

  trend: {
    term: 'Trend per 10 years',
    short: 'How many degrees the gap changes on average every 10 years. +0.4° means the gap grows by about 0.4 °C per decade.',
    more: 'Computed with the Theil–Sen estimator: the slopes between all pairs of years are taken and the median is chosen, so one odd season does not skew the result. Whether the change can be trusted is shown by its statistical significance (p).',
  },
  significant: {
    term: 'Significant',
    short: 'The gap changes so steadily that random weather hardly explains it: a statistically significant trend (p < 0.05). A signal, not a verdict.',
    more: 'If very many areas are tested, about every 20th will come out statistically significant by chance. So one such area is not yet proof for the whole city.',
  },
  notSignificant: {
    term: 'Not yet significant',
    short: 'The change is smaller than the usual variation between summer seasons. Not «nothing changed» — there is no evidence of a change yet.',
    more: 'The gap varies by about 1 °C from one summer season to another because of the weather. Over 10–13 seasons a small change cannot be told apart from this noise. Morning shadows of new high-rises and slowly growing trees can also hide it. Look at how greenery and built-up land changed. Scientific term: not statistically significant (p ≥ 0.05).',
  },
  insufficientData: {
    term: 'Too little data for a trend',
    short: 'Estimating a change needs at least 8 summer seasons with clear images. There are fewer here, so we say nothing about a trend.',
  },
  pValue: {
    term: 'p',
    short: 'The chance of seeing such a trend by accident if nothing really changed. The smaller p, the more reliable; the threshold is 0.05 (1 in 20).',
    more: 'Example: p = 0.37 means a trend this strong or stronger would appear by chance in about 37 cases out of 100 — it may well be weather noise. p = 0.002 means only 2 times in 1000. Computed with the Mann–Kendall test.',
  },
  ci: {
    term: '95% confidence interval',
    short: 'The range that most likely contains the true change. If it includes 0 («no change»), there may be no change at all.',
    more: 'For example, «from −1.0 to +2.1 °C» means: most likely the gap grows by a few tenths of a degree per 10 years, but the data rule out neither a small decrease nor a clear increase.',
  },
  theilSen: {
    term: 'Theil–Sen estimator',
    short: 'A way to fit a trend line that is robust to one anomalous season: the median slope between all pairs of years.',
  },
  mannKendall: {
    term: 'Mann–Kendall test',
    short: 'A statistical test of whether values rise (or fall) from year to year more often than chance would allow. It gives the p-value.',
  },
  median: {
    term: 'Median',
    short: 'The middle value of a sorted list: half of the numbers are larger, half smaller. One odd day hardly moves it.',
  },
  zoneTrend: {
    term: 'Trend of the built-up surface',
    short: 'How the surface temperature of the built-up land itself changes from year to year — without comparing with the forest.',
  },
  refTrend: {
    term: 'Trend of the reference forest',
    short: 'How the forest temperature changes. If the forest warms too, the gap may not grow even though the built-up land heats up.',
  },
  gapDriver: {
    term: 'Is it getting worse?',
    short: 'The gap is built-up minus forest. This shows what actually changed: the built-up surface itself or the reference forest.',
    more: 'If the forest has no statistically significant trend, we attribute the change in the gap to the area itself. But a non-significant forest trend does not prove the forest did not change, so this is a hint, not an exact split.',
  },

  summer: {
    term: 'Summer',
    short: 'June, July and August. We compare only summer images — summer is when the city suffers most from heat.',
  },
  overpassTime: {
    term: 'About 11:00 (image time)',
    short: 'Landsat 8 passes over Ukraine at about 11:00 local solar time. So this is the late-morning picture; afternoon and night look different.',
    more: 'At this time the shadows of tall buildings are still long and can slightly cool the surface in the image.',
  },
  scene: {
    term: 'Image (overpass)',
    short: 'One satellite pass over a place on a given day. Landsat 8 passes over the same place once every 16 days.',
    more: 'Neighbouring acquisition swaths overlap, so some cities (Kyiv among them) fall into two or three swaths and get more images per summer. Images of the same day from adjacent rows are merged into one.',
  },
  scenesCount: {
    term: 'Landsat images',
    short: 'How many clear images went into the calculation: in total and the fewest–most in one summer. The more, the more reliable.',
    more: 'In Kyiv, Kharkiv and Lviv an image is used if at least half of the area and enough of the reference forest are cloud-free. A summer needs at least 2 such images to be counted.',
  },
  clouds: {
    term: 'Clouds',
    short: 'A thermal image cannot see through clouds. Cloudy pixels are dropped; if over half of the area is covered, the day is skipped.',
  },
  validShare: {
    term: 'Smallest cloud-free share of the area',
    short: 'Which part of the area was seen cloud-free at least once in a summer — in the worst season. 100% means the whole area was seen.',
  },
  noDataYear: {
    term: 'No data (n/a)',
    short: 'There is no reliable number for this summer: too few clear images, clouds or a gap in the data. Hover over the year to see why.',
    more: 'For such seasons we do not invent numbers and do not count them in the mean or the trend. For example, in 2020 there was only one clear overpass over Pozniaky, and a summer value needs at least 2.',
  },
  partialYear: {
    term: 'Partial',
    short: 'In this summer clouds covered more than 30% of the area in every image. There is a number, but it is less certain.',
  },
  excludedYears: {
    term: 'Skipped years',
    short: 'Summer seasons that were not used in the calculation, and why: clouds, too few images or a gap in the satellite data.',
  },

  landsat8: {
    term: 'Landsat 8',
    short: 'A NASA and USGS satellite imaging the Earth since 2013, including with a thermal sensor. The data are free and open.',
  },
  pixel60: {
    term: '60 m',
    short: 'The smallest map detail is a 60 × 60 m square (about half a football pitch). A single house or tree cannot be seen.',
    more: 'The satellite’s thermal band is even coarser (≈100 m), so at the edge of a park and buildings the values mix. We do not analyse very small areas (under 0.5 km²).',
  },
  perScene: {
    term: 'Computed per image',
    short: 'In Kyiv, Kharkiv and Lviv built-up land is compared with the forest on each acquisition day separately, then the summer median is taken.',
    more: 'This way built-up land and forest are seen in the same weather, and seams between acquisition swaths do not enter the numbers. If a summer has fewer than 2 usable days, it is computed from the composite.',
  },
  composite: {
    term: 'Composite',
    short: 'One «average» summer picture from all clear images. Outside Kyiv, Kharkiv and Lviv the numbers are computed this way.',
    more: 'A composite is simpler, but neighbouring swaths enter it from different days, so in some years the error can reach 1–2 °C.',
  },
  seams: {
    term: 'Seams between images',
    short: 'Neighbouring Landsat swaths are acquired on different days with different weather. Where they meet, the map can show 1–3 °C «steps».',
    more: 'This is a property of the map, not a real heat boundary. The card numbers for Kyiv, Kharkiv and Lviv are computed per image, so seams hardly affect them.',
  },
  mapVsCard: {
    term: 'Map — summer mean',
    short: 'The map shows where it is warmer and where cooler. Exact numbers are on the card: they are computed differently and can differ by 1–3 °C.',
  },
  hatchNoData: {
    term: 'Transparent areas (hatching)',
    short: 'No temperature data here for this summer: clouds or a gap in the images. It means «unknown», not «cold».',
  },
  noLst: {
    term: 'No satellite land surface temperature',
    short: 'The images here are clear, but USGS did not compute a temperature for them: input data are missing. A product gap, not clouds.',
    more: 'The calculation needs a reference map of how different surfaces emit heat (ASTER). It has holes that are the same every year. The largest are in the east (Kharkiv, Donetsk and Luhansk regions, Mariupol), plus narrow strips in the centre and west.',
  },
  filledFromNeighbours: {
    term: 'Filled from neighbouring years',
    short: 'This summer had a gap here. So the map has no holes, we show a paler value from neighbouring years. It is not part of the report numbers.',
  },

  ndvi: {
    term: 'Greenness (NDVI)',
    short: 'How much living vegetation is seen from above: 0–0.2 — asphalt, roofs or bare soil; 0.8 and more — dense forest. Water is below 0.',
    more: 'Residential blocks with yards, gardens and street trees often have 0.4–0.6, so the city can look green on the «Greenness» layer. Computed from how leaves reflect red and near-infrared light; we take the summer value. Vegetation cools through shade and evaporation.',
  },
  dndvi: {
    term: 'Change in greenness since 2013',
    short: 'How much greener (green colour) or less green (orange) a place is compared with 2013. Scale: −0.3 to +0.3 NDVI.',
    more: 'Water bodies are not shown: rivers, reservoirs and lakes that were water in both the base year and the selected year. Where water disappeared or appeared (such as the bed of the former Kakhovka reservoir), the change is visible.',
  },
  ndviTrend: {
    term: 'Greenness is significantly increasing / decreasing',
    short: 'Vegetation in the area changes steadily, not by chance (p < 0.05). Often the first signal: trees growing up or disappearing.',
  },
  ndbi: {
    term: 'Built-up index (NDBI)',
    short: 'A measure of how much a surface looks like concrete, roofs or bare soil. Helps estimate built-up land in years without maps.',
  },
  parksGap: {
    term: 'Parks and squares are cooler',
    short: 'How many degrees the city’s parks, squares and green yards are cooler than your area’s built-up land. Large forests are not included.',
    more: 'We take green patches inside the city of up to 5 km² that were green in all years. Large woodlands (Pushcha-Vodytsia, Holosiivskyi Forest) are not counted — they behave like the reference forest.',
  },

  greenStillWarm: {
    term: 'A green area, but warmer than the forest',
    short: 'Even a forest or park in the city can be 2–3 °C warmer than the reference forest: it has clearings, sand, paths and edges.',
    more: 'The reference forest is only unbroken old forest around the city, without edges. Your green area is counted whole: clearings, sandy patches, roads, edges. The satellite sees heat in ≈100 m squares, so a hot path «smears» onto nearby trees. A large woodland inside a city is usually close to 0 (Holosiivskyi Forest ≈ −0.2 °C).',
  },
  ndviVsLst: {
    term: 'Greenness, but no temperature',
    short: 'Greenness and temperature come from the same images, but temperature has stricter conditions. So there can be greenness without temperature.',
    more: 'Temperature needs clear summer images showing both the area and the reference forest. Also, in parts of Ukraine (mostly the east) USGS did not compute temperature at all, although the images are clear and give greenness. Built-up maps also use April–October greenness.',
  },

  built: {
    term: 'Built-up (urban fabric, Esri)',
    short: 'Everything the Esri map marks as urban: buildings and roads, plus yards, squares and dachas between them. Not only concrete.',
    more: 'So even part of a city park may count as «built-up». How much is actually roofs and asphalt is in the «Sealed surfaces (GHSL)» row. Esri maps exist for 2017–2023; other years are estimated from the images.',
  },
  builtShare: {
    term: 'Built-up share',
    short: 'Which part of your area is urban built-up land (including yards and greenery between buildings). «On land» — without water.',
  },
  sealed: {
    term: 'Sealed surfaces (GHSL)',
    short: 'The share of the area under roofs and asphalt from the global GHSL map (100 m grid). Usually much smaller than «built-up».',
  },
  basisAlwaysBuilt: {
    term: 'What we compute: land built up in every year',
    short: 'The main number is computed only where land was built up every year. So new buildings cannot create a «trend» just by appearing.',
  },
  variantEachYear: {
    term: 'Variant «built-up land of each year»',
    short: 'The same gap, but for all built-up land of each year, new buildings included. A check of whether the conclusion changes.',
  },
  allLand: {
    term: 'All land (too little built-up)',
    short: 'The area has too little built-up land (a park, a forest), so all land is counted. A gap near 0 is normal here — it is nature.',
  },
  newBuilt: {
    term: 'New built-up land',
    short: 'Land that was not built up in the first two years of the period and was built up in the last two.',
  },
  newBuiltBeforeAfter: {
    term: 'New built-up land: before / after',
    short: 'The gap with the forest at the same places before and after construction. Bare soil and building sites are hot too, so it may not grow.',
  },
  classesExtrapolated: {
    term: 'Estimated built-up maps',
    short: 'Annual built-up maps exist only for 2017–2023; other years are estimated from greenness and the built-up index, blind to destruction.',
  },

  hotspots: {
    term: 'Hot spots',
    short: 'The hottest built-up places over the last 3 summer seasons with data: ≥ 1 °C hotter than the rest of the area’s built-up land.',
    more: 'The mean gap over those seasons, smoothed; up to 3 spots, ≥ 500 m apart. The number by a spot is its gap with the forest. A dashed line on the map outlines the hot patch. Click a spot or its number on the card to zoom in. No spots means no place stands out clearly.',
  },
  rank: {
    term: 'Compared with districts',
    short: 'We compare the built-up gap of your area with the districts of the same city. All are computed the same way, with the same reference forest.',
  },
  likeForLike: {
    term: 'Small area',
    short: 'A small dense block is almost always hotter than a whole district with its parks, so instead of a rank we show the districts’ range.',
  },
  compareZones: {
    term: 'Compared with other areas',
    short: 'The mean gap with the forest for the examples and the whole city — something to compare your area with.',
  },

  cmip6: {
    term: 'Climate scenarios (CMIP6)',
    short: 'Climate model runs: how much warmer the near-surface summer air will get in the region. Model results, not our measurements.',
    more: 'We take 12 models from the NASA NEX-GDDP-CMIP6 set for the nearest ≈25 km grid cell and compare summer daily maximum near-surface air temperature (2 m) over 20-year periods: 2041–2060 and 2081–2100 against 1995–2014. We show the median of the models and the 10–90% range.',
  },
  forecast2050: {
    term: 'Outlook for 2041–2060',
    short: 'How many degrees higher the summer daily maximum near-surface air temperature will be in 2041–2060 than in 1995–2014.',
    more: 'Median of 12 climate models: half of the models give more, half give less.',
  },
  ssp245: {
    term: 'Moderate scenario (SSP2‑4.5)',
    short: 'The world cuts greenhouse gas emissions slowly, roughly as today. It is most often used as the «middle» case.',
  },
  ssp585: {
    term: 'High emissions (SSP5‑8.5)',
    short: 'The pessimistic case: greenhouse gas emissions keep rising fast. Warming is then strongest.',
  },
  modelSpread: {
    term: 'Model spread',
    short: 'The range that holds 80% of the models (from the 10th to the 90th percentile). The wider the range, the less certain the outlook.',
    more: 'Each model gives its own value, so we show the median and the 10–90% range, not a single number.',
  },
  climateIsAir: {
    term: 'Air, not surface',
    short: 'The outlook is about near-surface air temperature (2 m) over a large region, not the surface. It is not added to the gap.',
  },

  warRegion: {
    term: 'Region affected by the war',
    short: 'The area is in an oblast occupied or near the front line since 2014 or 2022. Changes in 2022–2025 may result from destruction.',
    more: 'The amber dashed line on the map outlines the whole oblast — it is not the front line. We do not remove the analysis, but built-up maps after 2023 are estimated and do not see destruction.',
  },
  occupied: {
    term: 'Temporarily occupied territory',
    short: 'Occupied per the official list of the Ministry of Development of Ukraine (as of 15 September 2026). Boundaries by hromada.',
    more: 'Near the front line the boundary may be off by about one hromada (municipality). Changes in 2022–2025 here may result from the war and destruction.',
  },
  zoneClipped: {
    term: 'Part outside Ukraine',
    short: 'The part of the area beyond Ukraine’s border is cut off: we have no data there, so only the Ukrainian part is computed.',
  },
  veil: {
    term: 'Data — Ukraine only',
    short: 'We analyse only the territory of Ukraine. Neighbouring countries are dimmed on the map.',
  },

  geocoderCircle: {
    term: 'Circle of ≈1 km around the address',
    short: 'For an address or a single building we analyse a circle of ≈1 km radius around it: one building is too small for the satellite.',
  },
  minArea: {
    term: 'Area size',
    short: 'An area must be from 0.5 km² (a ≈700 × 700 m square) to 5,000 km². Smaller is too small for the satellite, larger too big to compute.',
  },
  areaAndBuilt: {
    term: 'Area',
    short: 'The whole area of the selected place and how much of it is built-up land (with yards and greenery between buildings).',
  },
  examples: {
    term: 'Examples',
    short: 'Ready-made areas with different stories: dense blocks, new housing on former dachas, gardens that grew up, and a forest in the city.',
  },

  mapYear: {
    term: 'Map: summer',
    short: 'The map shows one selected summer. Change the year with the bars next to it.',
  },
  yearBars: {
    term: 'Bars by year',
    short: 'Each bar is one summer; its height is the value for your area. Click a bar to show that summer on the map.',
  },
  yearValue: {
    term: 'In the area',
    short: 'The value for your area in the selected summer — the same as that year’s bar.',
  },
  legend: {
    term: 'Legend',
    short: 'Left — cooler, right — hotter. The colour of each place on the map matches the number on this scale.',
  },
  layerSwitch: {
    term: 'Map layer',
    short: 'What the map colours now: the gap with the forest, surface temperature, greenness or its change. The card numbers do not change.',
  },
  countryMarkers: {
    term: 'Markers on the country map',
    short: 'Number = built-up gap with the forest (mean over all summer seasons), not a temperature. +8°: 8 °C hotter than the forest. Click to open.',
    more: 'An amber ring around a marker means an oblast affected by the war. «n/a» means there are no data for this place. Zoom in to see the gap block by block.',
  },
  markerNoData: {
    term: 'n/a',
    short: 'No data: there is no satellite surface temperature here, or too few summer seasons with clear images.',
  },
  layersPanel: {
    term: 'Layers',
    short: 'How the map looks: basemap, heat visibility and muting of non-built land. These settings do not affect the numbers.',
  },
  basemap: {
    term: 'Map / Satellite',
    short: 'Under the heat layer — a regular map or a satellite photo (Esri archive). The photo is for orientation only, not in the calculation.',
  },
  heatTransparency: {
    term: 'Layer visibility',
    short: 'How much of the chosen layer shows over the basemap: 100% — all of it, less — streets show through. 50% on satellite until changed.',
  },
  muteNonBuilt: {
    term: 'Mute non-built land',
    short: 'Dims fields, forests, meadows and water to highlight the heat of built-up land. Fields are hot in summer too, but they are not the city.',
  },

  search: {
    term: 'Search',
    short: 'Enter an address, district or city in Ukraine. For an address we analyse a circle of ≈1 km around it.',
  },
  drawPolygon: {
    term: 'Polygon area',
    short: 'Click on the map to place the corners of an area; double-click or Enter to finish. You get an analysis of exactly that area.',
  },
  drawCircle: {
    term: 'Circle area',
    short: 'Press at the centre of the area and drag to its edge — you get an analysis of that circle.',
  },
  zoom: {
    term: 'Zoom',
    short: 'Zoom the map in or out. You can also use the mouse wheel or two fingers.',
  },
  fitUkraine: {
    term: 'All of Ukraine',
    short: 'Show the whole country. At this zoom the heat map is replaced by city markers with the mean gap with the forest.',
  },
  analyst: {
    term: 'Analyst (AI)',
    short: 'An AI assistant answers questions about the area. It uses numbers only from our data, shows every step; numbers are auto-checked.',
    more: 'If its answer contains a number that is not in our data, you will see a warning. The final check is «Analysis details».',
  },
  details: {
    term: 'Analysis details',
    short: 'All numbers, charts, the method and caveats for this area — so you can check the conclusion yourself.',
  },
  numbersToCheck: {
    term: 'Numbers to check',
    short: 'The raw numbers behind the conclusion: trend, p, image counts, areas. Hover over a row name to see what it is.',
  },
  reportJson: {
    term: 'Report in JSON',
    short: 'The full report in machine-readable form — for developers and independent checks. The id is the same for the same area and data version.',
  },
  demoData: {
    term: 'Demo data',
    short: 'The analysis server is unavailable right now, so we show saved examples from real calculations for Kyiv.',
  },
  dataCredit: {
    term: 'Data: NASA/USGS Landsat 8',
    short: 'Where the numbers come from: Landsat 8 thermal images for the summer seasons of the years shown, processed with our method.',
  },
};
