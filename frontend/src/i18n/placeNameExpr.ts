// English basemap labels (bug: «ODESKA STREET», «ВУЛИЦЯ ЩАСТЯ» and «ULICA ŁĄKOWA» side by side in one Ukrainian city).
// OpenFreeMap tiles carry `name:en` only for some streets; their `name:latin` / `name_int` fall back to `name:pl` when
// there is no English name, and plain `name` is Cyrillic. MapLibre expressions cannot call JS, so the KMU 2010
// transliteration of `romanize()` (placeName.ts) is spelled out as a style expression: one `match` per character.
// Street-type words are translated the way OSM `name:en` does it in Ukraine («Новосільська вулиця» → «Novosilska Street»),
// so a label without `name:en` reads like its neighbours that have one.
import type { ExpressionSpecification } from 'maplibre-gl';

type Expr = ExpressionSpecification;

const KMU: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', ґ: 'g', д: 'd', е: 'e', ж: 'zh', з: 'z', и: 'y', і: 'i',
  к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'kh', ц: 'ts', ч: 'ch',
  ш: 'sh', щ: 'shch',
  // Russian-only letters (names in the occupied territories without a `name:uk`), so no Cyrillic leaks through
  ы: 'y', э: 'e', ё: 'io',
};
/** word-initial / elsewhere (KMU 2010) */
const KMU_POS: Record<string, [string, string]> = { є: ['ye', 'ie'], ї: ['yi', 'i'], й: ['y', 'i'], ю: ['yu', 'iu'], я: ['ya', 'ia'] };
const SILENT = ['ь', 'Ь', 'ъ', 'Ъ', "'", '’', 'ʼ'];
const cap = (t: string) => t[0]!.toUpperCase() + t.slice(1);

/** longest name transliterated in full; longer ones end in «…» (OSM street / place names are well below this) */
export const ROMANIZE_MAX = 64;

function charExpr(s: Expr, i: number): Expr {
  const c: Expr = ['slice', s, i, i + 1];
  const p: Expr = ['slice', s, i - 1, i];
  // a word starts after anything that is not a cased letter or an apostrophe (as `romanize`: «м'ясо» → «miaso»)
  const initial: Expr = i === 0 ? ['literal', true] as unknown as Expr : ['!', ['any', ['!=', ['upcase', p], ['downcase', p]], ['in', p, "'’ʼ"]]];
  const afterZ: Expr = i === 0 ? ['literal', false] as unknown as Expr : ['==', ['downcase', p], 'з'];
  const arms: unknown[] = [];
  for (const [k, v] of Object.entries(KMU)) arms.push(k, v, k.toUpperCase(), cap(v));
  for (const [k, [first, other]] of Object.entries(KMU_POS)) {
    arms.push(k, ['case', ['var', 'w'], first, other], k.toUpperCase(), ['case', ['var', 'w'], cap(first), cap(other)]);
  }
  arms.push('г', ['case', ['var', 'z'], 'gh', 'h'], 'Г', ['case', ['var', 'z'], 'Gh', 'H']);
  arms.push(SILENT, '');
  return ['let', 'c', c, 'w', initial, 'z', afterZ, ['match', ['var', 'c'], ...arms, ['var', 'c']]] as unknown as Expr;
}

/** KMU 2010 transliteration of a string expression; Latin text and punctuation pass through unchanged */
export function romanizeExpr(input: Expr, max = ROMANIZE_MAX): Expr {
  const s: Expr = ['var', 's'];
  const parts: Expr[] = [];
  for (let i = 0; i < max; i++) parts.push(charExpr(s, i));
  return ['let', 's', ['to-string', input], ['concat', ...parts, ['case', ['>', ['length', s], max], '…', '']]] as unknown as Expr;
}

/** street-type words → the English word OSM `name:en` uses in Ukraine; matched as the first or last word */
const STREET_WORDS: [string, string][] = [
  ['вулиця', 'Street'], ['провулок', 'Lane'], ['проспект', 'Avenue'], ['бульвар', 'Boulevard'], ['площа', 'Square'],
  ['майдан', 'Square'], ['узвіз', 'Descent'], ['набережна', 'Embankment'], ['шосе', 'Highway'], ['проїзд', 'Passage'],
  ['алея', 'Alley'], ['тупик', 'Dead End'],
];

/**
 * English basemap label: OSM `name:en` when the tile has it, else the Ukrainian name (`name:uk`, else `name`) in KMU 2010
 * Latin with the street-type word translated. Never `name:latin` / `name_int` (Polish where `name:pl` exists).
 */
export function basemapNameEn(): Expr {
  const n: Expr = ['var', 'n'], lc: Expr = ['var', 'lc'];
  const len: Expr = ['length', n];
  const stemArms: unknown[] = [], sfxArms: unknown[] = [];
  for (const [uk, en] of STREET_WORDS) {
    const k = uk.length + 1;
    const starts: Expr = ['==', ['slice', lc, 0, k], `${uk} `];
    const ends: Expr = ['all', ['>', len, k], ['==', ['slice', lc, ['-', len, k]], ` ${uk}`]];
    stemArms.push(starts, ['slice', n, k], ends, ['slice', n, 0, ['-', len, k]]);
    sfxArms.push(starts, ` ${en}`, ends, ` ${en}`);
  }
  return ['coalesce', ['get', 'name:en'],
    ['let', 'n', ['to-string', ['coalesce', ['get', 'name:uk'], ['get', 'name'], '']],
      ['let', 'lc', ['downcase', n],
        ['let', 'stem', ['case', ...stemArms, n], 'sfx', ['case', ...sfxArms, ''],
          ['concat', romanizeExpr(['var', 'stem']), ['var', 'sfx']]]]]] as unknown as Expr;
}
