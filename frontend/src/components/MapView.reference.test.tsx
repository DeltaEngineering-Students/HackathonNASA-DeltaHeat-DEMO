import { act, cleanup, render, waitFor } from '@testing-library/react';
import type { Feature, FeatureCollection, Polygon } from 'geojson';
import type { Map as MlMap } from 'maplibre-gl';
import { MapView, type MapViewProps } from './MapView';
import { getMapUi, setMapUi } from '../lib/mapUi';

const api = vi.hoisted(() => ({ getReference: vi.fn() }));
vi.mock('../api/client', async () => ({
  ...await vi.importActual<typeof import('../api/client')>('../api/client'),
  getOverlays: async () => null,
  getReference: api.getReference,
}));
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: 'mock-worker' }));

// A map-engine boundary double: sources store what the real MapView writes, and style swaps discard
// sources just as MapLibre does. The reference-fetch lifecycle itself is the production component.
const engine = vi.hoisted(() => {
  type Source = { data: unknown; setData: (data: unknown) => void };
  type Layer = { id: string; type: string; layout?: Record<string, unknown>; paint?: Record<string, unknown> };
  class FakeMap {
    sources = new Map<string, Source>();
    layers = new Map<string, Layer>();
    events = new Map<string, ((...args: unknown[]) => void)[]>();
    canvas = document.createElement('canvas');
    container: HTMLElement;
    minZoom = 5;
    bounds: number[][] | null = null;
    touchZoomRotate = { disableRotation() {} };
    keyboard = { disableRotation() {} };
    constructor(options: { container: HTMLElement }) {
      this.container = options.container;
      Object.defineProperties(this.container, { clientWidth: { value: 1440 }, clientHeight: { value: 900 } });
    }
    on(event: string, ...args: unknown[]) {
      const handler = args.at(-1) as (...args: unknown[]) => void;
      this.events.set(event, [...this.events.get(event) ?? [], handler]);
      return this;
    }
    once(event: string, callback: (...args: unknown[]) => void) { return this.on(event, callback); }
    off(event: string, callback: (...args: unknown[]) => void) {
      this.events.set(event, (this.events.get(event) ?? []).filter((f) => f !== callback));
      return this;
    }
    fire(event: string) { for (const f of this.events.get(event) ?? []) f({}); return this; }
    getCanvas() { return this.canvas; }
    getContainer() { return this.container; }
    getZoom() { return 11; }
    getMinZoom() { return this.minZoom; }
    setMinZoom(z: number) { this.minZoom = z; }
    getMaxBounds() { return this.bounds ? { toArray: () => this.bounds! } : null; }
    setMaxBounds(b: number[][] | null) { this.bounds = b; }
    getPadding() { return { top: 0, bottom: 0, left: 0, right: 0 }; }
    getStyle() { return { layers: [...this.layers.values()] }; }
    getSource(id: string) { return this.sources.get(id); }
    addSource(id: string, options: { data?: unknown }) {
      const source: Source = { data: options.data, setData(data) { source.data = data; } };
      this.sources.set(id, source);
    }
    removeSource(id: string) { this.sources.delete(id); }
    getLayer(id: string) { return this.layers.get(id); }
    addLayer(layer: Layer) { this.layers.set(layer.id, layer); }
    removeLayer(id: string) { this.layers.delete(id); }
    getLayoutProperty(id: string, key: string) { return this.layers.get(id)?.layout?.[key]; }
    setLayoutProperty() {}
    addControl() { return this; }
    removeControl() { return this; }
    getPaintProperty(id: string, key: string) { return this.layers.get(id)?.paint?.[key]; }
    setPaintProperty() {}
    setFilter() {}
    setLayerZoomRange() {}
    hasImage() { return true; }
    project() { return { x: 700, y: 300 }; }
    queryRenderedFeatures() { return []; }
    flyTo() {}
    triggerRepaint() {}
    remove() {}
    setStyle() { this.sources.clear(); this.layers.clear(); return this; }
  }
  class Popup {
    setText() { return this; }
    setLngLat() { return this; }
    addTo() { return this; }
    remove() { return this; }
  }
  return { FakeMap, Popup };
});
vi.mock('maplibre-gl', () => ({ Map: engine.FakeMap, Popup: engine.Popup, setWorkerUrl() {}, addProtocol() {} }));

const geometry: Polygon = { type: 'Polygon', coordinates: [[[30, 50], [30.1, 50], [30.1, 50.1], [30, 50]]] };
const forest = (id: string): Feature<Polygon> => ({ type: 'Feature', properties: { id }, geometry });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
};

beforeEach(() => {
  api.getReference.mockReset();
  setMapUi({ showReference: true, reportId: 'A', zoneOutline: null, reference: 'idle', basemap: 'map' });
});
afterEach(() => { cleanup(); });

function mount() {
  const mapRef: MapViewProps['mapRef'] = { current: null };
  render(<MapView theme="light" geometry={geometry} label={null} cityGeometry={null}
    layer="gap" year={null} tiles leftInset={480} draw={null} onDrawn={() => {}}
    onDrawCancel={() => {}} mapRef={mapRef} />);
  const map = mapRef.current as unknown as InstanceType<typeof engine.FakeMap>;
  act(() => { map.fire('style.load'); });
  const shown = () => (map.getSource('reference')!.data as FeatureCollection).features;
  const reloadStyle = () => act(() => { (map as unknown as MlMap).setStyle('new-style'); map.fire('style.load'); });
  return { map, shown, reloadStyle };
}

it('clears visible A while B is pending, including after a basemap style reload', async () => {
  const b = deferred<Feature<Polygon> | null>();
  api.getReference.mockImplementation((id: string) => id === 'A' ? Promise.resolve(forest('A')) : b.promise);
  const { shown, reloadStyle } = mount();
  await waitFor(() => expect(shown()).toEqual([forest('A')]));

  act(() => { setMapUi({ reportId: 'B' }); });
  expect(api.getReference).toHaveBeenLastCalledWith('B');
  expect(getMapUi().reference).toBe('loading');
  expect(shown()).toEqual([]);
  reloadStyle();
  expect(shown()).toEqual([]);

  await act(async () => { b.resolve(forest('B')); });
  expect(shown()).toEqual([forest('B')]);
  expect(getMapUi().reference).toBe('ok');
});

it('never restores a canceled A response after B wins or reference visibility is disabled', async () => {
  const a = deferred<Feature<Polygon> | null>();
  const b = deferred<Feature<Polygon> | null>();
  api.getReference.mockImplementation((id: string) => id === 'A' ? a.promise : b.promise);
  const { shown, reloadStyle } = mount();
  act(() => { setMapUi({ reportId: 'B' }); });
  await act(async () => { b.resolve(forest('B')); });
  expect(shown()).toEqual([forest('B')]);

  await act(async () => { a.resolve(forest('A')); });
  expect(shown()).toEqual([forest('B')]);
  expect(getMapUi().reference).toBe('ok');
  reloadStyle();
  expect(shown()).toEqual([forest('B')]);

  act(() => { setMapUi({ showReference: false }); });
  expect(shown()).toEqual([]);
  expect(getMapUi().reference).toBe('idle');
  reloadStyle();
  expect(shown()).toEqual([]);
});
