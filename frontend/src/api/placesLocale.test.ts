import { adaptPlaces } from './adapt';
import { getPlace, searchPlaces } from './client';
import { setLocale } from '../i18n/locale';

const geometry = { type: 'Polygon', coordinates: [[[30, 50], [30.1, 50], [30.1, 50.1], [30, 50]]] };
beforeEach(() => { setLocale('uk'); });
afterEach(() => { vi.unstubAllGlobals(); setLocale('uk'); });

it('requests Nominatim in the UI language, including a change during an ongoing request', async () => {
  const pending: ((r: Response) => void)[] = [];
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>((resolve) => pending.push(resolve)));
  vi.stubGlobal('fetch', fetchMock);
  const uk = searchPlaces('Хрещатик');
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  setLocale('en');
  const en = searchPlaces('Хрещатик');
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(new URL(fetchMock.mock.calls[0]![0] as string, 'http://test').searchParams.get('lang')).toBe('uk');
  expect(new URL(fetchMock.mock.calls[1]![0] as string, 'http://test').searchParams.get('lang')).toBe('en');
  pending.forEach((resolve) => resolve(Response.json({ presets: [], geocoder: [] })));
  await Promise.all([uk, en]);
});

it('keeps canonical Ukrainian addresses and expands the English house number using its English street', () => {
  const [hit] = adaptPlaces({ geocoder: [{ id: 'osm:W42', name: '22', display_name: '22, вулиця Хрещатик, Київ',
    name_en: '22', display_name_en: '22, Khreshchatyk Street, Kyiv' }] });
  expect(hit).toMatchObject({ name: 'Хрещатик, 22', name_en: 'Khreshchatyk Street, 22', subtitle_en: 'Khreshchatyk Street, Kyiv' });
});

it('fetches both languages once for a place and keeps geometry and canonical fields unchanged', async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ id: 'osm:W42', kind: 'geocoder_circle', geometry,
    name: '22 (≈1 км навколо)', display_name: '22, вулиця Хрещатик, Київ',
    name_en: '22 (≈1 km around)', display_name_en: '22, Khreshchatyk Street, Kyiv' }));
  vi.stubGlobal('fetch', fetchMock);
  const place = await getPlace('osm:W42');
  expect(fetchMock.mock.calls[0]![0]).toContain('?lang=en');
  expect(place).toMatchObject({ name: 'Хрещатик, 22 (≈1 км навколо)', name_en: 'Khreshchatyk Street, 22 (≈1 km around)', geometry });
});
