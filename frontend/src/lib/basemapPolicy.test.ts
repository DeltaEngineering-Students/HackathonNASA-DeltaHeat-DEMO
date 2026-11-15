// Evaluates the filters with MapLibre's own style-spec engine (transitive dep of maplibre-gl), as the map does.
import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import type { FilterSpecification } from 'maplibre-gl';
import { undisputedBorder, withoutImposed } from './basemapPolicy';

const place = (props: Record<string, unknown>) => ({ type: 1 as const, properties: { class: 'state', ...props }, geometry: [] });
const line = (props: Record<string, unknown>) => ({ type: 2 as const, properties: { admin_level: 2, ...props }, geometry: [] });
const test = (f: FilterSpecification, feat: ReturnType<typeof place> | ReturnType<typeof line>) =>
  featureFilter(f, "layers[0].filter").filter({ zoom: 6 } as never, feat as never);

describe('basemap naming policy', () => {
  const states = withoutImposed(['==', ['get', 'class'], 'state']);
  it('hides Russian-imposed entities in any name field', () => {
    expect(test(states, place({ name: 'Республика Крым' }))).toBe(false);
    expect(test(states, place({ name: 'X', 'name:uk': 'Республіка Крим' }))).toBe(false);
    expect(test(states, place({ name: 'Донецкая Народная Республика' }))).toBe(false);
    expect(test(states, place({ 'name:en': "Luhansk People's Republic" }))).toBe(false);
  });
  it('keeps Ukrainian names and the original filter', () => {
    expect(test(states, place({ name: 'Автономна Республіка Крим', 'name:uk': 'Автономна Республіка Крим' }))).toBe(true);
    expect(test(states, place({ name: 'Севастополь' }))).toBe(true);
    expect(test(states, place({ name: 'Донецька область' }))).toBe(true);
    expect(test(states, place({ class: 'city', name: 'Київ' }))).toBe(false); // original filter still applies
  });
});

describe('basemap border policy', () => {
  const borders = undisputedBorder(['==', ['get', 'admin_level'], 2]);
  it('drops disputed and claimed lines (no line between Crimea and the mainland)', () => {
    expect(test(borders, line({ disputed: 1 }))).toBe(false);
    expect(test(borders, line({ claimed_by: 'RU' }))).toBe(false);
    expect(test(borders, line({}))).toBe(true);
    expect(test(borders, line({ admin_level: 4 }))).toBe(false);
  });
  it('works without an original filter', () => {
    expect(test(undisputedBorder(undefined), line({}))).toBe(true);
  });
});
