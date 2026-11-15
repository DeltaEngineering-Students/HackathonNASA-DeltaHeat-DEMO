import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnswerCard } from './AnswerCard';
import { REPORTS } from '../fixtures';
import type { Report } from '../api/types';

const base = REPORTS['kyiv-pozniaky']!;
const ns: Report = {
  ...base,
  trend: { ...base.trend, verdict: 'not_significant' },
  gap_summary: { ...base.gap_summary, mean: 10.45 },
  zone: { ...base.zone, analysed: 'built' },
  green_gap: 9.66, green_scope: 'urban_parks',
  hotspots: [{ center: [30.63, 50.41], gap: 13.2 }, { center: [30.62, 50.40], gap: 11.05 }],
  context: {
    rank: { rank: 2, of: 11, city: 'kyiv', compared_to_uk: 'порівняно із забудовою 10 районів Києва', like_for_like: true, note_uk: 'Зона невелика (2,9 км² забудови).' },
    climate: { scenario: 'ssp245', period: '2041-2050', delta: 1.95, baseline_period: '2005-2014' },
  },
};
const sel = { kind: 'preset' as const, id: 'kyiv-pozniaky', name: 'Позняки (≈1 км)' };
const noop = () => {};
/** text as seen: without the tips' screen-reader copies (item 22) */
const visible = (el: HTMLElement) => { const c = el.cloneNode(true) as HTMLElement; c.querySelectorAll('.sr-only').forEach((n) => n.remove()); return c.textContent; };

describe('AnswerCard: not-significant story', () => {
  it('leads with the magnitude, rank, factors, hotspots and the air outlook', async () => {
    const onHotspot = vi.fn();
    render(<AnswerCard selection={sel} state={{ status: 'ready', report: ns }} onDetails={noop} onRetry={noop} onSearch={noop} onHotspot={onHotspot} />);
    const lead = screen.getByTestId('verdict');
    expect(lead.textContent).toMatch(/на 10,5\s°C гарячіша/u);
    expect(screen.getByTestId('rank').textContent).toBe('гарячіше, ніж у середньому в 9 з 10 районів Києва');
    expect(screen.getByText(/помітної зміни не видно \(дані \d+ літніх сезонів\)/)).toBeTruthy();
    expect(screen.getByTestId('rank-note').textContent).toBe('Порівняно із забудовою 10 районів Києва. Зона невелика (2,9 км² забудови).');
    expect(screen.getByTestId('factors').textContent).toMatch(/Парки й сквери в місті на 9,7\s°C прохолодніші/u);
    expect(visible(screen.getByTestId('climate-line'))).toMatch(/^Прогноз: до 2050 денний максимум приземної температури повітря \(на висоті 2 м\) зросте приблизно на \+2,0\s°C \(порівняно з 2005–2014\)\..*Повітря, не поверхня\./u);
    const chips = screen.getByTestId('hotspots').querySelectorAll('button:not(.term)');
    expect(chips).toHaveLength(2);
    expect(chips[1]!.textContent).toMatch(/^2 \+11,1\s°C$/u);
    expect(chips[1]!.getAttribute('title')).toBe('Місце 2: на 11,1 °C гарячіше за ліс.');
    await userEvent.click(chips[0]!);
    expect(onHotspot).toHaveBeenCalledWith([30.63, 50.41]);
  });
  it('significant trends keep the backend sentence', () => {
    const sig: Report = { ...ns, trend: { ...ns.trend, verdict: 'significant' } };
    render(<AnswerCard selection={sel} state={{ status: 'ready', report: sig }} onDetails={noop} onRetry={noop} onSearch={noop} />);
    expect(screen.queryByText(/помітної зміни не видно/)).toBeNull();
  });
  it('not like-for-like: rank leaves the headline, the districts range shows under the numbers', () => {
    const small: Report = { ...ns, context: { ...ns.context, rank: { rank: 1, of: 11, city: 'kyiv', like_for_like: false, district_gap_range: [6.78, 9.7], note_uk: 'Зона невелика: щільний квартал зазвичай гарячіший за середнє по цілому району.' } } };
    render(<AnswerCard selection={sel} state={{ status: 'ready', report: small }} onDetails={noop} onRetry={noop} onSearch={noop} />);
    expect(screen.queryByTestId('rank')).toBeNull();
    expect(screen.getByTestId('district-range').textContent).toBe('Для порівняння: забудова районів Києва — від +6,8 до +9,7 °C.');
    // the reason stays available below the fold
    expect(screen.getByTestId('rank-note').textContent?.trim()).toBe('Зона невелика: щільний квартал зазвичай гарячіший за середнє по цілому району.');
  });
  it('empty state lists only caveats that matter without a gap (R4/R5-2)', () => {
    const none: Report = { ...ns, caveats: ['lst_not_air', 'composite_method', 'no_lst_product', 'war_zone', 'derived_reference'].map((code) => ({ code, text_uk: code })) };
    render(<AnswerCard selection={sel} state={{ status: 'empty', report: none }} onDetails={noop} onRetry={noop} onSearch={noop} />);
    expect([...screen.getByTestId('empty-caveats').querySelectorAll('li')].map((li) => li.textContent)).toEqual(['• no_lst_product', '• war_zone']);
  });
  it('R7-3: Маріуполь-like empty state keeps the absence / place caveats, drops ref_* and other method caveats', () => {
    const codes = ['ref_higher', 'ref_weak', 'no_lst_product', 'basis_always_built', 'occupied', 'composite_method', 'few_years',
      'derived_reference', 'classes_extrapolated', 'lst_not_air', 'geocoder_circle', 'zone_clipped', 'some_future_method_note'];
    const none: Report = { ...ns, caveats: codes.map((code) => ({ code, text_uk: code })) };
    render(<AnswerCard selection={sel} state={{ status: 'empty', report: none }} onDetails={noop} onRetry={noop} onSearch={noop} />);
    expect([...screen.getByTestId('empty-caveats').querySelectorAll('li')].map((li) => li.textContent))
      .toEqual(['• no_lst_product', '• occupied', '• few_years', '• geocoder_circle', '• zone_clipped']);
  });
  it('R7-3: no list at all when only method caveats remain', () => {
    const none: Report = { ...ns, caveats: ['ref_higher', 'lst_not_air'].map((code) => ({ code, text_uk: code })) };
    render(<AnswerCard selection={sel} state={{ status: 'empty', report: none }} onDetails={noop} onRetry={noop} onSearch={noop} />);
    expect(screen.queryByTestId('empty-caveats')).toBeNull();
  });
});

describe('hotspot row label', () => {
  it('says which summers the points are for', () => {
    const r: Report = { ...ns, hotspots: [{ center: [30.63, 50.41], gap: 13.2, years: [2023, 2024, 2025] }, { center: [30.62, 50.40], gap: 11.05, years: [2023, 2025] }] };
    render(<AnswerCard selection={sel} state={{ status: 'ready', report: r }} onDetails={noop} onRetry={noop} onSearch={noop} />);
    expect(visible(screen.getByTestId('hotspots').querySelector('.hot-row-h') as HTMLElement)).toBe('Гарячі точки (2023–2025):');
  });
});
