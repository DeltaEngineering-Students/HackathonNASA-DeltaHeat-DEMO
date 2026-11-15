// Sentence builders per language (I18N.md §5.3): whole sentences written for each language, never word-by-word
// templates. Inputs are report fields only; every number goes through the locale formatter with the same half-up
// rounding, so EN and UK always carry the same numbers. The Ukrainian builders reproduce lib/story.ts / lib/verdict.ts
// byte for byte (sentences.test.ts); at wiring time those libs delegate here by locale.
import type { ContextClimate, Hotspot, Report, Trend } from '../api/types';
import type { Locale } from './locale';
import { en } from './story.en';
import { uk } from './story.uk';

/** Rank of the zone among its city's districts (lib/story.ts Rank + the city id for English names). */
export interface RankIn {
  hotterThan: number; of: number;
  /** city id (kyiv | kharkiv | lviv); Ukrainian also accepts the ready genitive */
  city?: string; cityGen?: string;
  range?: [number, number];
  hottest?: { name: string; gap: number }; coolest?: { name: string; gap: number };
}

export interface NewBuiltIn {
  area_km2: number | null;
  before: { years: number[]; gap: number }; after: { years: number[]; gap: number };
  /** min / max of the per-year gap series, when ≥ 3 values (for the «smaller than the variation» remark) */
  spread?: [number, number] | null;
}

export interface Sentences {
  /** «hotter than the average of 7 of 9 Kyiv districts» (lower case, goes after a dash in the lead) */
  rank(r: RankIn): string;
  /** «For comparison: built-up land in Kyiv districts ranges from +6.8 (Holosiivskyi) to +9.7 °C (Desnianskyi).» */
  districtRange(r: RankIn): string | null;
  /** the reference forest's display name: «the forest around Kyiv» / «ліс навколо Києва» */
  forest(city: string | null | undefined, derived: boolean): string;
  /** n.s. trend caption: «no clear change (data from 8 summer seasons)» */
  stableHot(nSummers: number): string;
  parksCooler(gap: number): string;
  greenTrend(up: boolean, from: number | null, to: number | null): string;
  newBuilt(nb: NewBuiltIn): { lead: string; text: string; title: string };
  climate(c: ContextClimate, nModels?: number): { main: string; sub: string } | null;
  hotspotTip(h: Hotspot, i: number): string;
  /** Details §2 sentence, consistent with the backend verdict and the Theil–Sen interval */
  ci(t: Trend): string;
  /** Fallback lead when the backend sends no text in this language (pre-phase-3 backend); null = use the server text */
  verdict(r: Report, name?: string | null): string | null;
}

export const SENTENCES: Record<Locale, Sentences> = { en, uk };
export const sentences = (l: Locale): Sentences => SENTENCES[l];
