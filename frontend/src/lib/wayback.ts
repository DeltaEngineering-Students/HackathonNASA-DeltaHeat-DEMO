// Esri World Imagery Wayback: which imagery is actually under a place, and when it was captured.
//
// A Wayback release is a GLOBAL version of World Imagery (dated by its publication), not a capture from that year: at a
// given place most releases repeat the same picture, and a later release can even carry an older capture. So for the
// map year we do not take «the release of that year» but:
//  1. the full release list (waybackconfig.json, ~200 releases, fetched once per session; the static ESRI_RELEASES table
//     in satellite.ts is the fallback),
//  2. the releases where the tile under the place actually CHANGED (Wayback `tilemap` answers, for any release, the
//     release that holds that tile: `select`) — a few parallel rounds instead of walking all releases,
//  3. the capture date at the place for each of those (the release's metadata MapServer `identify`: SRC_DATE),
//  4. per map year the version whose capture is in that year (closest to mid-summer), else the latest capture before
//     it, else the earliest after it (pickVersion). One version per capture date, so years with the same picture
//     share one layer and switching between them reloads nothing.
// Results are cached in memory and in localStorage (captures of a release never change), every request has a timeout,
// and any failure degrades to the static per-year release with its release-date caption.
import { ESRI_RELEASES, esriVersion } from './satellite';

export interface WaybackRelease {
  release: number;
  /** publication date of the release, YYYY-MM-DD */
  date: string;
  /** its metadata MapServer (identify → capture date) */
  meta: string;
}
export interface SatVersion {
  release: number;
  date: string;
  /** capture date at the probed place, YYYY-MM-DD; null = unknown (metadata failed / timed out) */
  captured: string | null;
  /** deepest zoom with imagery at the place (from the metadata), else by release date */
  maxzoom: number;
  /** shallowest tile zoom where the dated imagery is drawn (below it: the undated Earthstar overview mosaic); null = unknown */
  minzoom?: number | null;
}
export interface SatSite {
  /** z17 tile of the probed place, `z/y/x` */
  key: string;
  /** tile versions, newest release first */
  versions: SatVersion[];
  /** every capture lookup has finished (success or failure) */
  complete: boolean;
}

export const CONFIG_URL = 'https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json';
const META_ROOT = 'https://metadata.maptiles.arcgis.com/arcgis/rest/services/';
const TILEMAP = 'https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap';
export const PROBE_Z = 17;
export const CAPTURE_REF_ZOOM = 17;
const CONFIG_TIMEOUT_MS = 6000;
const TILEMAP_TIMEOUT_MS = 6000;
const IDENTIFY_TIMEOUT_MS = 9000;

/** metadata service names of the static releases (from waybackconfig.json, 15.11.2026) */
const STATIC_META: Readonly<Record<number, string>> = {
  25586: '2014_r14', 3630: '2015_r16', 6984: '2016_r16', 18358: '2017_r16', 14426: '2018_r13', 9892: '2019_r12',
  19187: '2020_r13', 51313: '2021_r13', 47471: '2022_r12', 64776: '2023_r08', 20337: '2024_r10', 58924: '2025_r09',
};
const metaUrl = (name: string) => `${META_ROOT}World_Imagery_Metadata_${name}/MapServer`;
/** the static table as a release list (newest first) — the fallback when the config cannot be fetched */
export const STATIC_RELEASES: readonly WaybackRelease[] = Object.values(ESRI_RELEASES)
  .map((r) => ({ release: r.release, date: r.date, meta: metaUrl(STATIC_META[r.release] ?? '') }))
  .sort((a, b) => b.date.localeCompare(a.date));

/** waybackconfig.json → releases, newest first (entries without a date or an Esri metadata URL are skipped) */
export function parseWaybackConfig(json: unknown): WaybackRelease[] {
  if (!json || typeof json !== 'object') return [];
  const out: WaybackRelease[] = [];
  for (const [k, v] of Object.entries(json as Record<string, { itemTitle?: unknown; metadataLayerUrl?: unknown }>)) {
    const release = Number(k);
    const date = typeof v?.itemTitle === 'string' ? /(\d{4}-\d{2}-\d{2})/.exec(v.itemTitle)?.[1] : undefined;
    const meta = typeof v?.metadataLayerUrl === 'string' ? v.metadataLayerUrl : '';
    if (!Number.isInteger(release) || release <= 0 || !date || !meta.startsWith(META_ROOT)) continue;
    out.push({ release, date, meta });
  }
  return out.sort((a, b) => b.date.localeCompare(a.date) || b.release - a.release);
}

type Fetch = (url: string, init?: { signal?: AbortSignal }) => Promise<{ ok: boolean; json(): Promise<unknown> }>;
async function getJson(f: Fetch, url: string, ms: number): Promise<unknown> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), ms);
  try {
    const r = await f(url, { signal: ac.signal });
    if (!r.ok) throw new Error(`HTTP ${url}`);
    return await r.json();
  } finally { clearTimeout(timer); }
}
const defaultFetch: Fetch = (u, i) => fetch(u, i);

let releasesP: Promise<{ releases: WaybackRelease[]; live: boolean }> | null = null;
/** the release list, once per session; the static table when the config fetch fails */
export function loadWaybackReleases(f: Fetch = defaultFetch): Promise<{ releases: WaybackRelease[]; live: boolean }> {
  releasesP ??= getJson(f, CONFIG_URL, CONFIG_TIMEOUT_MS)
    .then((j) => { const r = parseWaybackConfig(j); if (r.length < 12) throw new Error('short config'); return { releases: r, live: true }; })
    .catch(() => ({ releases: [...STATIC_RELEASES], live: false }));
  return releasesP;
}
export function resetWaybackForTests() { releasesP = null; sites.clear(); }

export function tileOf(lon: number, lat: number, z: number): { z: number; x: number; y: number } {
  const n = 2 ** z;
  const x = Math.min(n - 1, Math.max(0, Math.floor(((lon + 180) / 360) * n)));
  const s = Math.sin((lat * Math.PI) / 180);
  const y = Math.min(n - 1, Math.max(0, Math.floor((0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n)));
  return { z, x, y };
}
export function tileCentre(t: { z: number; x: number; y: number }): [number, number] {
  const n = 2 ** t.z;
  const lon = ((t.x + 0.5) / n) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * (t.y + 0.5)) / n))) * 180) / Math.PI;
  return [lon, lat];
}

/**
 * The releases where the tile changed (newest first). `select(r)` = the release holding the tile as of release r
 * (Wayback tilemap), null = no tile there, undefined = the request failed. Round 1 asks every `stride`-th release; each
 * change found at S makes the release right before S a question for the next round (an older change may hide there).
 * Converges in ~3 rounds / ~40 requests for ~200 releases (vs ~20 sequential requests for the plain walk).
 */
export async function walkVersions(
  releases: readonly WaybackRelease[], select: (r: number) => Promise<number | null | undefined>, stride = 8, maxRequests = 90,
): Promise<WaybackRelease[]> {
  const idx = new Map(releases.map((r, i) => [r.release, i]));
  const asked = new Map<number, number | null | undefined>();
  let q = releases.filter((_, i) => i % stride === 0).map((r) => r.release);
  for (let round = 0; q.length && round < 10 && asked.size < maxRequests; round++) {
    const batch = q.slice(0, maxRequests - asked.size);
    const got = await Promise.all(batch.map((r) => select(r).catch(() => undefined)));
    batch.forEach((r, i) => asked.set(r, got[i]));
    const next = new Set<number>();
    for (const s of asked.values()) {
      if (s == null) continue;
      const i = idx.get(s);
      const older = i == null ? undefined : releases[i + 1];
      if (older && !asked.has(older.release)) next.add(older.release);
    }
    q = [...next];
  }
  const found = new Set<number>();
  for (const s of asked.values()) if (s != null && idx.has(s)) found.add(s);
  return releases.filter((r) => found.has(r.release));
}

const DATE8 = /^(\d{4})(\d{2})(\d{2})$/;
const MDY = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/;
function isoDate(a: Record<string, unknown>): string | null {
  const s = String(a.SRC_DATE ?? '').trim();
  let m = DATE8.exec(s);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  const s2 = String(a.SRC_DATE2 ?? '').trim();
  m = MDY.exec(s2);
  if (m) return `${m[3]}-${m[1]!.padStart(2, '0')}-${m[2]!.padStart(2, '0')}`;
  return null;
}
/**
 * identify answer → the capture date shown at `refZoom` (the result whose MinMapLevel..MaxMapLevel holds it; else the
 * most detailed dated one) and the deepest dated level (the source maxzoom: old releases stop at z17).
 */
export function parseIdentify(json: unknown, refZoom = CAPTURE_REF_ZOOM): { captured: string | null; maxLevel: number | null; minLevel: number | null } {
  const results = (json as { results?: { attributes?: Record<string, unknown> }[] } | null)?.results;
  if (!Array.isArray(results)) return { captured: null, maxLevel: null, minLevel: null };
  const dated = results
    .map((r) => r.attributes ?? {})
    .map((a) => ({ date: isoDate(a), min: Number(a.MinMapLevel), max: Number(a.MaxMapLevel) }))
    .filter((r): r is { date: string; min: number; max: number } => r.date != null);
  if (!dated.length) return { captured: null, maxLevel: null, minLevel: null };
  const at = dated.find((r) => r.min <= refZoom && refZoom <= r.max) ?? [...dated].sort((a, b) => b.max - a.max)[0]!;
  const maxLevel = Math.max(...dated.map((r) => r.max).filter(Number.isFinite));
  const minLevel = Math.min(...dated.map((r) => r.min).filter(Number.isFinite));
  return { captured: at.date, maxLevel: Number.isFinite(maxLevel) ? maxLevel : null, minLevel: Number.isFinite(minLevel) ? minLevel : null };
}

/** maxzoom by release date when the metadata is unknown: releases before 2015 have no z18–19 over Ukraine */
export const releaseMaxzoom = (date: string) => (date < '2015-01-01' ? 17 : 19);
const clampZ = (z: number) => Math.min(19, Math.max(17, z));

/**
 * The version for a map year among versions with a known capture (one per capture date: the newest release carrying it):
 * a capture in that year (closest to 1 July), else the latest one before the year, else the earliest after it.
 * No year → the latest capture. null when no capture is known.
 */
export function pickVersion(year: number | null | undefined, versions: readonly SatVersion[]): SatVersion | null {
  const byCapture = new Map<string, SatVersion>();
  for (const v of [...versions].sort((a, b) => b.date.localeCompare(a.date) || b.release - a.release))
    if (v.captured && !byCapture.has(v.captured)) byCapture.set(v.captured, v);
  const vs = [...byCapture.values()].sort((a, b) => a.captured!.localeCompare(b.captured!)); // oldest capture first
  if (!vs.length) return null;
  if (year == null || !Number.isFinite(year)) return vs[vs.length - 1]!;
  const y = Math.round(year);
  const mid = Date.UTC(y, 6, 1);
  const ms = (d: string) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
  const same = vs.filter((v) => +v.captured!.slice(0, 4) === y);
  if (same.length) return same.reduce((a, b) => (Math.abs(ms(b.captured!) - mid) < Math.abs(ms(a.captured!) - mid) ? b : a));
  const before = vs.filter((v) => +v.captured!.slice(0, 4) < y);
  return before.length ? before[before.length - 1]! : vs[0]!;
}

/** the tile version that a release shows (the newest version not newer than it) — same picture, no Wayback redirect */
export function versionOf(release: { date: string; release: number }, versions: readonly SatVersion[]): SatVersion | null {
  return versions.find((v) => v.release === release.release) ?? versions.find((v) => v.date <= release.date) ?? null;
}

export interface EsriChoice {
  release: number;
  date: string;
  captured: string | null;
  maxzoom: number;
  /** the dated imagery starts at this tile zoom (null = unknown) */
  minzoom: number | null;
  /** the picture is not from the selected year (capture year, or the static release year when unknown) */
  nearest: boolean;
}
/**
 * What to show for a map year at a probed place: the picked version once every capture lookup has finished, so the
 * layer switches at most once while the metadata comes in. Before that: the static release of the year (no reload),
 * captioned with the capture of its tile version as soon as that is known. Complete but no capture known (metadata
 * down): the static release mapped onto its tile version, so years with the same picture still share one layer.
 */
export function esriChoice(year: number | null | undefined, site: SatSite | null): EsriChoice {
  const yr = year != null && Number.isFinite(year) ? Math.round(year) : null;
  const pick = site?.complete ? pickVersion(year, site.versions) : null;
  if (pick) {
    const nearest = yr != null && +pick.captured!.slice(0, 4) !== yr;
    return { release: pick.release, date: pick.date, captured: pick.captured, maxzoom: pick.maxzoom, minzoom: pick.minzoom ?? null, nearest };
  }
  const s = esriVersion(year);
  const v = site ? versionOf(s, site.versions) : null;
  const nearest = v?.captured ? yr != null && +v.captured.slice(0, 4) !== yr : yr != null && yr !== s.year;
  if (v && site?.complete) return { release: v.release, date: v.date, captured: v.captured, maxzoom: v.maxzoom, minzoom: v.minzoom ?? null, nearest };
  return { release: s.release, date: s.date, captured: v?.captured ?? null, maxzoom: releaseMaxzoom(s.date), minzoom: v?.minzoom ?? null, nearest };
}

// ── probing a place (cached) ──
const LS_CAP = 'uhd-wb-cap:'; // + release:z/y/x → {c: captured, z: maxLevel|null, m: minLevel|null}
const LS_VER = 'uhd-wb-ver:'; // + z/y/x → {n: newest release, v: [release…]}
function lsGet<T>(k: string): T | null {
  try { const s = localStorage.getItem(k); return s ? (JSON.parse(s) as T) : null; } catch { return null; }
}
function lsSet(k: string, v: unknown) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* full / private mode */ }
}

async function identify(f: Fetch, r: WaybackRelease, lon: number, lat: number) {
  const d = 0.002;
  const q = new URLSearchParams({
    geometry: `${lon},${lat}`, geometryType: 'esriGeometryPoint', sr: '4326', layers: 'all', tolerance: '0',
    mapExtent: `${lon - d},${lat - d},${lon + d},${lat + d}`, imageDisplay: '256,256,96', returnGeometry: 'false', f: 'json',
  });
  return parseIdentify(await getJson(f, `${r.meta}/identify?${q}`, IDENTIFY_TIMEOUT_MS));
}

const sites = new Map<string, { site: SatSite; listeners: Set<(s: SatSite) => void>; done: Promise<SatSite> }>();
/**
 * Probe the imagery versions and their capture dates at a place (the z17 tile under lon/lat). `onUpdate` gets the site
 * as it fills in (versions first, then captures, last with complete = true). Shared and cached per tile for the session.
 */
export function probeSatSite(lon: number, lat: number, onUpdate?: (s: SatSite) => void, f: Fetch = defaultFetch): Promise<SatSite> {
  const t = tileOf(lon, lat, PROBE_Z);
  const key = `${t.z}/${t.y}/${t.x}`;
  let entry = sites.get(key);
  if (entry) {
    if (onUpdate) { entry.listeners.add(onUpdate); onUpdate(entry.site); }
    return entry.done;
  }
  const listeners = new Set<(s: SatSite) => void>(onUpdate ? [onUpdate] : []);
  const e = { site: { key, versions: [], complete: false } as SatSite, listeners, done: Promise.resolve(null as unknown as SatSite) };
  const emit = (s: SatSite) => { e.site = s; for (const l of e.listeners) l(s); };
  e.done = (async () => {
    const [plon, plat] = tileCentre(t);
    const { releases, live } = await loadWaybackReleases(f);
    let vers: WaybackRelease[] = [];
    if (live) {
      const cached = lsGet<{ n: number; v: number[] }>(LS_VER + key);
      const byNum = new Map(releases.map((r) => [r.release, r]));
      if (cached && cached.n === releases[0]!.release) vers = cached.v.map((n) => byNum.get(n)).filter((r): r is WaybackRelease => !!r);
      if (!vers.length) {
        vers = await walkVersions(releases, async (r) => {
          const j = (await getJson(f, `${TILEMAP}/${r}/${t.z}/${t.y}/${t.x}`, TILEMAP_TIMEOUT_MS)) as { data?: number[]; select?: number[] };
          if (!Array.isArray(j?.data) || !j.data[0]) return null;
          return Array.isArray(j.select) && Number.isInteger(j.select[0]) ? j.select[0] : r;
        });
        if (vers.length) lsSet(LS_VER + key, { n: releases[0]!.release, v: vers.map((r) => r.release) });
      }
    }
    if (!vers.length) vers = [...STATIC_RELEASES]; // no config / the walk failed: the 12 static releases
    const out: SatVersion[] = vers.map((r) => {
      const c = lsGet<{ c: string | null; z: number | null; m?: number | null }>(`${LS_CAP}${r.release}:${key}`);
      return { release: r.release, date: r.date, captured: c?.c ?? null, maxzoom: c?.c && c.z != null ? clampZ(c.z) : releaseMaxzoom(r.date), minzoom: c?.m ?? null };
    });
    emit({ key, versions: out, complete: false });
    await Promise.all(vers.map(async (r, i) => {
      if (out[i]!.captured) return;
      try {
        const got = await identify(f, r, plon, plat);
        if (!got.captured) return;
        const maxzoom = got.maxLevel != null ? clampZ(got.maxLevel) : out[i]!.maxzoom;
        out[i] = { ...out[i]!, captured: got.captured, maxzoom, minzoom: got.minLevel };
        lsSet(`${LS_CAP}${r.release}:${key}`, { c: got.captured, z: got.maxLevel, m: got.minLevel });
        emit({ key, versions: [...out], complete: false });
      } catch { /* slow / failing metadata service: this version stays without a date */ }
    }));
    const final = { key, versions: [...out], complete: true };
    emit(final);
    return final;
  })();
  sites.set(key, e);
  entry = e;
  return e.done;
}
/** stop listening to a probe (the probe itself finishes and stays cached) */
export function unprobe(lon: number, lat: number, onUpdate: (s: SatSite) => void) {
  const t = tileOf(lon, lat, PROBE_Z);
  sites.get(`${t.z}/${t.y}/${t.x}`)?.listeners.delete(onUpdate);
}
