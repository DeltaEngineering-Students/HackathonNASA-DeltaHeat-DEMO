import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Polygon } from 'geojson';
import App from './App';
import { PLACES, REPORTS } from './fixtures';

const api = vi.hoisted(() => ({
  analyze: vi.fn<typeof import('./api/client').analyze>(),
  getPlace: vi.fn<typeof import('./api/client').getPlace>(),
}));

vi.mock('./api/client', async () => {
  const actual = await vi.importActual<typeof import('./api/client')>('./api/client');
  const fx = await import('./fixtures');
  return {
    ...actual,
    getMeta: async () => fx.META,
    usingFixtures: async () => false,
    getOverview: async () => null,
    getClimate: async () => fx.CLIMATE,
    analyze: api.analyze,
    getPlace: api.getPlace,
  };
});

vi.mock('./components/MapView', () => ({
  MapView: ({ onDrawn }: { onDrawn: (g: Polygon) => void }) => (
    <button onClick={() => onDrawn({
      type: 'Polygon',
      coordinates: [[[30.60, 50.40], [30.62, 50.40], [30.62, 50.42], [30.60, 50.42], [30.60, 50.40]]],
    })}>Draw test area</button>
  ),
}));

beforeEach(() => {
  window.history.replaceState(null, '', '/');
  window.sessionStorage.clear();
  api.getPlace.mockReset().mockImplementation(async (id) => PLACES[id]!);
  api.analyze.mockReset().mockImplementation(async (_request, id) => REPORTS[id ?? 'kyiv-hatne']!);
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 200 }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function ready() {
  render(<App />);
  await screen.findByTestId('answer');
}

function chooseObolon() {
  fireEvent.focus(screen.getByRole('combobox'));
  fireEvent.click(screen.getByRole('option', { name: /^Оболонь/ }));
}

async function retry() {
  await screen.findByTestId('answer-error');
  fireEvent.click(screen.getByRole('button', { name: 'Спробувати ще раз' }));
}

it('retries the selected preset geometry after a failure, never the previous successful area', async () => {
  await ready();
  api.getPlace.mockImplementation(async (id) => {
    if (id === 'kyiv-obolon') throw new Error('network');
    return PLACES[id]!;
  });
  chooseObolon();
  await screen.findByTestId('answer-error');
  api.analyze.mockClear();
  api.getPlace.mockImplementation(async (id) => PLACES[id]!);

  await retry();
  const card = await screen.findByTestId('answer');
  expect(api.analyze).toHaveBeenCalledExactlyOnceWith(
    { geometry: PLACES['kyiv-obolon']!.geometry, place_id: 'kyiv-obolon' }, 'kyiv-obolon',
  );
  expect(card.querySelector('h1')).toHaveTextContent('Оболонь');
  expect(screen.getByTestId('gap-mean')).toHaveTextContent('+7,9°');
  expect(window.location.search).toContain('zone=kyiv-obolon');
});

it('retries an initial geometry failure when no previous analysis exists', async () => {
  api.getPlace.mockRejectedValueOnce(new Error('network'));
  render(<App />);
  await screen.findByTestId('answer-error');
  expect(api.analyze).not.toHaveBeenCalled();

  await retry();
  await screen.findByTestId('answer');
  expect(api.analyze).toHaveBeenCalledExactlyOnceWith(
    { geometry: PLACES['kyiv-pozniaky']!.geometry, place_id: 'kyiv-pozniaky' }, 'kyiv-pozniaky',
  );
});

it('keeps the new preset in error when its geometry fails again instead of displaying the old report', async () => {
  await ready();
  api.getPlace.mockImplementation(async (id) => {
    if (id === 'kyiv-obolon') throw new Error('network');
    return PLACES[id]!;
  });
  chooseObolon();
  await screen.findByTestId('answer-error');
  api.analyze.mockClear();
  await retry();

  await screen.findByTestId('answer-error');
  expect(api.getPlace.mock.calls.filter(([id]) => id === 'kyiv-obolon')).toHaveLength(2);
  expect(api.analyze).not.toHaveBeenCalled();
  expect(window.location.search).toContain('zone=kyiv-obolon');
});

it('retries a failed analysis with the selected preset cached geometry', async () => {
  await ready();
  api.analyze.mockRejectedValueOnce(new Error('analysis unavailable'));
  chooseObolon();
  await screen.findByTestId('answer-error');
  api.getPlace.mockClear();
  api.analyze.mockClear();
  await retry();

  await screen.findByTestId('answer');
  expect(api.getPlace.mock.calls.some(([id]) => id === 'kyiv-obolon')).toBe(false);
  expect(api.analyze).toHaveBeenCalledExactlyOnceWith(
    { geometry: PLACES['kyiv-obolon']!.geometry, place_id: 'kyiv-obolon' }, 'kyiv-obolon',
  );
});

it('retries the exact drawn geometry without a preset id', async () => {
  await ready();
  api.analyze.mockRejectedValueOnce(new Error('analysis unavailable'));
  fireEvent.click(await screen.findByRole('button', { name: 'Draw test area' }));
  await screen.findByTestId('answer-error');
  const failedRequest = api.analyze.mock.calls.at(-1)![0];
  api.analyze.mockClear();
  await retry();

  await screen.findByTestId('answer');
  expect(failedRequest).not.toHaveProperty('place_id');
  expect(api.analyze).toHaveBeenCalledExactlyOnceWith(failedRequest, undefined);
});

it('ignores retry geometry that resolves after another area is selected', async () => {
  await ready();
  api.getPlace.mockImplementation(async (id) => {
    if (id === 'kyiv-obolon') throw new Error('network');
    return PLACES[id]!;
  });
  chooseObolon();
  await screen.findByTestId('answer-error');
  let resolveGeometry!: (p: typeof PLACES[string]) => void;
  api.getPlace.mockImplementation((id) => id === 'kyiv-obolon'
    ? new Promise((resolve) => { resolveGeometry = resolve; })
    : Promise.resolve(PLACES[id]!));
  await retry();
  await waitFor(() => expect(resolveGeometry).toBeTypeOf('function'));
  fireEvent.focus(screen.getByRole('combobox'));
  fireEvent.click(screen.getByRole('option', { name: /^Теремки/ }));
  await screen.findByTestId('answer');
  api.analyze.mockClear();

  await act(async () => { resolveGeometry(PLACES['kyiv-obolon']!); });
  expect(api.analyze).not.toHaveBeenCalled();
  expect(screen.getByTestId('answer').querySelector('h1')).toHaveTextContent('Теремки');
  expect(window.location.search).toContain('zone=kyiv-teremky');
});
