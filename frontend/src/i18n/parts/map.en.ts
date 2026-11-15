// Slot «map» English keys (I18N.md §7, parallel wiring). Only the slot owner edits this pair; keys are
// «<area>.<name>» and must not repeat a key from en.ts or another part (i18n.test.ts fails on duplicates).
export const mapEn = {
  /** «Шари» panel: the reference-forest outline could not be loaded (uk keeps today's wording verbatim) */
  'map.refNone': 'The reference-forest outline for this area is not available yet.',
  /** satellite basemap caption next to the attribution (EOX yearly mosaic) */
  'map.satCaption': 'Satellite: Esri World Imagery, archive version {version} (imagery may be older)',
  /** EOX fallback caption */
  'map.satCaptionEox': 'Satellite: Sentinel‑2, {year}',
  /** short on-map credit of the occupied-territories overlay (the full source is in Details) */
  'map.occAttr': 'Occupied areas: Ministry of Development №376',
  'map.satNearest': '(nearest available version)',
  'map.satNearestEox': '(nearest available year)',
  /** Esri caption with the capture date at the place (wayback.ts): {date} = «Jul 2024» */
  'map.satCaptured': 'Satellite: Esri World Imagery, captured {date}',
  /** the capture is not from the selected map year */
  'map.satNearestCapture': '(nearest available)',
  /** zoomed out below the dated imagery (Esri shows its undated overview mosaic there) */
  'map.satZoomIn': '· zoom in to see it',
} as const;
