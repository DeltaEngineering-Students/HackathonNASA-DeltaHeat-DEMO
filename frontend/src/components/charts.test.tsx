import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GapBars, labelLines, LineChart, niceTicks, trendLine, YearBars } from './charts';
import { REPORTS, YEARS } from '../fixtures';

const r = REPORTS['kyiv-pozniaky']!;

describe('charts', () => {
  it('card chart: isolated summers are dots, the last data year is labelled, gaps get ticks (QA-UX R4-5, R4-5b)', () => {
    // Сарни-like: 2014 alone between gaps; data ends in 2024; 2025 missing
    const vals: Record<number, [number, number] | null> = { 2013: null, 2014: [36, 30], 2015: null, 2016: [41, 30], 2017: [39, 31], 2018: [40, 31],
      2019: [38, 31], 2020: [36, 31], 2021: [40, 31], 2022: null, 2023: null, 2024: [37, 31], 2025: null };
    const series = Object.entries(vals).map(([y, v]) => ({ ...r.series[0]!, year: +y, zone_lst: v?.[0] ?? null, ref_lst: v?.[1] ?? null }));
    const { container } = render(<LineChart series={series} zoneName="Сарни" />);
    // 2014 and 2024 are lone points on both lines → r=3 dots (plus the r=4 end dots)
    expect(container.querySelectorAll('circle[r="3"]').length).toBe(4);
    const labels = [...container.querySelectorAll('text')].map((t) => t.textContent);
    expect(labels.some((x) => x?.startsWith('2013 · '))).toBe(true); // first year missing: the band label names it
    expect(labels.some((x) => x?.startsWith('2025 · '))).toBe(true); // the trailing gap is named by its band label, not a bare tick
    expect(container.querySelectorAll('[data-testid="chart-nodata"]')).toHaveLength(4); // 2013, 2015, 2022–2023, 2025
  });
  it('card chart: a missing summer gets a hatched band, a labelled «year · н/д» and the reason as tooltip', () => {
    const base = (y: number, v: [number, number] | null, excluded: string | null = null) =>
      ({ ...r.series[0]!, year: y, zone_lst: v?.[0] ?? null, ref_lst: v?.[1] ?? null, excluded });
    const series = [2020, 2021, 2022, 2023, 2024].map((y) => base(y, y === 2022 ? null : [38, 30], y === 2022 ? 'low_coverage' : null));
    const { container } = render(<LineChart series={series} zoneName="Кременчук" />);
    const g = container.querySelectorAll('[data-testid="chart-nodata"]');
    expect(g).toHaveLength(1);
    expect(g[0]!.querySelector('rect')).not.toBeNull();
    expect(g[0]!.querySelector('text')!.textContent).toMatch(/^2022 · /);
    expect(g[0]!.querySelector('title')!.textContent).toMatch(/^2022: .+/);
    // the old lone tick under the axis is gone
    expect(container.querySelectorAll('svg > line')).toHaveLength(0);
  });
  it('card chart: the band label never overlaps the end-year label (gap 3 years from the end)', () => {
    const series = Array.from({ length: 13 }, (_, i) => ({ ...r.series[0]!, year: 2013 + i, zone_lst: 2013 + i === 2022 ? null : 38, ref_lst: 2013 + i === 2022 ? null : 30 }));
    const { container } = render(<LineChart series={series} zoneName="Кременчук" w={384} />);
    const texts = [...container.querySelectorAll('svg > text, svg > g > text')].filter((t) => /^\d{4}( · .*)?$/.test(t.textContent!));
    const box = (t: Element) => {
      const x = +t.getAttribute('x')!, wd = t.textContent!.length * 7, an = t.getAttribute('text-anchor');
      return an === 'end' ? [x - wd, x] : an === 'middle' ? [x - wd / 2, x + wd / 2] : [x, x + wd];
    };
    const boxes = texts.map(box);
    expect(texts.some((t) => t.textContent!.startsWith('2022 · '))).toBe(true);
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(boxes[i]![1]! <= boxes[j]![0]! || boxes[j]![1]! <= boxes[i]![0]!).toBe(true);
  });
  it('card chart: several missing summers merge into one band; edge gaps stay inside the plot', () => {
    const mk = (y: number, ok: boolean) => ({ ...r.series[0]!, year: y, zone_lst: ok ? 38 : null, ref_lst: ok ? 30 : null });
    const series = [[2018, false], [2019, true], [2020, true], [2021, false], [2022, false], [2023, true], [2024, false], [2025, false]]
      .map(([y, ok]) => mk(y as number, ok as boolean));
    const { container } = render(<LineChart series={series} zoneName="Сарни" w={384} />);
    const gs = [...container.querySelectorAll('[data-testid="chart-nodata"]')];
    expect(gs.map((x) => x.querySelector('text')!.textContent!.split(' · ')[0])).toEqual(['2018', '2021–2022', '2024–2025']);
    for (const x of gs) {
      const rect = x.querySelector('rect')!;
      const x0 = +rect.getAttribute('x')!, w1 = +rect.getAttribute('width')!;
      expect(x0).toBeGreaterThanOrEqual(34); // padL
      expect(x0 + w1).toBeLessThanOrEqual(384 - 100 + 0.01); // right edge of the plot (padR)
    }
  });
  it('direct labels wrap instead of truncating', () => {
    expect(labelLines('Позняки (≈1 км)')).toEqual(['Позняки']);
    expect(labelLines('Голосіївський ліс', 10)).toEqual(['Голосіїв-', 'ський ліс']);
    expect(labelLines('Драгоманова', 10)).toEqual(['Драгомано-', 'ва']);
    expect(labelLines('Нижні Сади (Осокорки)')).toEqual(['Нижні Сади']);
    expect(labelLines('Котеджне містечко «Деснянське»')).toEqual(['Котеджне', 'містечко…']);
  });
  it('nice ticks', () => {
    expect(niceTicks(28, 46)).toEqual([30, 36, 42]);
  });
  it('trend line passes through the median residual', () => {
    expect(trendLine([1, 2, 3], 1).b).toBe(1);
  });
  it('line chart labels both lines directly and breaks on gaps', () => {
    const series = structuredClone(r.series);
    series[7]!.zone_lst = null;
    const { container } = render(<LineChart series={series} zoneName="Позняки" />);
    expect(screen.getByText('Позняки')).toBeInTheDocument();
    expect(screen.getByText('ліс навколо')).toBeInTheDocument();
    // two runs for the zone line, one for the forest + band runs
    expect(container.querySelectorAll('path[stroke="var(--heat)"]').length).toBe(2);
  });
  it('gap bars highlight the selected year', () => {
    render(<GapBars series={r.series} trend={r.trend} mean={r.gap_summary.mean} selectedYear={2025} zoneName="Позняки" />);
    expect(screen.getByText('сер.')).toBeInTheDocument();
    expect(screen.getByText('+9,0°')).toBeInTheDocument();
    expect(screen.getByText('+4,9')).toBeInTheDocument();
  });
  it('year bars are a keyboard radiogroup', async () => {
    const onChange = vi.fn();
    render(<YearBars series={r.series} years={YEARS} year={2025} onChange={onChange} />);
    const cur = screen.getByRole('radio', { checked: true });
    expect(cur).toHaveAccessibleName(/2025, розрив \+4,9°C/);
    cur.focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(onChange).toHaveBeenCalledWith(2024);
    await userEvent.keyboard('{Home}');
    expect(onChange).toHaveBeenCalledWith(2013);
  });
});
