// English place names when the API sent no `name_en` (fixtures, geocoder hits, older reports): the same rules as the
// backend's uhd/services/i18n.py place_name_en — KMU 2010 transliteration (TERMS-EN §8: Kyiv, Kharkiv, Odesa,
// Zaporizhzhia) with a few generic words translated. Prefer the API's `name_en` whenever it is present.

const KMU: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'h', ґ: 'g', д: 'd', е: 'e', є: 'ie', ж: 'zh', з: 'z', и: 'y', і: 'i', ї: 'i', й: 'i',
  к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch',
  ш: 'sh', щ: 'shch', ь: '', ю: 'iu', я: 'ia', "'": '', '’': '', 'ʼ': '',
};
const KMU_FIRST: Record<string, string> = { є: 'ye', ї: 'yi', й: 'y', ю: 'yu', я: 'ya' };
const APOS = new Set(["'", '’', 'ʼ']);

/** KMU 2010: word-initial є/ї/й/ю/я → Ye/Yi/Y/Yu/Ya, «зг» → «zgh», apostrophe and ь dropped. */
export function romanize(s: string): string {
  let out = '';
  let prevLetter = false;
  const low = s.toLowerCase();
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!, lc = low[i]!;
    let t: string;
    if (lc === 'г' && i > 0 && low[i - 1] === 'з') t = 'gh';
    else if (lc in KMU) t = !prevLetter && lc in KMU_FIRST ? KMU_FIRST[lc]! : KMU[lc]!;
    else { out += ch; prevLetter = /\p{L}/u.test(ch); continue; }
    if (ch !== lc && t) t = t[0]!.toUpperCase() + t.slice(1);
    out += t;
    prevLetter = !APOS.has(lc) || prevLetter;
  }
  return out;
}

const WORDS: Record<string, string> = {
  район: 'District', мікрорайон: 'microdistrict', мікрорайони: 'microdistricts', ліс: 'Forest', увесь: 'All of',
  котеджне: 'Cottage', містечко: 'town', область: 'Oblast', км: 'km', і: 'and', старий: 'Old',
};
const ordinal = (n: number) => `${n}${n % 100 >= 10 && n % 100 <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;

/** «Деснянський район (Київ)» → «Desnianskyi District (Kyiv)», «Позняки (≈1 км)» → «Pozniaky (≈1 km)». Latin stays. */
export function placeNameEn(name: string): string {
  if (!/[А-Яа-яІіЇїЄєҐґ]/.test(name)) return name;
  return name.replace(/[\p{L}\p{N}’'ʼ-]+/gu, (w) => {
    const o = /^(\d+)-й$/.exec(w);
    if (o) return ordinal(Number(o[1]));
    const tr = WORDS[w.toLowerCase()];
    if (tr !== undefined) return /^\p{Lu}/u.test(w) ? tr[0]!.toUpperCase() + tr.slice(1) : tr;
    return romanize(w);
  });
}

/** The name to show in English: the API's `name_en` when sent, else the transliteration. */
export const nameEn = (uk: string, en?: string | null) => (en && en.trim() ? en : placeNameEn(uk));
