// Source credit of the occupied-territory overlay (Мінрозвитку order No. 376 + OSM hromada boundaries).
// The API puts it in the collection's `properties` (`attribution`, `attribution_en` with ?lang=en); older payloads had it
// at the top level, or only `source`. English falls back to the Ukrainian credit, never to nothing.
import type { Locale } from '../i18n/locale';

const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v : undefined);

/** `occ`: the `occupied` FeatureCollection from /api/overlays (any shape; only these fields are read) */
export function occupiedAttribution(occ: object | null | undefined, l: Locale): string | undefined {
  const top = (occ ?? {}) as Record<string, unknown>;
  if (!Array.isArray(top.features) || !top.features.length) return undefined;
  const p = (top.properties && typeof top.properties === 'object' ? top.properties : {}) as Record<string, unknown>;
  return (l === 'en' ? str(p.attribution_en) ?? str(top.attribution_en) : undefined)
    ?? str(p.attribution) ?? str(top.attribution) ?? str(p.source) ?? str(top.source);
}
