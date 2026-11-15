import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { PlaceHit } from '../api/types';
import { setLocale, type Locale } from '../i18n/locale';

const pending: { q: string; signal?: AbortSignal; locale?: Locale; resolve: (h: PlaceHit[]) => void }[] = [];
vi.mock('../api/client', () => ({
  searchPlaces: (q: string, signal?: AbortSignal, locale?: Locale) => new Promise<PlaceHit[]>((resolve) => pending.push({ q, signal, locale, resolve })),
}));
const { Search } = await import('./Search');

const EX: PlaceHit[] = [
  { id: 'kyiv-pozniaky', name: 'Позняки', kind: 'district' },
  { id: 'kyiv-obolon', name: 'Оболонь', kind: 'district' },
];
const TEREMKY: PlaceHit = { id: 'kyiv-teremky', name: 'Теремки', kind: 'district' };
const answer = (q: string, h: PlaceHit[]) => act(async () => { pending.filter((p) => p.q === q).forEach((p) => p.resolve(h)); });

beforeEach(() => { pending.length = 0; setLocale('uk'); });
afterEach(() => { setLocale('uk'); });

describe('Search (QA-08)', () => {
  it('no stale examples while a query is pending; Enter waits for the current results', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<Search examples={EX} onSelect={onSelect} />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('Тере');
    expect(screen.queryByRole('option')).toBeNull();
    expect(screen.getByText('Шукаємо…')).toBeTruthy();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(onSelect).not.toHaveBeenCalled();
    await waitFor(() => expect(pending.length).toBeGreaterThan(0));
    await answer('Тере', [TEREMKY]);
    expect(onSelect).toHaveBeenCalledWith(TEREMKY);
  });

  it('nothing is pre-highlighted: ↓ selects the first option', async () => {
    const user = userEvent.setup();
    render(<Search examples={EX} onSelect={() => undefined} />);
    await user.click(screen.getByRole('combobox'));
    expect(screen.getByRole('combobox').getAttribute('aria-activedescendant')).toBeNull();
    expect(screen.queryByRole('option', { selected: true })).toBeNull();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('option', { selected: true }).textContent).toContain('Позняки');
  });

  it('ignores a late response for an older query', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<Search examples={EX} onSelect={onSelect} />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('Хар');
    await waitFor(() => expect(pending.length).toBeGreaterThan(0));
    await user.keyboard('ків');
    await waitFor(() => expect(pending.some((p) => p.q === 'Харків')).toBe(true));
    await answer('Хар', [{ id: 'kharkiv-saltivka', name: 'Салтівка', kind: 'district' }]);
    expect(screen.queryByRole('option')).toBeNull();
    await answer('Харків', [{ id: 'kharkiv', name: 'Харків', kind: 'city' }]);
    await user.click(screen.getByRole('option'));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'kharkiv' }));
  });
});


describe('Search locale changes', () => {
  it('aborts the old language, hides its results and ignores late replies for the same query', async () => {
    const user = userEvent.setup();
    render(<Search examples={EX} onSelect={() => undefined} />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('Maidan');
    await waitFor(() => expect(pending).toHaveLength(1));
    const ukRequest = pending[0]!;
    await act(async () => { setLocale('en'); });
    expect(ukRequest.signal?.aborted).toBe(true);
    expect(screen.queryByRole('option')).toBeNull();
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1]!.locale).toBe('en');
    await act(async () => { ukRequest.resolve([{ id: 'old', name: 'Стара українська відповідь', kind: 'geocoder' }]); });
    expect(screen.queryByRole('option')).toBeNull();
    await act(async () => { pending[1]!.resolve([{ id: 'new', name: 'Майдан Незалежності', name_en: 'Independence Square', kind: 'geocoder' }]); });
    expect(screen.getByRole('option')).toHaveTextContent('Independence Square');
  });

  it('clears an Enter queued in the old language instead of selecting an unseen translated result', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<Search examples={EX} onSelect={onSelect} />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('Maidan{Enter}');
    await waitFor(() => expect(pending).toHaveLength(1));
    await act(async () => { setLocale('en'); });
    await waitFor(() => expect(pending).toHaveLength(2));
    await act(async () => { pending[1]!.resolve([{ id: 'new', name: 'Майдан Незалежності', name_en: 'Independence Square', kind: 'geocoder' }]); });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('option')).toHaveTextContent('Independence Square');
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ name_en: 'Independence Square' }));
  });
});
