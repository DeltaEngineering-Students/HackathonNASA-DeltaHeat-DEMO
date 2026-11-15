import { MARKER_LEGEND, colorAt, inkOn, markerKind, markerLabel, markerTip, overviewFeatures } from './overview';
import type { OverviewPlace } from '../api/types';

const base: OverviewPlace = { place_id: 'kyiv', name: 'Київ', kind: 'city', city: 'kyiv', lon: 30.6, lat: 50.4, bbox: [30, 50, 31, 51], rank: 1,
  status: 'ok', gap_mean: 7.98, war_region: null, reason_uk: null };
const STOPS: [number, string][] = [[-6, '#326056'], [0, '#424a60'], [6, '#cc6e28'], [16, '#fac4e8']];

describe('country markers (MAP-TASKS 3)', () => {
  it('label = gap_mean like the card headline: decimal comma, sign, U+2212 minus', () => {
    expect(markerLabel(base)).toBe('+8,0°');
    expect(markerLabel({ ...base, gap_mean: -0.15 })).toBe('−0,2°');
    // a single year in gap_by_year (e.g. 2020 → 9.97) never leaks into the marker: it is the all-seasons mean (9.38 → +9,4)
    expect(markerLabel({ ...base, gap_mean: 9.38, gap_by_year: { '2020': 9.97 } })).toBe('+9,4°');
    expect(markerLabel({ ...base, status: 'no_data', gap_mean: null })).toBe('н/д');
  });
  it('colour from the legend stops (interpolated, clamped)', () => {
    expect(colorAt(STOPS, 0)).toBe('#424a60');
    expect(colorAt(STOPS, 3)).toBe('#875c44');
    expect(colorAt(STOPS, 99)).toBe('#fac4e8');
    expect(colorAt(STOPS, -99)).toBe('#326056');
    expect(inkOn('#fac4e8')).toBe('#10131c');
    expect(inkOn('#424a60')).toBe('#ffffff');
  });
  it('kinds and tooltips: no data → reason; war → caveat text from the overlays', () => {
    const nd = { ...base, name: 'Маріуполь', status: 'no_data' as const, gap_mean: null, reason_uk: 'немає даних про температуру поверхні за ці роки', war_region: { name: 'Донецька область', since: 2014 } };
    expect(markerKind(nd)).toBe('nodata');
    expect(markerKind({ ...base, war_region: { name: 'Донецька область', since: 2014 } })).toBe('war');
    const ov = { ukraine: { bbox: [0, 0, 1, 1] as [number, number, number, number], geometry: { type: 'Polygon' as const, coordinates: [] } },
      war_regions: { type: 'FeatureCollection' as const, features: [{ type: 'Feature' as const, properties: { name: 'Донецька область', since: 2014, text_uk: 'Територія в регіоні війни.' }, geometry: { type: 'Polygon' as const, coordinates: [] } }] },
      no_lst: { type: 'FeatureCollection' as const, features: [] } };
    expect(markerTip(nd, ov)).toBe('Маріуполь: немає даних про температуру поверхні за ці роки. Територія в регіоні війни.');
    expect(markerTip(base, null)).toBe('Київ: забудова +8,0 °C гарячіша за ліс навколо (середнє за всі літні сезони). Натисніть, щоб відкрити.');
    expect(markerTip({ ...base, gap_mean: -1.24 }, null)).toMatch(/^Київ: забудова на 1,2 °C прохолодніша за ліс навколо/u);
    expect(markerTip({ ...base, name: 'Ужгород', gap_mean: 10.1, lst_mean: 36.2 }, null)).toMatch(/^Ужгород: забудова \+10,1 °C гарячіша за ліс навколо · сама поверхня ≈ 36 °C/u);
  });
  it('occupied places: the dated official note instead of the oblast war text', () => {
    const occ = { ...base, name: 'Мелітополь', war_region: { name: 'Запорізька область', since: 2022 },
      occupied: { snapshot_date: '2026-09-15', source: 'Перелік ТОТ (наказ Мінрозвитку № 376, ред. від 15.09.2026)' } };
    const t = markerTip(occ, null);
    expect(t).toContain('Тимчасово окупована територія (станом на 15.09.2026; джерело: Перелік ТОТ (наказ Мінрозвитку № 376, ред. від 15.09.2026)).');
    expect(t).not.toContain('Регіон війни');
    expect(MARKER_LEGEND).toMatch(/не температура$/);
  });
  it('features carry the sort rank and district flag', () => {
    const fc = overviewFeatures([base, { ...base, place_id: 'kyiv-obolon', kind: 'district', rank: 101 }], STOPS, null, true);
    expect(fc.features.map((f) => [f.properties!.rank, f.properties!.district])).toEqual([[1, false], [101, true]]);
  });
});
