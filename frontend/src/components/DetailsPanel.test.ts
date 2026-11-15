import { numbersToCheck } from './DetailsPanel';
import { adaptReport } from '../api/adapt';
import { REPORTS } from '../fixtures';
import type { Report } from '../api/types';

const base = REPORTS['kyiv-pozniaky']!;

describe('numbers to check (QA-17, sci-v3.2)', () => {
  it('lowest coverage ignores excluded years; excluded years get a human reason', () => {
    const r: Report = {
      ...base,
      series: base.series.map((s) => (s.year === 2020 ? { ...s, gap: null, valid_share: 0.5, method: null, excluded: 'low_coverage' } : s)),
    };
    const rows = Object.fromEntries(numbersToCheck(r));
    expect(rows['Найменша частка ділянки без хмар']).not.toContain('2020');
    expect(rows['Пропущені роки']).toBe('2020 — хмари закрили більшу частину ділянки');
    expect(JSON.stringify(rows)).not.toMatch(/low_coverage|always_built|urban_parks/);
  });
  it('basis, secondary, new-built and parks rows in Ukrainian', () => {
    const r: Report = {
      ...base,
      zone: { ...base.zone, basis: 'always_built', analysed_area_km2: 2.89 },
      green_gap: 4.2, green_scope: 'urban_parks',
      secondary: { basis: 'built_each_year', gap_summary: { mean: 11.5 }, trend: { ...base.trend } },
      new_built_gap: { area_km2: 0.4, before: { years: [2013, 2014], gap: 2.1 }, after: { years: [2024, 2025], gap: 9.3 } },
    };
    const rows = Object.fromEntries(numbersToCheck(r));
    expect(rows['Що рахуємо']).toMatch(/^ділянки, забудовані в усі роки/);
    expect(rows['Варіант «забудова кожного року»']).toMatch(/^\+11,5/);
    expect(rows['Нова забудова: до / після']).toMatch(/\+2,1\s°C \(2013, 2014\) → \+9,3\s°C \(2024, 2025\)/u);
    expect(rows['Забудова − парки й сквери всередині міста']).toBeDefined();
  });
  it('adaptReport keeps the green scope and nulls the method of gap-less years', () => {
    const raw = { ...base, green_gap: { mean: 3, last: 3, scope: 'urban_parks' }, series: [{ ...base.series[0]!, gap: null, method: 'composite' }] };
    const r = adaptReport(raw as unknown as Record<string, unknown>);
    expect(r.green_gap).toBe(3);
    expect(r.green_scope).toBe('urban_parks');
    expect(r.series[0]!.method).toBeNull();
  });
});

import { driverSentence } from './DetailsPanel';
import { excludedLabel } from '../lib/verdict';
describe('sci-v3.3', () => {
  it('plain sentence on what drives the gap', () => {
    expect(driverSentence('zone')).toMatch(/саму забудову/);
    expect(driverSentence('reference')).toMatch(/ліс-еталон/);
    expect(driverSentence(null)).toBeNull();
  });
  it('no_lst_product has a human reason', () => {
    expect(excludedLabel('no_lst_product')).toMatch(/немає супутникової температури/);
  });
});

import { skippedYears } from './DetailsPanel';
describe('skipped years', () => {
  it('groups years by reason into ranges', () => {
    const rows = [2013, 2014, 2015, 2017].map((year) => ({ year, excluded: 'no_lst_product' })).concat([{ year: 2020, excluded: 'too_few_scenes' }]);
    expect(skippedYears(rows)).toMatch(/^2013–2015, 2017 — немає супутникової .*; 2020 — /);
  });
});

describe('sci-v3.4 excluded_detail', () => {
  it('uses the backend sentence for too_few_scenes years', () => {
    const t = 'Лише один чистий проліт над зоною (16.08). З 12 прольотів за літо 4 — хмарні над зоною, у 7 зона поза смугою знімання або на її краю. Для річного значення потрібно щонайменше 2.';
    expect(skippedYears([{ year: 2020, excluded: 'too_few_scenes', excluded_detail: { text_uk: t } }])).toBe(`2020 — ${t}`);
  });
});

describe('ring wording (item 18 E)', () => {
  it('measured from the city edge, not the centre', async () => {
    const { numbersToCheck } = await import('./DetailsPanel');
    const { REPORTS } = await import('../fixtures');
    const rows = Object.fromEntries(numbersToCheck(REPORTS['kyiv-pozniaky']!));
    expect(rows['Ліс-еталон']).toMatch(/^у кільці \d+–\d+ км від межі міста \(забудованої території\), не від центру; /);
  });
});
