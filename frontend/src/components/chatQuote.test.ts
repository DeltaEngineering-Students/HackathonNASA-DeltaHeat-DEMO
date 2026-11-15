import { describe, expect, it } from 'vitest';
import { appendQuote, plainFromMarkdown, QUOTE_MAX, splitQuote, toQuote } from './chatQuote';

describe('chat quote', () => {
  it('prefixes every line and ends with an empty line', () => {
    expect(toQuote('Перший рядок\nДругий')).toBe('> Перший рядок\n> Другий\n\n');
    expect(toQuote('a\n\nb')).toBe('> a\n>\n> b\n\n');
    expect(toQuote('  ')).toBe('');
  });
  it('truncates long text at a word boundary to about 300 characters', () => {
    const q = toQuote('слово '.repeat(200));
    const body = q.slice(2).trimEnd();
    expect(body.length).toBeLessThanOrEqual(QUOTE_MAX + 1);
    expect(body.endsWith('…')).toBe(true);
    expect(body.endsWith(' …')).toBe(false);
  });
  it('strips markdown from an answer', () => {
    expect(plainFromMarkdown('**Факти**\n\n- на 7,7 °C [на мапі](uhd:place/x)')).toBe('Факти\n\n• на 7,7 °C на мапі');
  });
  it('appends after existing input', () => {
    expect(appendQuote('', '> a\n\n')).toBe('> a\n\n');
    expect(appendQuote('Чому?', '> a\n\n')).toBe('Чому?\n\n> a\n\n');
  });
  it('splits a user message into quote and rest', () => {
    expect(splitQuote('> a\n> b\n\nЧому так?')).toEqual({ quote: 'a\nb', rest: 'Чому так?' });
    expect(splitQuote('просто')).toEqual({ quote: null, rest: 'просто' });
    expect(splitQuote('питання\n> не цитата')).toEqual({ quote: null, rest: 'питання\n> не цитата' });
  });
});
