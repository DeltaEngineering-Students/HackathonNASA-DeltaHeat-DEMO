// Basemap naming & border policy (MAP-TASKS item c). OpenFreeMap (OpenMapTiles schema) carries OSM's Russian-imposed
// entities on Ukrainian territory: a second state point «Республика Крым» (name:uk «Республіка Крим») next to
// «Автономна Республіка Крим», and admin_level 2 lines with `claimed_by` / `disputed` that cut Crimea off the mainland.
// The place layer has no claim tags, so labels are filtered by name (in every name field we may render);
// boundary lines are filtered by the schema's own `disputed` / `claimed_by` tags.
import type { ExpressionSpecification, FilterSpecification } from 'maplibre-gl';

/** Exact names of Russian-imposed entities on Ukrainian territory (ru / uk / en spellings). */
export const IMPOSED_NAMES = [
  'Республика Крым', 'Республіка Крим', 'Republic of Crimea',
  'Донецкая Народная Республика', 'Донецька Народна Республіка', "Donetsk People's Republic",
  'Луганская Народная Республика', 'Луганська Народна Республіка', "Luhansk People's Republic", "Lugansk People's Republic",
  'ДНР', 'ЛНР', 'DPR', 'LPR',
];
/** Substrings that only occur in those entities' names («… Народная/Народна Республика»). */
export const IMPOSED_PARTS = ['Народная Республика', 'Народна Республіка', "People's Republic"];
const NAME_FIELDS = ['name', 'name:uk', 'name:ru', 'name:en', 'name:latin', 'name:nonlatin'];

/** true for a feature whose name is a Russian-imposed entity. */
export const imposedName: ExpressionSpecification = [
  'any',
  ...NAME_FIELDS.map((f): ExpressionSpecification => ['match', ['coalesce', ['get', f], ''], IMPOSED_NAMES, true, false]),
  ...NAME_FIELDS.flatMap((f) => IMPOSED_PARTS.map((p): ExpressionSpecification => ['in', p, ['coalesce', ['get', f], '']])),
] as ExpressionSpecification;

/** A place-label filter with the imposed names removed (keeps «Автономна Республіка Крим», «Севастополь»). */
export const withoutImposed = (orig: FilterSpecification | undefined): FilterSpecification =>
  (orig ? ['all', orig, ['!', imposedName]] : ['!', imposedName]) as FilterSpecification;

/** Country lines only where undisputed and not a claim line (no line between Crimea and the mainland). */
export const undisputedBorder = (orig: FilterSpecification | undefined): FilterSpecification =>
  ['all', ...(orig ? [orig] : []), ['!=', ['coalesce', ['get', 'disputed'], 0], 1], ['!', ['has', 'claimed_by']]] as FilterSpecification;

/** Basemap layers that only draw disputed lines — hidden. */
export const DISPUTED_LAYERS = ['boundary_disputed'];
