import { describe, expect, it } from 'vitest';
import { getMapUi, layerTransparency, muteApplies, SAT_HEAT_TRANSPARENCY, setBasemap, setMapUi } from './mapUi';

describe('mapUi (item 7)', () => {
  it('defaults: map basemap, heat as designed, mute 70 %', () => {
    const s = getMapUi();
    expect(s.basemap).toBe('map');
    expect(s.heatTransparency).toBe(0);
    expect(s.mute).toBe(0.7);
  });
  it('mute slider only on «Розрив» (item 27) and only when the backend offers the overlay', () => {
    expect(muteApplies({ ...getMapUi(), layer: 'gap', nonbuilt: null })).toBe(false);
    const nb = { label_uk: 'не-забудова', applies_to: ['gap', 'lst'] };
    expect(muteApplies({ ...getMapUi(), layer: 'gap', nonbuilt: nb })).toBe(true);
    expect(muteApplies({ ...getMapUi(), layer: 'lst', nonbuilt: nb })).toBe(false);
    expect(muteApplies({ ...getMapUi(), layer: 'gap', nonbuilt: { applies_to: ['lst'] } })).toBe(false);
    expect(muteApplies({ ...getMapUi(), layer: 'ndvi', nonbuilt: nb })).toBe(false);
    expect(muteApplies({ ...getMapUi(), layer: 'ndvi', nonbuilt: {} })).toBe(false);
  });
  it('setMapUi updates and ignores no-op patches', () => {
    const a = getMapUi();
    setMapUi({ basemap: 'map' });
    expect(getMapUi()).toBe(a);
    setMapUi({ basemap: 'sat', heatTransparency: 0.5 });
    expect(getMapUi()).toMatchObject({ basemap: 'sat', heatTransparency: 0.5 });
  });
  it('satellite sets heat to 50 % until the user moves the slider (item 26)', () => {
    setMapUi({ basemap: 'map', heatTransparency: 0, heatTouched: false });
    setBasemap('sat');
    expect(getMapUi().heatTransparency).toBe(0.5);
    setBasemap('map');
    expect(getMapUi().heatTransparency).toBe(0);
    setMapUi({ heatTransparency: 0.3, heatTouched: true });
    setBasemap('sat');
    expect(getMapUi()).toMatchObject({ basemap: 'sat', heatTransparency: 0.3 });
  });
});

describe('layerTransparency (slider «Видимість шару»)', () => {
  it('0 % visibility hides every layer, 100 % shows it fully', () => {
    for (const l of ['gap', 'lst', 'ndvi', 'dndvi']) {
      expect(layerTransparency(1, l)).toBe(1);
      expect(layerTransparency(0, l)).toBe(0);
    }
  });
  it('green layers stay ≥ 85 % visible at the satellite default and are monotonic', () => {
    expect(layerTransparency(SAT_HEAT_TRANSPARENCY, 'ndvi')).toBeCloseTo(0.15);
    expect(layerTransparency(SAT_HEAT_TRANSPARENCY, 'gap')).toBe(SAT_HEAT_TRANSPARENCY);
    let prev = -1;
    for (let i = 0; i <= 20; i++) { const v = layerTransparency(i / 20, 'dndvi'); expect(v).toBeGreaterThanOrEqual(prev); prev = v; }
  });
});
