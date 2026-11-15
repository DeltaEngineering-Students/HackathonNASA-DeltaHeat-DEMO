import { describe, expect, it, vi } from 'vitest';
import { choosePlaceHit, installLabelPick, placeLabelAt, sameName, type MapLabel } from './labelPick';
import type { PlaceHit } from '../api/types';

const feat = (layer: string, props: Record<string, unknown>, coords: [number, number] = [30.5, 50.5], type = 'symbol', sourceLayer = 'place') =>
  ({ layer: { id: layer, type }, sourceLayer, properties: props, geometry: { type: 'Point', coordinates: coords } });
const mapWith = (feats: unknown[]) => ({ queryRenderedFeatures: vi.fn(() => feats) }) as never;
const own = new Set(['ov-city', 'hot-dot', 'veil']);

describe('placeLabelAt', () => {
  it('reads a settlement / district label (Ukrainian name, class, point)', () => {
    const m = mapWith([feat('label_city', { class: 'city', name: 'Uzhhorod', 'name:uk': 'Ужгород', 'name:en': 'Uzhhorod' }, [22.29, 48.62])]);
    expect(placeLabelAt(m, { x: 10, y: 10 }, own)).toEqual({ name: 'Ужгород', nameEn: 'Uzhhorod', cls: 'city', lngLat: [22.29, 48.62] });
  });
  it('ignores roads, water, POIs and our own layers on top', () => {
    expect(placeLabelAt(mapWith([feat('road_label', { class: 'primary', name: 'вул. Х' }, undefined, 'symbol', 'transportation_name')]), { x: 0, y: 0 }, own)).toBeNull();
    expect(placeLabelAt(mapWith([feat('label_other', { class: 'continent', name: 'Europe' })]), { x: 0, y: 0 }, own)).toBeNull();
    expect(placeLabelAt(mapWith([feat('ov-city', {}, undefined, 'circle', ''), feat('label_city', { class: 'city', name: 'Київ' })]), { x: 0, y: 0 }, own)).toBeNull();
    expect(placeLabelAt(mapWith([feat('veil', {}, undefined, 'fill', ''), feat('label_town', { class: 'town', name: 'Przemyśl' })]), { x: 0, y: 0 }, own)).toBeNull();
  });
});

describe('choosePlaceHit — the same choice as the search', () => {
  const lab = (name: string, lngLat: [number, number], cls = 'suburb'): MapLabel => ({ name, cls, lngLat });
  const hit = (id: string, name: string, center: [number, number], kind = 'district'): PlaceHit => ({ id, name, kind, center });
  it('prefers a preset near the label over a geocoder hit', () => {
    const hits = [hit('osm:N1', 'Оболонь', [30.5, 50.51], 'geocoder'), hit('kyiv-obolon', 'Оболонь', [30.49, 50.5])];
    expect(choosePlaceHit(hits, lab('Оболонь', [30.5, 50.5]))?.id).toBe('kyiv-obolon');
  });
  it('falls back to the geocoder hit when there is no preset', () => {
    const hits = [hit('osm:R7', 'Ірпінь', [30.25, 50.52], 'geocoder')];
    expect(choosePlaceHit(hits, lab('Ірпінь', [30.24, 50.52], 'town'))?.id).toBe('osm:R7');
  });
  it('never opens a same-named place far away', () => {
    const hits = [hit('osm:R9', 'Новоселиця', [26.28, 48.22], 'geocoder')];
    expect(choosePlaceHit(hits, lab('Новоселиця', [30.0, 50.0], 'village'))).toBeNull();
  });
  it('a city label finds the city preset even if its centre is a few km off', () => {
    expect(choosePlaceHit([hit('kyiv', 'Увесь Київ', [30.53, 50.4], 'city'), hit('kyiv-holosiivskyi', 'Голосіївський район (Київ)', [30.55, 50.33])], lab('Київ', [30.52, 50.45], 'city'))?.id).toBe('kyiv');
  });
  it('name matching', () => {
    expect(sameName('Позняки (≈1 км)', 'Позняки')).toBe(true);
    expect(sameName('Оболонський район', 'Оболонь')).toBe(true);
    expect(sameName('Дарниця', 'Деснянський')).toBe(false);
  });
});

describe('installLabelPick', () => {
  const setup = (active = true) => {
    const on: Record<string, (e: unknown) => void> = {};
    const style = { cursor: '' };
    const map = {
      on: (ev: string, f: (e: unknown) => void) => { on[ev] = f; }, off: vi.fn(),
      getCanvas: () => ({ style }),
      queryRenderedFeatures: () => [feat('label_city', { class: 'city', name: 'Львів' }, [24.03, 49.84])],
    };
    const pick = vi.fn();
    installLabelPick(map as never, own, () => active, pick);
    return { on, style, pick };
  };
  it('hover → pointer cursor; click → onPick with the label', () => {
    const { on, style, pick } = setup();
    on.mousemove!({ point: { x: 1, y: 1 } });
    expect(style.cursor).toBe('pointer');
    on.click!({ point: { x: 1, y: 1 } });
    expect(pick).toHaveBeenCalledWith({ name: 'Львів', cls: 'city', lngLat: [24.03, 49.84] });
  });
  it('inactive while drawing', () => {
    const { on, style, pick } = setup(false);
    on.mousemove!({ point: { x: 1, y: 1 } });
    on.click!({ point: { x: 1, y: 1 } });
    expect(style.cursor).toBe('');
    expect(pick).not.toHaveBeenCalled();
  });
});
