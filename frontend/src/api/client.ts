import type { ReferenceOutline,
  AgentStep, AnalyzeRequest, ApiError, ChatMessage, Climate, Health, Meta, Overlays, Overview, Place, PlaceHit, Report,
} from './types';
import * as fx from '../fixtures';
import { setMapUi } from '../lib/mapUi';
import { adaptClimate, adaptMeta, adaptPlaces, adaptReport, addressName } from './adapt';
import { areaKm2, centroid } from '../lib/geo';
import { takePrefetch, viaPrefetch } from './prefetch';
import { getLocale, type Locale } from '../i18n/locale';

/**
 * API client. Modes (VITE_API_MODE):
 *  - `live`     — default (and the only mode for production builds): always call the backend;
 *                 failures surface as error states with retry, never as made-up numbers (QA-04);
 *  - `fixtures` — never call it (typed fixtures, used by e2e and offline dev, `npm run dev:fixtures`);
 *  - `auto`     — explicit dev/demo only: probe /api/health once, fall back to flagged fixtures.
 * Base URL: VITE_API_BASE ('' = same origin; dev server proxies /api and /tiles).
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const MODE = ((import.meta.env.VITE_API_MODE as string | undefined) || 'live') as 'live' | 'fixtures' | 'auto';

export class HttpError extends Error {
  constructor(public status: number, public body: ApiError | null) {
    super(body?.error ?? `HTTP ${status}`);
  }
}

let fixturesDecided: Promise<boolean> | null = null;
export function usingFixtures(): Promise<boolean> {
  if (MODE === 'fixtures') return Promise.resolve(true);
  if (MODE === 'live') return Promise.resolve(false);
  fixturesDecided ??= fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(4000) })
    .then(async (r) => !(r.ok && ((await r.json()) as Health).ok))
    .catch(() => true);
  return fixturesDecided;
}

const delay = <T>(v: T, ms = 350): Promise<T> =>
  new Promise((res) => setTimeout(() => res(structuredClone(v)), ms));

/**
 * fetch with one retry when a GET fails with a network error (no HTTP response at all) — a backend worker
 * recycling drops the odd in-flight request (RB-14). Aborts and HTTP errors are never retried.
 */
export async function fetchRetry(url: string, init?: RequestInit, waitMs = 250): Promise<Response> {
  const get = !init?.method || init.method.toUpperCase() === 'GET';
  try {
    return await fetch(url, init);
  } catch (e) {
    if (!get || init?.signal?.aborted || (e instanceof DOMException && e.name === 'AbortError')) throw e;
    await new Promise((res) => setTimeout(res, waitMs));
    if (init?.signal?.aborted) throw e;
    return fetch(url, init);
  }
}

/** MapLibre protocol for heat tiles: same URL, fetched through fetchRetry (RB-14). */
export const TILE_PROTOCOL = 'uhdt';
export async function loadTile(params: { url: string }, ac: AbortController): Promise<{ data: ArrayBuffer }> {
  const url = params.url.slice(TILE_PROTOCOL.length + 3);
  const r = await fetchRetry(url, { signal: ac.signal });
  if (!r.ok) throw new Error(`tile ${r.status}`);
  return { data: await r.arrayBuffer() };
}
// string concat, not new URL(): URL() percent-encodes «{z}/{x}/{y}» and MapLibre then never fills them in
export const retryingTileUrl = (url: string, origin = window.location.origin) =>
  `${TILE_PROTOCOL}://${/^https?:\/\//.test(url) ? url : origin + (url.startsWith('/') ? '' : '/') + url}`;

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetchRetry(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  });
  if (!r.ok) {
    let body: ApiError | null = null;
    try { body = (await r.json()) as ApiError; } catch { /* non-JSON error */ }
    throw new HttpError(r.status, body);
  }
  return (await r.json()) as T;
}

/**
 * Item 32 (I18N.md §6.1): cached data fetches ask for `lang=en`. Search uses the current locale. The API ADDS `*_en` next to each `*_uk` and
 * `name_en` next to Cyrillic names — the Ukrainian fields are unchanged — so one response serves both languages and a
 * language switch needs no refetch. Old report ids keep working (the parameter only adds fields).
 */
const EN = 'lang=en';

export async function getMeta(): Promise<Meta> {
  if (await usingFixtures()) return delay(fx.META, 0);
  const m = adaptMeta(await viaPrefetch(takePrefetch('meta'), () => http<Record<string, unknown>>(`/api/meta?${EN}`)));
  tileTemplate = m.tiles?.url ?? null;
  setMapUi({ nonbuilt: m.nonbuilt ?? null }); // item 13: the «Шари» store offers the slider only when the backend has it
  // tiles are cached immutably per tiles_version (falls back to data_version on older backends)
  dataVersion = m.tiles?.version ?? m.data_version ?? null;
  if (m.tiles?.maxzoom) tileOptions.maxzoom = m.tiles.maxzoom;
  if (m.tiles?.tileSize) tileOptions.tileSize = m.tiles.tileSize;
  return m;
}

// The server sends these with `Cache-Control: public, max-age=86400`, so a browser would keep a pre-deploy overview (old
// method_version, old marker numbers) for up to a day and the marker would disagree with the freshly fetched card.
// `no-cache` = always revalidate with the ETag (it carries data+method version): a 304 when nothing changed, a new body after a method change.
export const REVALIDATE: RequestInit = { cache: 'no-cache' };

// Country map layers (MAP-TASKS 2–4): fetched once per page; null on fixtures or when the backend lacks them —
// the map then simply draws no veil/markers/hatch.
// item 32: always ?lang=en — the API then ADDS *_en next to every *_uk (I18N.md §6.1), so one fetch serves both
// languages and a language switch needs no refetch; the Ukrainian UI keeps reading the *_uk fields as before.
let overlaysP: Promise<Overlays | null> | null = null;
export function getOverlays(): Promise<Overlays | null> {
  overlaysP ??= usingFixtures().then((fixtures) => (fixtures ? null : http<Overlays>('/api/overlays?lang=en', REVALIDATE))).catch(() => { overlaysP = null; return null; });
  return overlaysP;
}
let overviewP: Promise<Overview | null> | null = null;
export function getOverview(): Promise<Overview | null> {
  overviewP ??= usingFixtures().then((fixtures) => (fixtures ? null : http<Overview>('/api/overview?lang=en', REVALIDATE))).catch(() => { overviewP = null; return null; });
  return overviewP;
}

export async function searchPlaces(q: string, signal?: AbortSignal, lang: Locale = getLocale()): Promise<PlaceHit[]> {
  if (await usingFixtures()) return delay(fx.searchPresets(q), 120);
  return adaptPlaces(await http<unknown>(`/api/places?q=${encodeURIComponent(q)}&limit=12&lang=${lang}`, { signal }));
}

export async function getPlace(id: string): Promise<Place> {
  if (await usingFixtures()) {
    const p = fx.PLACES[id];
    if (!p) throw new HttpError(404, { error: 'not_found' });
    return delay({ id: p.id, name: p.name, kind: p.kind, geometry: p.geometry }, 80);
  }
  const p = await viaPrefetch(takePrefetch('place', id), () => http<Place>(`/api/places/${encodeURIComponent(id)}?${EN}`));
  return { ...p, name: addressName(p.name, p.display_name),
    ...(p.name_en ? { name_en: addressName(p.name_en, p.display_name_en) } : {}) };
}

/** Analyze without changing the active map. `presetId` selects the matching fixture. */
export async function analyze(req: AnalyzeRequest, presetId?: string, signal?: AbortSignal): Promise<Report> {
  if (await usingFixtures()) {
    if (presetId && fx.REPORTS[presetId]) return delay(fx.REPORTS[presetId]!, 450);
    const [lon, lat] = centroid(req.geometry);
    const nearest = Object.values(fx.PLACES)
      .filter((p) => p.kind !== 'city')
      .map((p) => ({ id: p.id, d: (p.center[0] - lon) ** 2 + (p.center[1] - lat) ** 2 }))
      .sort((a, b) => a.d - b.d)[0];
    const id = nearest && nearest.d < 0.05 ? nearest.id : lon > 33 ? 'kharkiv' : lon < 26 ? 'lviv' : 'kyiv';
    return delay(fx.fixtureReportForCustom(id, areaKm2(req.geometry)), 600);
  }
  return analyzeLive(req, presetId, signal);
}
async function analyzeLive(req: AnalyzeRequest, presetId?: string, signal?: AbortSignal): Promise<Report> {
  // the prefetched report was computed for the preset's own geometry — only reuse it for that request
  const pre = presetId ? takePrefetch('analyze', presetId) : undefined;
  return adaptReport(await viaPrefetch(pre, () => http<Record<string, unknown>>(`/api/analyze?${EN}`, { method: 'POST', body: JSON.stringify(req.place_id ? { place_id: req.place_id, ...(req.years ? { years: req.years } : {}) } : { geometry: req.geometry, ...(req.years ? { years: req.years } : {}) }), signal })));
}

export async function getReport(id: string): Promise<Report> {
  if (await usingFixtures()) {
    const r = Object.values(fx.REPORTS).find((x) => x.report_id === id);
    if (!r) throw new HttpError(404, { error: 'not_found' });
    return delay(r);
  }
  return adaptReport(await http<Record<string, unknown>>(`/api/reports/${encodeURIComponent(id)}?${EN}`));
}

const refCache = new Map<string, Promise<ReferenceOutline | null>>();
/** Reference-forest outline of a stored report; null on fixtures, an unknown id, or a backend without the endpoint. */
export function getReference(id: string): Promise<ReferenceOutline | null> {
  let p = refCache.get(id);
  if (!p) {
    p = usingFixtures().then((fx) => (fx ? null : http<ReferenceOutline>(`/api/reports/${encodeURIComponent(id)}/reference`)))
      .then((f) => (f && f.type === 'Feature' && f.geometry ? f : null))
      .catch(() => { refCache.delete(id); return null; });
    refCache.set(id, p);
  }
  return p;
}

export async function getClimate(lat: number, lon: number): Promise<Climate> {
  if (await usingFixtures()) return delay(fx.CLIMATE, 200);
  return adaptClimate(await http<Record<string, unknown>>(`/api/climate?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}&${EN}`));
}

let tileTemplate: string | null = null;
let dataVersion: string | null = null;
/** Raster tile source options (updated from /api/meta: native zoom → MapLibre overzooms above it). */
export const tileOptions = { maxzoom: 14, tileSize: 256 };
export function tileUrl(layer: string, year: number, theme: 'light' | 'dark'): string {
  const t = tileTemplate ?? '/tiles/{layer}/{year}/{z}/{x}/{y}.png?theme={theme}';
  const url = API_BASE + t.replace('{layer}', layer).replace('{year}', String(year)).replace('{theme}', theme);
  // cache-bust tiles when the data changes
  return dataVersion ? `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(dataVersion)}` : url;
}

// ---- agent chat (decision #19) -------------------------------------------------------
export type MapView = { layer?: string | null; year?: number | null; place_ids?: string[]; report_ids?: string[]; bbox?: number[] | null };
export type ChatEvent =
  | { type: 'step'; step: AgentStep }
  | { type: 'delta'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'map_view'; view: MapView }
  | { type: 'error'; code: string; message: string }
  | { type: 'reset' }
  | { type: 'validation'; ok: boolean; repairing: boolean; caveats: number; unsourced: string[] }
  | { type: 'done'; validationOk?: boolean; unsourced?: string[]; costUsd?: number };

export interface ChatContext { report_id?: string | null; place_id?: string | null; layer?: string; year?: number | null; lang?: 'en' | 'uk' }

/** The analyst is unavailable before any answer: `code` is the backend error (503 agent_not_configured /
 * agent_budget_exhausted / agent_busy / agent_team_only, 429 rate_limited…) or `network`. */
export class AgentUnavailable extends Error {
  constructor(public code: string) { super(code); }
}
/** 503 agent_not_configured (or no backend in fixtures mode) → the friendly offline card. */
export class AgentNotConfigured extends AgentUnavailable {
  constructor() { super('agent_not_configured'); }
}

// Team mode («Командний режим»): the token is typed by a team member, kept in sessionStorage only (never in the bundle).
const TEAM_KEY = 'uhd.teamToken';
export function getTeamToken(): string | null {
  try { return sessionStorage.getItem(TEAM_KEY); } catch { return null; }
}
export function setTeamToken(token: string | null): void {
  try { if (token) sessionStorage.setItem(TEAM_KEY, token); else sessionStorage.removeItem(TEAM_KEY); } catch { /* private mode */ }
}
const teamHeaders = (token = getTeamToken()): Record<string, string> => (token ? { 'X-UHD-Team-Token': token } : {});

/** GET /api/agent/tools with the token → true when the backend accepts it as the team token. */
export async function verifyTeamToken(token: string): Promise<boolean> {
  const r = await fetch(`${API_BASE}/api/agent/tools`, { headers: teamHeaders(token) });
  if (!r.ok) return false;
  return ((await r.json()) as { team?: boolean }).team === true;
}

// e2e hook (fixtures mode only): sessionStorage 'uhd.e2e.chat' = '1' lets a mocked /api/agent/chat answer.
function chatFetchInFixtures(): boolean {
  try { return sessionStorage.getItem('uhd.e2e.chat') === '1'; } catch { return false; }
}

/**
 * POST /api/agent/chat. Streams Server-Sent Events when the backend replies with `text/event-stream`
 * (uhd/backend/uhd/agent/loop.py), or accepts a plain JSON `{reply, steps}`. Errors before the stream:
 * 503/429 with `{error}` → AgentUnavailable(code) (AgentNotConfigured for agent_not_configured).
 */
export async function chat(
  messages: ChatMessage[], context: ChatContext, onEvent: (e: ChatEvent) => void, signal?: AbortSignal,
): Promise<void> {
  if (await usingFixtures() && !chatFetchInFixtures()) {
    await delay(null, 400);
    throw new AgentNotConfigured();
  }
  let r: Response;
  try {
    r = await fetch(`${API_BASE}/api/agent/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream, application/json', ...teamHeaders() },
      body: JSON.stringify({ messages, context }),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new AgentUnavailable('network');
  }
  if (!r.ok) {
    let code = '';
    try { code = ((await r.json()) as ApiError).error ?? ''; } catch { /* not JSON */ }
    if (code === 'agent_not_configured' || (r.status === 503 && !code)) throw new AgentNotConfigured();
    throw new AgentUnavailable(code || (r.status === 429 ? 'rate_limited' : r.status >= 500 ? 'upstream_error' : 'invalid_request'));
  }
  const ct = r.headers.get('content-type') ?? '';
  if (!ct.includes('text/event-stream') || !r.body) {
    const j = (await r.json()) as { reply?: string; steps?: AgentStep[] };
    for (const s of j.steps ?? []) onEvent({ type: 'step', step: s });
    if (j.reply) onEvent({ type: 'delta', text: j.reply });
    onEvent({ type: 'done' });
    return;
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  let finished = false;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value.replace(/\r\n/g, '\n');
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const ev = parseSse(buf.slice(0, i));
      buf = buf.slice(i + 2);
      if (ev) { if (ev.type === 'done' || ev.type === 'error') finished = true; onEvent(ev); }
    }
  }
  if (!finished) onEvent({ type: 'done' });
}

/**
 * One SSE block → event. Backend events (uhd/backend/uhd/agent/loop.py): text{delta}, thinking{delta},
 * tool_call{id,name}, tool_result{id,name,is_error}, web{name}, map_view{layer,year,place_ids,report_ids,bbox},
 * validation{ok,repairing,unsourced,caveats}, text_reset, done{validation,cost_usd}, error{error,message}.
 */
export function parseSse(block: string): ChatEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  const raw = data.join('\n');
  let j: Record<string, unknown> = {};
  try { j = JSON.parse(raw) as Record<string, unknown>; } catch {
    return event === 'delta' || event === 'text' || event === 'message' ? { type: 'delta', text: raw } : null;
  }
  const texts = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === 'string' ? x : String((x as { text?: unknown })?.text ?? ''))) : []);
  switch (event) {
    case 'text': case 'delta': case 'message':
      return { type: 'delta', text: String(j.delta ?? j.text ?? '') };
    case 'thinking':
      return { type: 'thinking', text: String(j.delta ?? '') };
    case 'step':
      return { type: 'step', step: j as unknown as AgentStep };
    case 'tool_call':
      return { type: 'step', step: { id: j.id as string, tool: String(j.name), status: 'running' } };
    case 'tool_result':
      return { type: 'step', step: { id: j.id as string, tool: String(j.name), status: j.is_error ? 'error' : 'done' } };
    case 'web':
      return { type: 'step', step: { tool: String(j.name ?? 'web_search'), status: 'done' } };
    case 'map_view':
      return { type: 'map_view', view: j as MapView };
    case 'error':
      return { type: 'error', code: String(j.error ?? 'unknown'), message: String(j.message ?? j.error ?? 'error') };
    case 'text_reset':
      return { type: 'reset' };
    case 'validation':
      return { type: 'validation', ok: j.ok === true, repairing: j.repairing === true,
        caveats: Array.isArray(j.caveats) ? j.caveats.length : 0, unsourced: texts(j.unsourced) };
    case 'done': {
      const v = j.validation as { ok?: boolean; unsourced?: unknown } | undefined;
      const cost = typeof j.cost_usd === 'number' ? j.cost_usd : undefined;
      return v && typeof v.ok === 'boolean'
        ? { type: 'done', validationOk: v.ok, unsourced: texts(v.unsourced), costUsd: cost }
        : { type: 'done', costUsd: cost };
    }
    default:
      return null;
  }
}
