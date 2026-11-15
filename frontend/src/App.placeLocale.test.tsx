import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import App from './App';
import { PLACES, REPORTS } from './fixtures';
import { setLocale } from './i18n/locale';

const api = vi.hoisted(() => ({ analyze: vi.fn(), getPlace: vi.fn(), searchPlaces: vi.fn() }));
vi.mock('./api/client', async () => {
  const actual = await vi.importActual<typeof import('./api/client')>('./api/client');
  const fx = await import('./fixtures');
  return { ...actual, getMeta: async () => fx.META, usingFixtures: async () => false,
    getOverview: async () => null, getClimate: async () => fx.CLIMATE,
    analyze: api.analyze, getPlace: api.getPlace, searchPlaces: api.searchPlaces };
});
vi.mock('./components/MapView', () => ({ MapView: () => null }));

beforeEach(() => {
  window.history.replaceState(null, '', '/');
  sessionStorage.clear();
  setLocale('uk');
  api.analyze.mockReset().mockImplementation(async () => REPORTS['kyiv-pozniaky']);
  api.getPlace.mockReset().mockImplementation(async (id: string) => id === 'osm:W42'
    ? { id, name: 'Майдан Незалежності', name_en: 'Майдан Незалежності', kind: 'geocoder_circle', geometry: PLACES['kyiv-pozniaky']!.geometry }
    : PLACES[id]);
  api.searchPlaces.mockReset().mockResolvedValue([{ id: 'osm:W42', name: 'Майдан Незалежності', name_en: 'Independence Square', kind: 'geocoder' }]);
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 200 }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); setLocale('uk'); });

async function chooseEnglishPlace() {
  render(<App />);
  await screen.findByTestId('answer');
  await act(async () => { setLocale('en'); });
  fireEvent.focus(screen.getByRole('combobox'));
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Maidan' } });
  fireEvent.click(await screen.findByRole('option', { name: 'Independence Square' }));
}

it('uses the selected official English name and toggles labels without rerunning analysis', async () => {
  await chooseEnglishPlace();
  const card = await screen.findByTestId('answer');
  expect(card.querySelector('h1')).toHaveTextContent('Independence Square');
  const n = api.analyze.mock.calls.length;
  await act(async () => { setLocale('uk'); });
  expect(card.querySelector('h1')).toHaveTextContent('Майдан Незалежності');
  await act(async () => { setLocale('en'); });
  expect(card.querySelector('h1')).toHaveTextContent('Independence Square');
  expect(api.analyze).toHaveBeenCalledTimes(n);
});

it('preserves the official English search label through a failed-analysis retry and cached geometry', async () => {
  api.analyze.mockResolvedValueOnce(REPORTS['kyiv-pozniaky']).mockRejectedValueOnce(new Error('temporary'));
  await chooseEnglishPlace();
  await screen.findByTestId('answer-error');
  expect(screen.getByTestId('answer-error').querySelector('h1')).toHaveTextContent('Independence Square');
  const lookups = api.getPlace.mock.calls.length;
  fireEvent.click(screen.getByTestId('answer-error').querySelector('button')!);
  const card = await screen.findByTestId('answer');
  expect(card.querySelector('h1')).toHaveTextContent('Independence Square');
  expect(api.getPlace).toHaveBeenCalledTimes(lookups);
  expect(api.analyze.mock.calls.at(-1)![1]).toBe('osm:W42');
});

it('loads the official English name for a shared place URL without any prior search hit', async () => {
  window.history.replaceState(null, '', '/?zone=osm:W42&lang=en');
  setLocale('en');
  api.getPlace.mockImplementation(async (id: string) => id === 'osm:W42'
    ? { id, name: 'Майдан Незалежності', name_en: 'Independence Square', kind: 'geocoder_circle', geometry: PLACES['kyiv-pozniaky']!.geometry }
    : PLACES[id]);
  render(<App />);
  const card = await screen.findByTestId('answer');
  expect(card.querySelector('h1')).toHaveTextContent('Independence Square');
  const n = api.analyze.mock.calls.length;
  await act(async () => { setLocale('uk'); });
  expect(card.querySelector('h1')).toHaveTextContent('Майдан Незалежності');
  expect(api.analyze).toHaveBeenCalledTimes(n);
});
