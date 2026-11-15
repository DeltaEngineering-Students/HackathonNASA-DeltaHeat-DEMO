import { barsMetric, mapLayers, overviewNote, NDVI_NODATA, NDVI_TICKS_UK, yearNoData } from './layers';
import type { LayerMeta } from '../api/types';

const L = (id: string, name_uk: string): LayerMeta => ({ id, name_uk, units: '', stops: [] });

describe('one map layer list (item 6)', () => {
  it('fixed order, full names from meta, short labels for the strip', () => {
    const got = mapLayers([L('ndvi', 'Зелень (NDVI)'), L('dndvi', 'Зміна зелені з 2013'), L('gap', 'Розрив з лісом'), L('lst', 'Температура поверхні')]);
    expect(got.map((x) => x.id)).toEqual(['gap', 'lst', 'ndvi', 'dndvi']);
    expect(got.map((x) => x.short)).toEqual(['Розрив', 'Температура', 'Зелень', 'Зміна зелені']);
    expect(got[3]!.name).toBe('Зміна зелені'); // an older meta's «з 2013» is dropped: names carry no year
  });
  it('year bars follow the layer', () => {
    expect(barsMetric('gap').caption).toBe('розрив з лісом за роками');
    expect(barsMetric('lst').kind).toBe('lst');
    expect(barsMetric('dndvi').caption).toMatch(/NDVI.*зміна від 2013/);
  });
  it('below z9 the note says the markers are the gap', () => {
    expect(overviewNote('ndvi', 'Зелень (NDVI)')).toBe('Маркери — розрив з лісом, не зелень. Наблизьте, щоб побачити шар «Зелень (NDVI)».');
  });
  it('internal layers never become choices (item 17 C)', () => {
    const got = mapLayers([L('gap', 'Розрив з лісом'), L('gap_fill', 'gap_fill'), L('nonbuilt', 'nonbuilt'), { ...L('lst', 'Т'), internal: true } as LayerMeta, L('ndvi', 'Зелень (NDVI)')]);
    expect(got.map((x) => x.id)).toEqual(['gap', 'ndvi']);
  });
});

describe('per-layer «no data» (MAP-TASKS 28)', () => {
  const row = { year: 2023, zone_lst: null, ref_lst: null, gap: null, ndvi: 0.53, ndbi: null, built_share: null, scenes: 1, valid_share: 0.2, method: null, excluded: 'too_few_scenes' };
  it('a summer left out of the heat analysis still has NDVI on the green layers', () => {
    expect(yearNoData('gap', row)?.label).toMatch(/^немає даних/);
    expect(yearNoData('lst', row)).not.toBeNull();
    expect(yearNoData('ndvi', row)).toBeNull();
    expect(yearNoData('dndvi', row)).toBeNull();
  });
  it('green layers say «no data» only when NDVI itself is missing', () => {
    expect(yearNoData('ndvi', { ...row, ndvi: null })?.label).toBe(NDVI_NODATA);
    expect(yearNoData('gap', { ...row, excluded: null, gap: 5, method: 'per_scene' as const })).toBeNull();
    expect(NDVI_TICKS_UK).toBe('0,2 — асфальт, дахи · 0,5 — двори з деревами · 0,8 — ліс');
  });
});
