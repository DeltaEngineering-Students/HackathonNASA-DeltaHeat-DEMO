import { GLOSSARY, MORE_MAX, SHORT_MAX, type GlossaryKey } from '../lib/glossary';
import { GLOSSARY_EN } from './glossary.en';

const keys = Object.keys(GLOSSARY) as GlossaryKey[];
const CYR = /[А-Яа-яІіЇїЄєҐґ]/;

describe('English glossary', () => {
  it('has exactly the Ukrainian keys', () => {
    expect(Object.keys(GLOSSARY_EN).sort()).toEqual([...keys].sort());
  });
  it.each(keys)('%s: non-empty, short ≤ 140, more ≤ 400, more iff Ukrainian has more, no Cyrillic', (k) => {
    const e = GLOSSARY_EN[k];
    expect(e.term.trim()).not.toBe('');
    expect(e.short.length).toBeLessThanOrEqual(SHORT_MAX);
    if (e.more !== undefined) expect(e.more.length).toBeLessThanOrEqual(MORE_MAX);
    expect(e.more === undefined).toBe(GLOSSARY[k].more === undefined);
    expect(`${e.term} ${e.short} ${e.more ?? ''}`).not.toMatch(CYR);
  });
  it('uses the decimal point (no «0,05»), and keeps every number of the Ukrainian text', () => {
    const nums = (s: string) => (s.match(/\d+(?:[.,]\d+)?/g) ?? []).map((x) => x.replace(',', '.')).sort();
    for (const k of keys) {
      const e = GLOSSARY_EN[k], u = GLOSSARY[k];
      expect(`${e.short} ${e.more ?? ''}`, k).not.toMatch(/\d,\d(?!\d\d)/);
      // thousands separators aside, the same numbers in the same quantity
      // «15 September 2026» (TERMS-EN §10) counts as the Ukrainian «15.09.2026»
      const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
      const longDate = (s: string) => s.replace(new RegExp(`(\\d{1,2}) (${MONTHS.join('|')}) (\\d{4})`, 'g'),
        (_, d: string, m: string, y: string) => `${d.padStart(2, '0')}.${String(MONTHS.indexOf(m) + 1).padStart(2, '0')}.${y}`);
      const en = nums(longDate(`${e.term} ${e.short} ${e.more ?? ''}`).replace(/(\d),(\d{3})/g, '$1$2'));
      const ukN = nums(`${u.term} ${u.short} ${u.more ?? ''}`);
      expect(en, k).toEqual(ukN);
    }
  });
  it('terms are unique', () => {
    const t = keys.map((k) => GLOSSARY_EN[k].term);
    expect(new Set(t).size).toBe(t.length);
  });
});
