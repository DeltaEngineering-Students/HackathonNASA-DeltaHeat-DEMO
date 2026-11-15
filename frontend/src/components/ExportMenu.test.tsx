import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExportMenu, exportUrl, resetExportProbe, placeMenu, shareWithLang } from './ExportMenu';

describe('«Експорт ▾» (item 29)', () => {
  beforeEach(() => { resetExportProbe(); vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false }))); });
  afterEach(() => vi.unstubAllGlobals());

  it('urls: export endpoint when present, else only the plain JSON', () => {
    expect(exportUrl('ab/c', 'csv', new Set(['csv']))).toBe('/api/reports/ab%2Fc/export?format=csv');
    expect(exportUrl('abc', 'json', new Set())).toBe('/api/reports/abc');
    expect(exportUrl('abc', 'pdf', new Set(['csv', 'json']))).toBeNull();
  });
  it('menu button pattern: ↓ opens on the first enabled item, arrows wrap, Esc closes and refocuses', async () => {
    const user = userEvent.setup();
    render(<ExportMenu reportId="abc" shareUrl="https://x/?zone=a" title="A" />);
    const btn = screen.getByRole('button', { name: /Експорт/ });
    expect(btn).toHaveAttribute('aria-haspopup', 'menu');
    btn.focus();
    await user.keyboard('{ArrowDown}');
    await new Promise((r) => requestAnimationFrame(r));
    expect(btn).toHaveAttribute('aria-expanded', 'true');
    const items = screen.getAllByRole('menuitem');
    expect(items.map((x) => x.textContent?.replace(' · скоро', ''))).toEqual(['PDF — звіт для друку', 'Excel (.xlsx)', 'CSV (таблиця за роками)', 'JSON (для розробників)', 'Поділитися посиланням']);
    // without the backend export only JSON + share are live; the rest are disabled, not dead links
    expect(items.slice(0, 3).every((x) => x.getAttribute('aria-disabled') === 'true')).toBe(true);
    expect(screen.getByRole('menuitem', { name: 'JSON (для розробників)' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Поділитися посиланням' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'JSON (для розробників)' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    expect(btn).toHaveFocus();
  });
  it('share copies the link and shows the toast', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<ExportMenu reportId="abc" shareUrl="https://x/?zone=a&year=2022" title="A" />);
    await user.click(screen.getByRole('button', { name: /Експорт/ }));
    await user.click(screen.getByRole('menuitem', { name: 'Поділитися посиланням' }));
    expect(writeText).toHaveBeenCalledWith('https://x/?zone=a&year=2022&lang=uk'); // item 32: share links carry the language
    expect(await screen.findByTestId('toast')).toHaveTextContent('Посилання скопійовано');
  });
  it('json 200 + pdf 422 → CSV / Excel / JSON live, PDF stays «скоро» (no dead link)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (u: string) => ({ ok: !u.includes('format=pdf'), status: u.includes('format=pdf') ? 422 : 200 })));
    const user = userEvent.setup();
    render(<ExportMenu reportId="abc" shareUrl="https://x/" title="A" />);
    await new Promise((r) => setTimeout(r, 0));
    await user.click(screen.getByRole('button', { name: /Експорт/ }));
    const pdf = screen.getAllByRole('menuitem')[0]!;
    expect(pdf).toHaveAttribute('aria-disabled', 'true');
    expect(pdf).not.toHaveAttribute('href');
    expect(screen.getByRole('menuitem', { name: 'CSV (таблиця за роками)' })).toHaveAttribute('href', '/api/reports/abc/export?format=csv');
    expect(screen.getByRole('menuitem', { name: 'Excel (.xlsx)' })).toHaveAttribute('href', '/api/reports/abc/export?format=xlsx');
    expect(screen.getByRole('menuitem', { name: 'JSON (для розробників)' })).toHaveAttribute('href', '/api/reports/abc/export?format=json');
  });
});

describe('placeMenu (fixed popover)', () => {
  const m = { width: 260, height: 220 };
  it('opens upward when asked and it fits, right-aligned when the left edge would overflow', () => {
    const p = placeMenu({ left: 300, right: 400, top: 800, bottom: 840 }, m, 480, 900, true);
    expect(p.top).toBe(800 - 6 - 220);
    expect(p.left).toBe(400 - 260);
  });
  it('flips down when there is no room above; stays 8 px inside the viewport', () => {
    const p = placeMenu({ left: 1300, right: 1400, top: 20, bottom: 60 }, m, 1440, 900, true);
    expect(p.top).toBe(66);
    expect(p.left + m.width).toBeLessThanOrEqual(1440 - 8);
  });
});

describe('item 32: language on downloads and share links', () => {
  it('exportUrl adds lang=en only in English (Ukrainian keeps today\'s URL)', () => {
    const all = new Set<'pdf' | 'xlsx' | 'csv' | 'json'>(['csv', 'json']);
    expect(exportUrl('r1', 'csv', all, 'en')).toMatch(/\/api\/reports\/r1\/export\?format=csv&lang=en$/);
    expect(exportUrl('r1', 'csv', all, 'uk')).toMatch(/\/api\/reports\/r1\/export\?format=csv$/);
    expect(exportUrl('r1', 'json', new Set(), 'en')).toMatch(/\/api\/reports\/r1\?lang=en$/);
    expect(exportUrl('r1', 'pdf', new Set(), 'en')).toBeNull();
  });
  it('shareWithLang makes the language explicit and keeps the rest', () => {
    expect(shareWithLang('https://x/?zone=a&year=2022', 'en')).toBe('https://x/?zone=a&year=2022&lang=en');
    expect(shareWithLang('https://x/?zone=a&lang=en', 'uk')).toBe('https://x/?zone=a&lang=uk');
  });
});
