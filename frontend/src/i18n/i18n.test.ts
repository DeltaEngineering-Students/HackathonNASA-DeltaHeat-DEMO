import { en } from './en';
import { uk } from './uk';
import { DICTS, segments, tagsOf, tr } from './index';
import { GLOSSARY_EN } from './glossary.en';
import { PARTS_EN, PARTS_UK } from './parts';

const keys = Object.keys(en) as (keyof typeof en)[];
const CYR = /[А-Яа-яІіЇїЄєҐґ]/;
const vars = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const texts = (v: unknown): string[] => (typeof v === 'string' ? [v] : Object.values(v as Record<string, string>));
// names that stay in their own script: the language switch labels
const OWN_SCRIPT = new Set<keyof typeof en>(['app.langToUk', 'app.langToEn']);

describe('dictionaries', () => {
  it('have the same keys', () => {
    expect(Object.keys(uk).sort()).toEqual([...keys].sort());
  });

  it.each(keys)('%s: non-empty, same placeholders and tags in en and uk', (k) => {
    const e = texts(en[k]), u = texts(uk[k]);
    for (const s of [...e, ...u]) expect(s.trim(), k).not.toBe('');
    expect(vars(u[0]!)).toEqual(vars(e[0]!));
    expect(tagsOf(u[0]!)).toEqual(tagsOf(e[0]!));
  });

  it('plural entries: en has one/other, uk has one/few/many/other', () => {
    for (const k of keys) {
      if (typeof en[k] === 'string') { expect(typeof uk[k]).toBe('string'); continue; }
      expect(Object.keys(en[k]).sort()).toEqual(['one', 'other']);
      expect(Object.keys(uk[k] as object).sort()).toEqual(['few', 'many', 'one', 'other']);
    }
  });

  it('English has no Cyrillic, Ukrainian uses the decimal comma, English the point', () => {
    for (const k of keys) {
      for (const s of texts(en[k])) if (!OWN_SCRIPT.has(k)) expect(s, k).not.toMatch(CYR);
      for (const s of texts(uk[k])) expect(s.replace(/SSP\d[‑-]\d\.\d/g, ''), k).not.toMatch(/\d\.\d/);
      for (const s of texts(en[k])) expect(s, k).not.toMatch(/\d,\d(?!\d\d)/);
    }
  });

  it('English avoids the banned terms (TERMS-EN)', () => {
    const all = keys.flatMap((k) => texts(en[k])).join('\n').replace(/\{\w+\}/g, '');
    const gl = Object.values(GLOSSARY_EN).map((e) => `${e.term} ${e.short} ${e.more ?? ''}`).join('\n');
    for (const text of [all, gl]) expect(text).not.toMatch(/\bdelta\b|\banomaly\b|\bscenes?\b|°C\/decade|\bzone\b|\bproven\b|\bKiev\b|Kharkov|\bLvov\b|Odessa/i);
  });
});

describe('slot parts (parts/*.en.ts / *.uk.ts)', () => {
  const sources: [string, Record<string, unknown>][] = [['en.ts', en], ...Object.entries(PARTS_EN).map(([n, d]) => [`parts/${n}.en.ts`, d] as [string, Record<string, unknown>])];
  it('no key appears twice across en.ts and the parts', () => {
    const seen = new Map<string, string>();
    const dup: string[] = [];
    for (const [file, d] of sources) for (const k of Object.keys(d)) { if (seen.has(k)) dup.push(`${k}: ${seen.get(k)} + ${file}`); else seen.set(k, file); }
    expect(dup).toEqual([]);
  });
  it.each(Object.keys(PARTS_EN) as (keyof typeof PARTS_EN)[])('%s: same keys, non-empty, same placeholders/tags, no Cyrillic in en', (slot) => {
    const e = PARTS_EN[slot] as Record<string, unknown>, u = PARTS_UK[slot] as Record<string, unknown>;
    expect(Object.keys(u).sort()).toEqual(Object.keys(e).sort());
    for (const k of Object.keys(e)) {
      const es = texts(e[k]), us = texts(u[k]);
      for (const s of [...es, ...us]) expect(s.trim(), k).not.toBe('');
      expect(vars(us[0]!), k).toEqual(vars(es[0]!));
      expect(tagsOf(us[0]!), k).toEqual(tagsOf(es[0]!));
      for (const s of es) expect(s, k).not.toMatch(CYR);
    }
  });
  it('t() finds part keys', () => {
    for (const d of Object.values(DICTS)) expect(Object.keys(d).length).toBeGreaterThanOrEqual(Object.keys(en).length);
  });
});

describe('t()', () => {
  it('interpolates and pluralises per locale', () => {
    expect(tr('en', 'draw.tooSmall', { area: '0.31', min: '0.5' })).toBe('The area is too small: 0.31 km². At least 0.5 km² is needed, otherwise the result is not representative.');
    expect(tr('uk', 'cardYear.value', { year: 2022, value: '+9,1 °C' })).toBe('У 2022: +9,1 °C');
    expect(tr('en', 'count.districts', { n: 1 })).toBe('1 district');
    expect(tr('en', 'count.districts', { n: 9 })).toBe('9 districts');
    expect(tr('uk', 'count.districts', { n: 1 })).toBe('1 район');
    expect(tr('uk', 'count.districts', { n: 3 })).toBe('3 райони');
    expect(tr('uk', 'count.districts', { n: 11 })).toBe('11 районів');
    expect(tr('uk', 'count.districts', { n: 22 })).toBe('22 райони');
    expect(tr('uk', 'count.models', { n: 5 })).toBe('5 моделей');
  });

  it('every locale is complete', () => {
    for (const d of Object.values(DICTS)) for (const k of keys) expect(d[k], k).toBeDefined();
  });
});

describe('segments()', () => {
  it('splits tags, keeps comparison signs and unknown markup as text', () => {
    expect(segments('a <gap>b</gap> c')).toEqual([{ text: 'a ', tags: [] }, { text: 'b', tags: ['gap'] }, { text: ' c', tags: [] }]);
    expect(segments('p < 0.05 and <b><x>y</x></b>')).toEqual([{ text: 'p < 0.05 and ', tags: [] }, { text: 'y', tags: ['b', 'x'] }]);
    expect(segments('<lonely> open')).toEqual([{ text: '<lonely> open', tags: [] }]);
    const s = tr('en', 'details.howSurface');
    expect(segments(s).map((x) => x.text).join('')).not.toMatch(/[<>]/);
  });
});
