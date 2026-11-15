// UI locale (uhd/docs/I18N.md §1): precedence at boot: `?lang=` in the URL (shared links keep their language) →
// localStorage `uhd-lang` → DEFAULT_LOCALE. The browser language is deliberately NOT used.
// English by default (user request; flipped after the full «no Cyrillic in EN» sweep passed). Keep public/boot.js's
// DEFAULT in step. Reverting this one commit brings the Ukrainian default back.
import { useSyncExternalStore } from 'react';

export const LOCALES = ['en', 'uk'] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en';
export const STORAGE_KEY = 'uhd-lang';
export const URL_PARAM = 'lang';

/** BCP 47 tag for Intl (numbers, plurals, dates) and for <html lang>. */
export const INTL_TAG: Record<Locale, string> = { en: 'en-GB', uk: 'uk-UA' };
/** Switcher labels (I18N.md §3): always shown in their own language. */
export const LOCALE_LABEL: Record<Locale, string> = { en: 'EN', uk: 'УКР' };
export const LOCALE_NAME: Record<Locale, string> = { en: 'English', uk: 'Українська' };

export const isLocale = (x: unknown): x is Locale => typeof x === 'string' && (LOCALES as readonly string[]).includes(x);

/** `?lang=uk|en` (also accepts `ua`, `uk-UA`, `en-GB`, any case); null when absent or unknown. */
export function localeFromSearch(search: string): Locale | null {
  const v = new URLSearchParams(search).get(URL_PARAM)?.trim().toLowerCase();
  if (!v) return null;
  if (v === 'ua' || v.startsWith('uk')) return 'uk';
  if (v.startsWith('en')) return 'en';
  return null;
}

function readStored(): Locale | null {
  try {
    const v = globalThis.localStorage?.getItem(STORAGE_KEY);
    return isLocale(v) ? v : null;
  } catch {
    return null; // private mode / blocked storage
  }
}

function writeStored(l: Locale): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, l);
  } catch {
    /* ignore: the URL still carries the choice */
  }
}

export function detectLocale(search = typeof location !== 'undefined' ? location.search : ''): Locale {
  return localeFromSearch(search) ?? readStored() ?? DEFAULT_LOCALE;
}

/**
 * The search string with the locale applied: `lang=uk` for Ukrainian, no param for English (the default), other params
 * untouched. Share links use `withLang(…, l, true)` so an English link also opens in English for a Ukrainian-stored visitor.
 */
export function withLang(search: string, l: Locale, explicit = false): string {
  const p = new URLSearchParams(search);
  if (l === DEFAULT_LOCALE && !explicit) p.delete(URL_PARAM);
  else p.set(URL_PARAM, l);
  const s = p.toString();
  return s ? `?${s}` : '';
}

let current: Locale = DEFAULT_LOCALE;
const subs = new Set<() => void>();

export const getLocale = (): Locale => current;

function applyDocument(l: Locale): void {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = l;
}

/** Called once from main.tsx before the first render (index.html/boot.js set <html lang> even earlier). */
export function initLocale(search?: string): Locale {
  current = detectLocale(search);
  applyDocument(current);
  return current;
}

/** User switch: persist, reflect in the address bar (replaceState, no history entry), update <html lang>, re-render. */
export function setLocale(l: Locale): void {
  if (!isLocale(l)) return;
  writeStored(l);
  if (typeof location !== 'undefined' && typeof history !== 'undefined') {
    const next = `${location.pathname}${withLang(location.search, l)}${location.hash}`;
    if (next !== `${location.pathname}${location.search}${location.hash}`) history.replaceState(history.state, '', next);
  }
  if (l === current) return;
  current = l;
  applyDocument(l);
  for (const f of subs) f();
}

export function subscribeLocale(f: () => void): () => void {
  subs.add(f);
  return () => subs.delete(f);
}

/** React hook: the current locale; components re-render on a switch. */
export const useLocale = (): Locale => useSyncExternalStore(subscribeLocale, getLocale, getLocale);
