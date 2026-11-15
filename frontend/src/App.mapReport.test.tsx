import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ZoneGeometry } from './api/types';
import App from './App';
import { getReport } from './api/client';
import { PLACES } from './fixtures';
import { getMapUi, setMapUi } from './lib/mapUi';
import sample from './api/samples/analyze.json';

const api = vi.hoisted(() => ({ getPlace: vi.fn<typeof import('./api/client').getPlace>() }));
vi.mock('./api/client', async () => {
  const actual = await vi.importActual<typeof import('./api/client')>('./api/client');
  const fx = await import('./fixtures');
  return { ...actual, getMeta: async () => fx.META, getOverview: async () => null,
    getClimate: async () => fx.CLIMATE, getPlace: api.getPlace };
});
vi.mock('./components/MapView', async () => {
  const { useMapUi } = await import('./lib/mapUi');
  return { MapView: () => {
    const ui = useMapUi();
    return <output data-testid="map-report">{ui.reportId ?? 'none'}</output>;
  } };
});

const outlines: Record<string, ZoneGeometry> = {
  'kyiv-pozniaky': PLACES['kyiv-pozniaky']!.geometry,
  'kyiv-obolon': PLACES['kyiv-obolon']!.geometry,
  'kyiv-teremky': PLACES['kyiv-teremky']!.geometry,
};
function report(id: string) {
  return { ...sample, report_id: `report-${id}`, zone_outline: outlines[id] ?? null };
}
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  window.history.replaceState(null, '', '/');
  window.sessionStorage.clear();
  setMapUi({ reportId: null, zoneOutline: null });
  api.getPlace.mockReset().mockImplementation(async (id) => PLACES[id]!);
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'HEAD') return new Response(null, { status: 200 });
    const path = url.split('?')[0]!; // fetches carry ?lang=<ui language>
    const id = path === '/api/analyze'
      ? (JSON.parse(init!.body as string) as { place_id: string }).place_id
      : path.split('/').at(-1)!;
    return Response.json(report(id));
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function ready() {
  render(<App />);
  await screen.findByTestId('answer');
  await waitFor(() => expect(getMapUi().reportId).toBe('report-kyiv-pozniaky'));
}
async function choose(name: RegExp) {
  fireEvent.focus(screen.getByRole('combobox'));
  const option = await screen.findByRole('option', { name });
  await act(async () => {
    fireEvent.click(option);
  });
}

it('keeps the active report and clipped outline when Details computes background comparisons', async () => {
  await ready();
  await act(async () => { fireEvent.click(screen.getByTestId('open-details')); });
  await screen.findByTestId('details');
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) =>
    url.split('?')[0] === '/api/analyze' && JSON.parse(init.body).place_id !== 'kyiv-pozniaky').length).toBeGreaterThan(1));
  expect(getMapUi().reportId).toBe('report-kyiv-pozniaky');
  expect(getMapUi().zoneOutline).toEqual(outlines['kyiv-pozniaky']);
});

it('clears the old reference before the next place geometry resolves', async () => {
  await ready();
  api.getPlace.mockImplementation((id) => id === 'kyiv-obolon'
    ? new Promise(() => {}) : Promise.resolve(PLACES[id]!));
  await choose(/^Оболонь/);
  expect(getMapUi().reportId).toBeNull();
  expect(getMapUi().zoneOutline).toBeNull();
});

it('ignores an analysis that finishes after a more recent selection has loaded', async () => {
  await ready();
  let finishOld!: (response: Response) => void;
  fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
    if (init?.method === 'HEAD') return Promise.resolve(new Response(null, { status: 200 }));
    const id = (JSON.parse(init!.body as string) as { place_id: string }).place_id;
    return id === 'kyiv-obolon' ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve(Response.json(report(id)));
  });
  await choose(/^Оболонь/);
  await waitFor(() => expect(finishOld).toBeTypeOf('function'));
  await choose(/^Теремки/);
  await screen.findByTestId('answer');
  expect(getMapUi().reportId).toBe('report-kyiv-teremky');
  await act(async () => { finishOld(Response.json(report('kyiv-obolon'))); });
  expect(getMapUi().reportId).toBe('report-kyiv-teremky');
  expect(getMapUi().zoneOutline).toEqual(outlines['kyiv-teremky']);
  expect(screen.getByTestId('answer').querySelector('h1')).toHaveTextContent('Теремки');
});

it('does not change the active map when a stored report is fetched for another purpose', async () => {
  await ready();
  await act(async () => { await getReport('background'); });
  expect(getMapUi().reportId).toBe('report-kyiv-pozniaky');
  expect(getMapUi().zoneOutline).toEqual(outlines['kyiv-pozniaky']);
});

it('does not restore the previous reference when the next place geometry fails', async () => {
  await ready();
  api.getPlace.mockImplementation(async (id) => {
    if (id === 'kyiv-obolon') throw new Error('network');
    return PLACES[id]!;
  });
  await choose(/^Оболонь/);
  await screen.findByTestId('answer-error');
  expect(getMapUi().reportId).toBeNull();
  expect(getMapUi().zoneOutline).toBeNull();
});

it('publishes the accepted report even when it has insufficient temperature data', async () => {
  await ready();
  fetchMock.mockImplementation(async () => Response.json({
    ...report('kyiv-obolon'), gap_summary: { mean: null, last: null, min: null, max: null },
    series: sample.series.map((row) => ({ ...row, gap: null })),
  }));
  await choose(/^Оболонь/);
  await screen.findByTestId('answer-empty');
  expect(getMapUi().reportId).toBe('report-kyiv-obolon');
  expect(getMapUi().zoneOutline).toEqual(outlines['kyiv-obolon']);
});

it('keeps the active reference while a background report request is pending or rejected', async () => {
  await ready();
  let rejectBackground!: (reason: Error) => void;
  fetchMock.mockImplementation(() => new Promise((_resolve, reject) => { rejectBackground = reject; }));
  const pending = getReport('background').catch(() => null);
  await waitFor(() => expect(rejectBackground).toBeTypeOf('function'));
  expect(getMapUi().reportId).toBe('report-kyiv-pozniaky');
  // An HTTP failure is not automatically retried by the transport.
  await act(async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 503 }));
    rejectBackground(new Error('network'));
    await pending;
  });
  expect(getMapUi().reportId).toBe('report-kyiv-pozniaky');
  expect(getMapUi().zoneOutline).toEqual(outlines['kyiv-pozniaky']);
});
