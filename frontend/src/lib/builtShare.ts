// Board item 14 (INVESTIGATION-BUILT-SHARE): Esri «built» is urban fabric (yards, parks, dachas), and the old
// built_share was a share of LAND, not of the zone. sci-v3.5.1 adds the share of the whole zone, keeps the land share,
// and adds GHSL sealed surface (roofs + paving). Older reports (sci-v3.5) have only built_share → fall back to it.
import type { Report, SeriesPoint } from '../api/types';
import { fmtPct } from './format';
import { isCounted } from './verdict';
import { getLocale } from '../i18n/locale';
import { tr } from '../i18n';

const isEn = () => getLocale() === 'en';

type BuiltPoint = SeriesPoint & { built_share_zone?: number | null; built_share_land?: number | null };
type Sealed = Record<string, number | null> | null | undefined;

export const BUILT_LABEL = 'Забудова (міська тканина, Esri)';
export const SEALED_LABEL = 'Запечатані поверхні (дахи, асфальт; GHSL)';
export const builtLabel = () => (isEn() ? tr('en', 'built.label') : BUILT_LABEL);
export const sealedLabel = () => (isEn() ? tr('en', 'built.sealedLabel') : SEALED_LABEL);

/** Share of the zone (new field) or, on older reports, the old built_share. */
export const zoneShare = (s: SeriesPoint): number | null => {
  const b = s as BuiltPoint;
  return b.built_share_zone !== undefined ? b.built_share_zone : s.built_share;
};
/** Share of the land, only when the report has the new fields (otherwise it equals the shown value). */
const landShare = (s: SeriesPoint): number | null => (s as BuiltPoint).built_share_land ?? null;
const hasZoneShare = (s: SeriesPoint) => (s as BuiltPoint).built_share_zone !== undefined;

/** The latest GHSL year with a value: {year, share} or null. */
export function latestSealed(r: Report): { year: string; share: number } | null {
  const g = (r.zone as { sealed_share_ghsl?: Sealed }).sealed_share_ghsl;
  if (!g) return null;
  const y = Object.keys(g).filter((k) => g[k] != null).sort().pop();
  return y ? { year: y, share: g[y]! } : null;
}

/** Card «Що гріє» chip: «Забудова (міська тканина, Esri) — 73 % ділянки (2025)». */
export function builtFactorText(r: Report): string | null {
  const last = [...r.series].filter(isCounted).reverse().find((x) => zoneShare(x) != null);
  if (!last) return null;
  if (isEn()) return tr('en', 'built.factor', { label: builtLabel(), share: fmtPct(zoneShare(last)), year: last.year });
  return `${BUILT_LABEL} — ${fmtPct(zoneShare(last))} ділянки (${last.year})`;
}

/** Details «Цифри для перевірки» rows for built / sealed surface. */
export function builtRows(r: Report): [string, string][] {
  const built = r.series.filter((s) => zoneShare(s) != null);
  const rows: [string, string][] = [];
  const b0 = built[0], b1 = built[built.length - 1];
  if (b0 && b1) {
    const land = hasZoneShare(b1) ? landShare(b1) : null;
    if (isEn()) rows.push([builtLabel(), tr('en', 'built.row', { from: fmtPct(zoneShare(b0), 1), to: fmtPct(zoneShare(b1), 1) }) + (land != null ? tr('en', 'built.rowLand', { land: fmtPct(land, 1) }) : '')]);
    else rows.push([BUILT_LABEL, `${fmtPct(zoneShare(b0), 1)} → ${fmtPct(zoneShare(b1), 1)} ділянки${land != null ? ` — з них суходолу: ${fmtPct(land, 1)}` : ''}`]);
  }
  const g = latestSealed(r);
  if (g) rows.push(isEn() ? [sealedLabel(), tr('en', 'built.sealedRow', { share: fmtPct(g.share), year: g.year })] : [SEALED_LABEL, `${fmtPct(g.share)} ділянки (${g.year})`]);
  return rows;
}
