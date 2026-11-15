// Adapters are tested against real responses captured from the live backend (src/api/samples/*.json).
import meta from './samples/meta.json';
import places from './samples/places.json';
import analyze from './samples/analyze.json';
import climate from './samples/climate.json';
import { adaptClimate, adaptHotspots, adaptMeta, adaptPlaces, adaptReport, cityLabel, leadSentence } from './adapt';
import { highlightVerdict } from '../lib/verdict';

describe('live backend adapters', () => {
  it('normalises /api/meta layers into themed colour stops', () => {
    const m = adaptMeta(meta as Record<string, unknown>);
    expect(m.years).toContain(2025);
    const gap = m.layers.find((l) => l.id === 'gap')!;
    expect(gap.name_uk).toBe('Розрив з лісом');
    expect(gap.stops[0]).toEqual([-6, '#5C8C7A']);
    expect(gap.stops_dark?.at(-1)).toEqual([12, '#F078BA']);
    expect(m.tiles?.url).toContain('{theme}');
    expect(adaptMeta({ layers: { tiles_version: 'tv1', scales: {} } }).tiles?.version).toBe('tv1');
    expect(m.presets.some((p) => p.id === 'kyiv-pozniaky')).toBe(true);
  });
  it('merges preset and geocoder hits for search', () => {
    adaptMeta(meta as Record<string, unknown>);
    const hits = adaptPlaces(places);
    expect(hits[0]).toMatchObject({ id: 'kyiv-obolon', name: 'Оболонь', subtitle: 'Київ' });
    expect(hits.some((h) => h.kind === 'geocoder')).toBe(true);
  });
  it('normalises the report (green gap object, city name)', () => {
    adaptMeta(meta as Record<string, unknown>);
    const r = adaptReport(analyze as Record<string, unknown>);
    expect(typeof r.green_gap).toBe('number');
    expect(r.reference.city).toBe('Київ');
    expect(r.series).toHaveLength(13);
    expect(r.trend.verdict).toBe('not_significant');
  });
  it('never shows raw enum values for the reference city', () => {
    expect(cityLabel('kyiv')).toBe('Київ');
    expect(cityLabel('derived')).toBe('');
    expect(cityLabel('some_new_id')).not.toMatch(/[a-z]/);
  });
  it('turns CMIP6 scenario maps into rows', () => {
    const c = adaptClimate(climate as Record<string, unknown>);
    expect(c.projections.length).toBeGreaterThanOrEqual(4);
    expect(c.projections[0]!.period).toMatch(/^\d{4}–\d{4}$/);
    expect(c.baseline).toMatch(/^\d{4}–\d{4}$/);
  });
  it('takes the first sentence of the verdict for the card and highlights it', () => {
    const lead = leadSentence((analyze as { verdict_text_uk: string }).verdict_text_uk, 'Позняки');
    expect(lead).toMatch(/^Забудова влітку вдень у середньому на \d+,\d °C гарячіша за ліс навколо Києва\.$/);
    const segs = highlightVerdict(lead);
    expect(segs.find((s) => s.tone === 'heat')?.text).toMatch(/°C гарячіша$/);
    expect(segs.find((s) => s.tone === 'ref')?.text).toBe('ліс навколо Києва');
    expect(leadSentence('Тренд 0,7 °C/10 р. поки не значущий. Далі.')).toBe('Тренд 0,7 °C/10 р. поки не значущий.');
  });
});

describe('hotspots (API v1.8)', () => {
  it('reads {lon, lat, gap}, hottest first, max 3; null/[] -> []', () => {
    const h = adaptHotspots([
      { lon: 30.62, lat: 50.40, gap: 11.0, gap_peak_px: 12, area_km2: 0.1, years: [2023, 2024, 2025] },
      { lon: 30.6312, lat: 50.4071, gap: 13.2, gap_peak_px: 14.6, area_km2: 0.252, years: [2023, 2024, 2025] },
      { lon: 30.64, lat: 50.41, gap: 9.1 }, { lon: 30.65, lat: 50.42, gap: 8.0 }, { lat: 50.4, gap: 20 },
    ]);
    expect(h.map((x) => x.gap)).toEqual([13.2, 11.0, 9.1]);
    expect(h[0]).toEqual({ center: [30.6312, 50.4071], gap: 13.2, area_km2: 0.252, years: [2023, 2024, 2025] });
    const poly = { type: 'Polygon', coordinates: [[[30.6, 50.4], [30.61, 50.4], [30.61, 50.41], [30.6, 50.4]]] };
    expect(adaptHotspots([{ lon: 30.6, lat: 50.4, gap: 9, delta_vs_zone: 1.2, polygon: poly, land_class: { class: 'built', label_uk: 'забудова', share: 1 } }])[0]).toMatchObject({ delta_vs_zone: 1.2, polygon: poly, type_uk: 'забудова' });
    expect(adaptHotspots(null)).toEqual([]);
    expect(adaptHotspots([])).toEqual([]);
  });
});
