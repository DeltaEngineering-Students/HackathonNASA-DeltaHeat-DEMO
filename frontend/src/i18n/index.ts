// t(): typed lookup + `{placeholder}` interpolation + plurals (Intl.PluralRules) + `<tag>…</tag>` rich segments.
// No i18n library: ~300 keys, two locales, everything is typed (I18N.md §5).
import { en } from './en';
import { uk } from './uk';
import { plural, type PluralForms } from './format';
import { getLocale, useLocale, type Locale } from './locale';
import type { AllMessages, MsgKey, Params } from './messages';
import { PARTS_EN, PARTS_UK } from './parts';

export * from './locale';
export type { MsgKey, Messages, AllMessages, Params, UkOf } from './messages';

/** Core + every slot part (parts/index.ts). Duplicate keys are a test failure (i18n.test.ts), never an override. */
export const DICTS: Record<Locale, AllMessages> = {
  en: Object.assign({}, en, ...Object.values(PARTS_EN)) as AllMessages,
  uk: Object.assign({}, uk, ...Object.values(PARTS_UK)) as AllMessages,
};

const fill = (s: string, p: Record<string, unknown> | undefined) =>
  p ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in p ? String(p[k]) : m)) : s;

type Args<K extends MsgKey> = keyof Params<K> extends never ? [params?: Params<K>] : [params: Params<K>];

/** Translate for an explicit locale (pure; use in libs and tests). */
export function tr<K extends MsgKey>(l: Locale, key: K, ...[params]: Args<K>): string {
  const m = (DICTS[l][key] ?? DICTS.en[key]) as string | PluralForms;
  const p = params as Record<string, unknown> | undefined;
  if (typeof m === 'string') return fill(m, p);
  return fill(plural(Number(p?.n ?? 0), l, m), p);
}

/** Translate for the current locale (non-React code; re-render comes from useT/useLocale in components). */
export const t = <K extends MsgKey>(key: K, ...args: Args<K>): string => tr(getLocale(), key, ...args);

/** Hook: `const t = useT(); t('card.details')` — re-renders on a language switch. */
export function useT() {
  const l = useLocale();
  return <K extends MsgKey>(key: K, ...args: Args<K>): string => tr(l, key, ...args);
}

/** A run of rich text: plain, or wrapped in a tag (`<gap>розрив</gap>` → {tag: 'gap', text: 'розрив'}). */
export interface Segment { text: string; tags: string[] }

/**
 * Splits `<tag>…</tag>` markup (nesting allowed, no attributes) into segments, so a component can render a glossary
 * <Term k={tag}> or <b> without HTML in the dictionary. Unknown or unbalanced markup stays plain text.
 */
export function segments(s: string): Segment[] {
  const out: Segment[] = [];
  const stack: string[] = [];
  const re = /<(\/?)([A-Za-z][\w]*)>/g;
  let last = 0;
  const push = (text: string) => { if (text) out.push({ text, tags: [...stack] }); };
  for (const m of s.matchAll(re)) {
    const [whole, close, tag] = m;
    const i = m.index ?? 0;
    if (close ? stack[stack.length - 1] !== tag : !s.includes(`</${tag}>`, i)) continue; // not markup: keep as text
    push(s.slice(last, i));
    if (close) stack.pop(); else stack.push(tag!);
    last = i + whole.length;
  }
  push(s.slice(last));
  return out;
}

/** Tag names used in a string (tests: en and uk must use the same tags). */
export const tagsOf = (s: string) => [...s.matchAll(/<([A-Za-z]\w*)>/g)].map((m) => m[1]!).sort();
