// item 32 slot 2d/2f: Details, charts, Search and the export menu speak English with lang=en; no Cyrillic leaks
// outside elements marked lang="uk" (place names / server texts without an English version).
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DetailsPanel, numbersToCheck } from './DetailsPanel';
import { LineChart } from './charts';
import { ExportMenu } from './ExportMenu';
import { Search } from './Search';
import { REPORTS, META } from '../fixtures';
import { setLocale } from '../i18n';

const CYR = /[А-Яа-яІіЇїЄєҐґ]/;
/** visible text outside [lang=uk] and the screen-reader copies of tooltips */
function cyrillicLeaks(root: HTMLElement): string[] {
  const out: string[] = [];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement;
    if (!el || el.closest('[lang="uk"]') || el.closest('.sr-only')) continue;
    if (CYR.test(n.textContent ?? '')) out.push(n.textContent!.trim());
  }
  for (const el of root.querySelectorAll<HTMLElement>('[aria-label],[title],[placeholder]')) {
    if (el.closest('[lang="uk"]')) continue;
    for (const a of ['aria-label', 'title', 'placeholder']) { const v = el.getAttribute(a); if (v && CYR.test(v)) out.push(`${a}: ${v}`); }
  }
  return out;
}

const r = REPORTS['kyiv-pozniaky']!;
const noop = () => {};

describe('item 32: English in Details / charts / Search / export', () => {
  beforeEach(() => act(() => setLocale('en')));
  afterEach(() => act(() => setLocale('uk')));

  it('Details: English headings, rows and method text; Ukrainian only inside lang="uk"', () => {
    const { container } = render(<DetailsPanel report={r} title="Pozniaky" year={2025} onYear={noop} onBack={noop} layers={META.layers} layer="gap"
      onLayer={noop} compare={[{ id: 'a', name: 'Pozniaky', value: 9, sel: true }]} climate={null} demo={false} />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Analysis details · Pozniaky');
    expect(container.textContent).toContain('Numbers to check');
    expect(screen.getByTestId('p-plain').textContent).toMatch(/^What p means in plain words:/);
    expect(cyrillicLeaks(container)).toEqual([]);
  });

  it('numbersToCheck: English labels with glossary keys, decimal point', () => {
    const rows = numbersToCheck(r, 'en');
    expect(rows[0]![0]).toBe('Trend (Theil–Sen estimator)');
    expect(rows[0]![2]).toBe('theilSen');
    expect(rows.every(([k]) => !CYR.test(k))).toBe(true);
    expect(rows[0]![1]).toMatch(/^[−+]?\d+\.\d °C \/ 10 yr$/u);
  });

  it('charts: labels and aria in English', () => {
    const { container } = render(<LineChart series={r.series} zoneName="Pozniaky" />);
    expect(screen.getByTestId('linechart').getAttribute('aria-label')).toMatch(/^Summer land surface temperature: Pozniaky vs the forest/);
    expect(cyrillicLeaks(container)).toEqual([]);
  });

  it('export menu and search box in English', async () => {
    const { container } = render(<><ExportMenu reportId={null} shareUrl="https://x/" title="t" demo /><Search examples={[]} onSelect={noop} /></>);
    await userEvent.click(screen.getByTestId('export-btn'));
    expect(screen.getByTestId('export-btn').textContent).toMatch(/^Export/);
    expect(screen.getByRole('menu').textContent).toContain('PDF — printable report');
    expect(screen.getByRole('combobox').getAttribute('placeholder')).toBe('Enter your address or district');
    expect([...cyrillicLeaks(container), ...cyrillicLeaks(screen.getByRole('menu'))]).toEqual([]);
  });
});
