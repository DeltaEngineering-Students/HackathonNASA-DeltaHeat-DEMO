import { GLOSSARY, MORE_MAX, SHORT_MAX, gloss, type GlossaryKey } from './glossary';

const keys = Object.keys(GLOSSARY) as GlossaryKey[];

describe('glossary (tooltips data)', () => {
  it('has entries', () => {
    expect(keys.length).toBeGreaterThan(50);
  });

  it.each(keys)('%s: non-empty term and short ≤ 140 chars, more ≤ 400', (k) => {
    const e = gloss(k);
    expect(e.term.trim()).not.toBe('');
    expect(e.short.trim()).not.toBe('');
    expect(e.short.length).toBeLessThanOrEqual(SHORT_MAX);
    if (e.more !== undefined) {
      expect(e.more.trim()).not.toBe('');
      expect(e.more.length).toBeLessThanOrEqual(MORE_MAX);
    }
  });

  it.each(keys)('%s: seeAlso keys exist, are unique and not self', (k) => {
    const see = GLOSSARY[k].seeAlso ?? [];
    for (const s of see) {
      expect(keys).toContain(s);
      expect(s).not.toBe(k);
    }
    expect(new Set(see).size).toBe(see.length);
  });

  it('uses the decimal comma in numbers (no «0.05» style)', () => {
    for (const k of keys) {
      const e = GLOSSARY[k];
      // allowed points: SSP names («SSP2‑4.5») and dates («15.09.2026»)
      const text = `${e.term} ${e.short} ${e.more ?? ''}`.replace(/SSP\d[‑-]\d\.\d/g, '').replace(/\d{2}\.\d{2}\.\d{4}/g, '');
      expect(text, k).not.toMatch(/\d\.\d/);
    }
  });

  it('terms are unique', () => {
    const terms = keys.map((k) => GLOSSARY[k].term);
    expect(new Set(terms).size).toBe(terms.length);
  });
});
