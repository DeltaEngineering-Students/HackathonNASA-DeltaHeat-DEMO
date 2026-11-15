// Dictionary types: en.ts (+ the slot parts in parts/) is the source of keys and placeholders.
import { en } from './en';
import type { PluralForms } from './format';
import type { mapEn } from './parts/map.en';
import type { detailsEn } from './parts/details.en';
import type { searchEn } from './parts/search.en';
import type { chatEn } from './parts/chat.en';
import type { polishEn } from './parts/polish.en';

/** The Ukrainian shape of an English dictionary: same keys; plural entries stay plural (uk adds few / many). */
export type UkOf<T> = { readonly [K in keyof T]: T[K] extends string ? string : PluralForms };

type AllEn = typeof en & typeof mapEn & typeof detailsEn & typeof searchEn & typeof chatEn & typeof polishEn;
export type MsgKey = keyof AllEn;
export type Msg = string | PluralForms;
/** Core dictionary (en.ts / uk.ts). */
export type Messages = UkOf<typeof en>;
/** Everything t() can look up: core + parts. */
export type AllMessages = UkOf<AllEn>;

type Vars<S> = S extends `${string}{${infer V}}${infer R}` ? V | Vars<R> : never;
type Src<K extends MsgKey> = AllEn[K];
type Text<K extends MsgKey> = Src<K> extends string ? Src<K> : Src<K> extends { other: infer O } ? O : never;
/** Parameters a key needs, from its English text: `'draw.tooSmall'` → { area, min }; plurals need `n`. */
export type Params<K extends MsgKey> = { [V in Vars<Text<K>>]: string | number } &
  (Src<K> extends string ? unknown : { n: number });
