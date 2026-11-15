// Server texts (I18N.md §6): the API sends `<field>_uk` and, with `?lang=en` (backend phase 3), `<field>_en`.
// `text_en: null` means the backend could not produce a faithful English text (unknown template) — then we show the
// Ukrainian one and mark it `lang="uk"`, never a guessed translation.
import type { Locale } from './locale';

export interface Localized { text: string; lang: Locale }

type Bag = Record<string, unknown> | null | undefined;

/** pick(caveat, 'text', 'en') → caveat.text_en ?? caveat.text_uk; '' when neither exists. */
export function pick(obj: Bag, base: string, l: Locale): Localized {
  const want = obj?.[`${base}_${l}`];
  if (typeof want === 'string' && want.trim()) return { text: want, lang: l };
  for (const alt of ['uk', 'en'] as const) {
    const v = obj?.[`${base}_${alt}`];
    if (typeof v === 'string' && v.trim()) return { text: v, lang: alt };
  }
  return { text: '', lang: l };
}

/** Plain string when the language marker is not needed. */
export const pickText = (obj: Bag, base: string, l: Locale): string => pick(obj, base, l).text;

/** Query suffix for endpoints that localise on read (`/api/analyze`, `/api/reports/{id}`, overlays, overview, exports). */
export const langQuery = (l: Locale, sep: '?' | '&' = '&') => `${sep}lang=${l}`;
