import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { Map as MlMap } from 'maplibre-gl';
import type { Polygon } from 'geojson';
import type { Climate, Meta, Overview, PlaceHit, ZoneGeometry } from './api/types';
import { sendsPlaceId } from './api/types';
import { hotspotTip, hotspotYears, hotspotsOnLayer } from './lib/story';
import { isMapLayer } from './lib/layers';
import { analyze, getClimate, getMeta, getOverview, getPlace, HttpError, searchPlaces, usingFixtures } from './api/client';
import { choosePlaceHit, type MapLabel } from './lib/labelPick';
import { errorMessage, initialState, reducer, type DrawMode, type Selection } from './state/store';
import { useDarkTheme } from './state/theme';
import { parseUrl, toSearch, zoneKey, DEFAULT_ZONE, type UrlState } from './lib/url';
import { bbox, centroid, validateDrawn } from './lib/geo';
import { setMapUi } from './lib/mapUi';
import { AWAY_SECONDS, awayStep, leftInset, loadCollapsed, saveCollapsed, zoneK } from './lib/insets';
import { CARD_ID, CardPill, CollapseButton } from './components/CardCollapse';
import { ExportMenu } from './components/ExportMenu';
import { Search, EXAMPLE_IDS } from './components/Search';
import { AnswerCard, zoneTitle } from './components/AnswerCard';
import { BottomStrip } from './components/BottomStrip';
import { DrawHint, MapTools } from './components/MapTools';
import type { CompareRow } from './components/charts';
import { ChatIcon, Close, Logo } from './components/icons';
import { PLACES } from './fixtures';
import { getLocale as getLocaleNow, LOCALES, LOCALE_LABEL, setLocale, tr, useLocale, withLang } from './i18n';
import { LangSwitch } from './components/LangSwitch';
import { nameEn } from './i18n/placeName';

// heavy parts load in separate chunks so the first answer does not wait for them (QA R3-3)
const MapView = lazy(() => import('./components/MapView').then((m) => ({ default: m.MapView })));
const DetailsPanel = lazy(() => import('./components/DetailsPanel').then((m) => ({ default: m.DetailsPanel })));
const ChatPanel = lazy(() => import('./components/ChatPanel').then((m) => ({ default: m.ChatPanel })));

export default function App() {
  const [s, dispatch] = useReducer(reducer, initialState);
  // Only a report accepted by the current selection's sequence guard owns the map.
  // Loading/error states clear it before paint, including a pending geometry lookup.
  useLayoutEffect(() => {
    const active = s.report.status === 'ready' || s.report.status === 'empty' ? s.report.report : null;
    setMapUi({ reportId: active?.report_id ?? null, zoneOutline: active?.zone_outline ?? null });
  }, [s.report]);
  const theme = useDarkTheme();
  const lang = useLocale(); // I18N.md: the whole tree re-renders on a language switch
  const mapRef = useRef<MlMap | null>(null);
  const seq = useRef(0);
  const placeCache = useRef(new Map<string, ZoneGeometry>());
  const [cityGeom, setCityGeom] = useState<ZoneGeometry | null>(null);
  const [compareVals, setCompareVals] = useState<Record<string, number | null>>({});
  const [climate, setClimate] = useState<Climate | null | 'error'>(null);
  // MAP-TASKS 3: country markers (fetched once) and whether the map currently shows them (below z9)
  const [overview, setOverview] = useState<Overview | null>(null);
  const [lowZoom, setLowZoom] = useState(false);
  useEffect(() => { void getOverview().then(setOverview); }, []);
  const chatBtn = useRef<HTMLButtonElement>(null);
  const limitsRef = useRef<{ min_area_km2: number; max_area_km2: number } | undefined>(undefined);
  limitsRef.current = s.meta?.limits;
  // MAP-TASKS 12: collapsible card. `collapsed` starts from the user's manual choice for this session.
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const toggleCard = useCallback((c: boolean) => {
    setCollapsed(c);
    saveCollapsed(c);
    // keep keyboard focus on the counterpart control (the pressed one unmounts)
    setTimeout(() => document.querySelector<HTMLElement>(`[data-testid=${c ? 'card-expand' : 'card-collapse'}]`)?.focus(), 0);
  }, []);
  const panArmed = useRef(false); // the user moved the map since the zone was selected
  const awayHold = useRef(false); // expanded by hand while the zone is still away: no auto-minimise until it is back

  const placeNames = useRef(new Map<string, string>());
  const placeNamesEn = useRef(new Map<string, string>());
  const placeKinds = useRef(new Map<string, string>());
  const fetchGeom = useCallback(async (id: string) => {
    const hit = placeCache.current.get(id);
    if (hit) return hit;
    const p = await getPlace(id);
    placeCache.current.set(id, p.geometry);
    if (p.name) placeNames.current.set(id, p.name);
    if (p.name_en) placeNamesEn.current.set(id, p.name_en);
    if (p.kind) placeKinds.current.set(id, p.kind);
    return p.geometry;
  }, []);

  const run = useCallback(async (geometry: ZoneGeometry, id: number, presetId?: string) => {
    try {
      const report = await analyze({ geometry, ...(sendsPlaceId(presetId, presetId ? placeKinds.current.get(presetId) : undefined) ? { place_id: presetId } : {}) }, presetId);
      dispatch({ type: 'reportOk', seq: id, report });
    } catch (e) {
      const he = e instanceof HttpError ? e : null;
      dispatch({ type: 'reportError', seq: id, message: errorMessage(he?.status, he?.body?.error), code: he?.body?.error });
    }
  }, []);

  const selectPreset = useCallback(async (hit: { id: string; name: string; name_en?: string; subtitle?: string; city?: string }) => {
    const id = ++seq.current;
    const cityId = hit.city ?? (hit.id.includes('-') ? hit.id.split('-')[0] : PLACES[hit.id]?.kind === 'city' ? hit.id : undefined);
    const selection: Selection = { kind: 'preset', id: hit.id, name: hit.name, name_en: hit.name_en ?? placeNamesEn.current.get(hit.id), subtitle: hit.subtitle, cityId };
    dispatch({ type: 'select', seq: id, selection, geometry: placeCache.current.get(hit.id) ?? null });
    try {
      const g = await fetchGeom(hit.id);
      if (id !== seq.current) return;
      dispatch({ type: 'geometry', geometry: g });
      const known = placeNames.current.get(hit.id);
      const knownEn = placeNamesEn.current.get(hit.id);
      if ((!hit.name && known) || knownEn) dispatch({ type: 'rename', seq: id, name: hit.name || known || '', name_en: hit.name_en ?? knownEn });
      await run(g, id, hit.id);
    } catch (e) {
      const he = e instanceof HttpError ? e : null;
      dispatch({ type: 'reportError', seq: id, message: he?.status === 404 ? tr(getLocaleNow(), 'app.placeNotFoundError') : errorMessage(he?.status, he?.body?.error) });
    }
  }, [fetchGeom, run]);

  const selectDrawn = useCallback((g: Polygon) => {
    const check = validateDrawn(g, limitsRef.current);
    if (!check.ok) { dispatch({ type: 'drawError', message: check.reason }); return; }
    const id = ++seq.current;
    dispatch({ type: 'select', seq: id, selection: { kind: 'drawn', geometry: g, areaKm2: check.areaKm2 } });
    void run(g, id);
  }, [run]);

  const retry = () => {
    // Retry the current selection, including its geometry lookup if that failed.
    // A previous successful analysis may belong to a different place.
    if (s.selection?.kind === 'preset') {
      void selectPreset({ id: s.selection.id, name: s.selection.name, name_en: s.selection.name_en, subtitle: s.selection.subtitle, city: s.selection.cityId });
    } else if (s.selection?.kind === 'drawn') {
      selectDrawn(s.selection.geometry);
    }
  };

  /** Select the zone/area described by a URL (boot, Back/Forward). */
  const applyZone = useCallback((u: UrlState, meta: Meta | null) => {
    if (u.area) { selectDrawn(u.area); return; }
    const zone = u.zone ?? DEFAULT_ZONE;
    const preset = meta?.presets.find((p) => p.id === zone);
    const fx = PLACES[zone];
    // unknown ids get their name from /api/places/{id}; never show the raw id as a title (QA-19)
    void selectPreset({ id: zone, name: preset?.name ?? fx?.name ?? '', name_en: preset?.name_en, subtitle: fx?.subtitle, city: preset?.city });
  }, [selectDrawn, selectPreset]);
  const metaRef = useRef<Meta | null>(null);
  metaRef.current = s.meta;

  // boot: meta + initial zone from URL (default: Позняки)
  const boot = useCallback(() => {
    const u = parseUrl(window.location.search);
    Promise.all([getMeta(), usingFixtures()])
      .then(([meta, demo]) => {
        dispatch({ type: 'meta', meta, demo });
        // a zone the user picked while we were booting wins over the URL/default zone (QA-07)
        if (seq.current === 0) applyZone(u, meta);
      })
      .catch(() => dispatch({ type: 'metaError', message: tr(getLocaleNow(), 'app.metaError') }));
  }, [applyZone]);
  useEffect(() => {
    const u = parseUrl(window.location.search);
    if (u.year) dispatch({ type: 'year', year: u.year });
    if (u.layer) dispatch({ type: 'layer', layer: u.layer });
    if (u.panel === 'details') dispatch({ type: 'panel', panel: 'details' });
    boot();
  }, [boot]);

  // URL state (shareable link). Zone/area/panel changes push a history entry (Back works inside the app,
  // QA-09); year/layer changes only replace it.
  const lastNav = useRef<string | null>(null);
  useEffect(() => {
    if (!s.selection) return;
    const search = toSearch({
      zone: s.selection.kind === 'preset' ? s.selection.id : null,
      area: s.selection.kind === 'drawn' ? s.selection.geometry : null,
      year: s.year, layer: s.layer, panel: s.panel,
    });
    const nav = `${zoneKey(search)}|${s.panel}`;
    const push = lastNav.current !== null && lastNav.current !== nav;
    lastNav.current = nav;
    if (withLang(search, getLocaleNow()) === window.location.search) return;
    const url = `${window.location.pathname}${withLang(search, getLocaleNow())}`;
    if (push) window.history.pushState(null, '', url);
    else window.history.replaceState(null, '', url);
  }, [s.selection, s.year, s.layer, s.panel]);
  useEffect(() => {
    const onPop = () => {
      const u = parseUrl(window.location.search);
      if (u.year) dispatch({ type: 'year', year: u.year });
      dispatch({ type: 'layer', layer: u.layer ?? 'gap' });
      dispatch({ type: 'panel', panel: u.panel });
      lastNav.current = `${zoneKey(window.location.search)}|${u.panel}`;
      if (zoneKey(window.location.search) !== curZone.current) applyZone(u, metaRef.current);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [applyZone]);
  const curZone = useRef<string | null>(null);
  curZone.current = s.selection
    ? zoneKey(toSearch({ zone: s.selection.kind === 'preset' ? s.selection.id : null, area: s.selection.kind === 'drawn' ? s.selection.geometry : null, year: null, layer: null, panel: 'card' }))
    : null;

  // Esc closes «Деталі» (unless the search dropdown, chat or drawing handled it)
  useEffect(() => {
    if (s.panel !== 'details' || s.chatOpen || s.draw) return;
    const on = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      if ((e.target as HTMLElement | null)?.closest?.('.search')) return;
      dispatch({ type: 'panel', panel: 'card' });
      setTimeout(() => document.querySelector<HTMLElement>('[data-testid=open-details]')?.focus(), 0);
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [s.panel, s.chatOpen, s.draw]);

  // MAP-TASKS 12: auto-minimise when the zone has been away from the view for ~1 s after a user pan/zoom, weighted by
  // the same continuous fade factor k as the map wash (item 10). Never auto-expands; never while «Деталі» are open.
  useEffect(() => { panArmed.current = false; awayHold.current = false; }, [s.geometry]);
  useEffect(() => {
    if (s.panel === 'details' || collapsed || !s.geometry) return;
    const b = bbox(s.geometry);
    let acc = 0, last = performance.now(), hooked: MlMap | null = null;
    const onStart = (e: { originalEvent?: unknown }) => { if (e.originalEvent) panArmed.current = true; };
    const t = setInterval(() => {
      const m = mapRef.current;
      const now = performance.now(), dt = (now - last) / 1000;
      last = now;
      if (!m) return;
      if (hooked !== m) { hooked?.off('movestart', onStart); m.on('movestart', onStart); hooked = m; }
      if (!panArmed.current) { acc = 0; return; }
      const c = m.getContainer();
      const k = zoneK(b, (ll) => m.project(ll), c.clientWidth, c.clientHeight);
      if (k >= 1) awayHold.current = false;
      if (awayHold.current) { acc = 0; return; }
      acc = awayStep(acc, k, dt);
      if (acc >= AWAY_SECONDS) setCollapsed(true);
    }, 100);
    return () => { clearInterval(t); hooked?.off('movestart', onStart); };
  }, [s.panel, collapsed, s.geometry]);
  // search focus minimises the card; a picked result opens it expanded (onPick); leaving the search without a pick
  // (Esc, focus elsewhere) restores the card as it was
  const collapsedRef = useRef(collapsed);
  collapsedRef.current = collapsed;
  const searchPrior = useRef<boolean | null>(null);
  useEffect(() => {
    const inSearch = (t: EventTarget | null) => !!(t as HTMLElement | null)?.closest?.('.search');
    const restore = () => { if (searchPrior.current !== null) { setCollapsed(searchPrior.current); searchPrior.current = null; } };
    const onIn = (e: Event) => {
      if ((e.target as HTMLElement | null)?.id !== 'search' || s.panel === 'details' || searchPrior.current !== null) return;
      searchPrior.current = collapsedRef.current;
      setCollapsed(true);
    };
    const onOut = (e: FocusEvent) => { if (inSearch(e.target) && !inSearch(e.relatedTarget)) restore(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && inSearch(e.target)) restore(); };
    document.addEventListener('focusin', onIn);
    document.addEventListener('pointerdown', onIn); // clicking / typing in the box again after an Esc
    document.addEventListener('input', onIn);
    document.addEventListener('focusout', onOut);
    window.addEventListener('keydown', onKey);
    return () => { for (const t of ['focusin', 'pointerdown', 'input'] as const) document.removeEventListener(t, onIn); document.removeEventListener('focusout', onOut); window.removeEventListener('keydown', onKey); };
  }, [s.panel]);
  // Esc toggles the card (Details, chat, drawing and the search box handle their own Esc)
  useEffect(() => {
    if (s.panel === 'details' || s.chatOpen || s.draw || s.metaError) return;
    const on = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest?.('.search, input, textarea, select, .maplibregl-popup')) return;
      if (collapsed) awayHold.current = true;
      toggleCard(!collapsed);
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [s.panel, s.chatOpen, s.draw, s.metaError, collapsed, toggleCard]);

  // city outline for districts
  const cityId = s.selection?.kind === 'preset' ? s.selection.cityId : undefined;
  useEffect(() => {
    setCityGeom(null);
    if (!cityId || (s.selection?.kind === 'preset' && s.selection.id === cityId)) return;
    let live = true;
    fetchGeom(cityId).then((g) => live && setCityGeom(g)).catch(() => undefined);
    return () => { live = false; };
  }, [cityId, s.selection, fetchGeom]);

  const report = s.report.status === 'ready' ? s.report.report : null;
  // hotspots are the last summers with data (API `years`), not the map year: say so when the map shows another summer
  const hotYears = report?.hotspots?.length ? hotspotYears(report.hotspots) : '';
  const hotOtherYear = !!hotYears && !!s.year && !report!.hotspots!.some((h) => h.years?.includes(s.year!));
  const title = zoneTitle(s.selection, report ?? undefined, true);
  // <title> and meta description per language (I18N.md §5.1); Ukrainian keeps index.html's own texts
  useEffect(() => {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    document.title = title ? tr(lang, 'app.docTitle', { place: title }) : tr(lang, 'app.name');
    if (meta) meta.content = tr(lang, 'app.metaDescription');
  }, [lang, title]);
  const selPresetId = s.selection?.kind === 'preset' ? s.selection.id : null;
  const selPlaceKind = selPresetId ? s.meta?.presets.find((p) => p.id === selPresetId)?.kind ?? placeKinds.current.get(selPresetId) : undefined;

  // details: comparison zones + climate
  const comparePresets = useMemo(() => {
    const city = cityId ?? 'kyiv';
    const selId = s.selection?.kind === 'preset' ? s.selection.id : null;
    return (s.meta?.presets ?? []).filter((p) => (p.city === city || p.id === city) && (p.kind === 'demo_zone' || p.kind === 'city' || p.id === selId)).slice(0, 8);
  }, [s.meta, cityId]);
  useEffect(() => {
    if (s.panel !== 'details' || !report) return;
    // results are per preset and stay valid, so they are stored even if this effect re-ran meanwhile
    // (gating them on the effect's lifetime left bars stuck in «loading», QA R3-2)
    for (const p of comparePresets) {
      if (p.id in compareVals) continue;
      setCompareVals((v) => ({ ...v, [p.id]: null }));
      fetchGeom(p.id)
        .then((g) => analyze({ geometry: g, place_id: p.id }, p.id))
        .then((r) => setCompareVals((v) => ({ ...v, [p.id]: r.gap_summary.mean })))
        .catch(() => setCompareVals((v) => { const c = { ...v }; delete c[p.id]; return c; }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.panel, report, comparePresets]);
  // climate outlook: the card shows one line, details the table (loaded once the report is there)
  const hasReport = s.report.status === 'ready' || s.report.status === 'empty';
  useEffect(() => {
    if (!hasReport || !s.geometry) return;
    setClimate(null);
    const [lon, lat] = centroid(s.geometry);
    let live = true;
    getClimate(lat, lon).then((c) => live && setClimate(c)).catch(() => live && setClimate('error'));
    return () => { live = false; };
  }, [hasReport, s.geometry]);

  const compareRows: CompareRow[] = useMemo(() => {
    const selId = s.selection?.kind === 'preset' ? s.selection.id : null;
    const rows: CompareRow[] = comparePresets
      .filter((p) => p.id in compareVals || p.id === selId)
      .map((p) => ({ id: p.id, name: p.id === selId ? title : lang === 'en' ? nameEn(p.name, p.name_en) : p.name, value: p.id === selId ? report?.gap_summary.mean ?? null : compareVals[p.id] ?? null, sel: p.id === selId }));
    if (!selId && report) rows.unshift({ id: 'drawn', name: tr(lang, 'app.yourArea'), value: report.gap_summary.mean, sel: true });
    return rows.sort((a, b) => (b.value ?? -99) - (a.value ?? -99));
  }, [comparePresets, compareVals, s.selection, report, title, lang]);

  const examples: PlaceHit[] = useMemo(() => {
    const presets = s.meta?.presets ?? [];
    return EXAMPLE_IDS.flatMap((id) => {
      const p = presets.find((x) => x.id === id);
      if (!p) return [];
      const city = s.meta?.cities.find((c) => c.id === p.city)?.name;
      // English siblings for Search (hitText): the API's *_en, else the transliterated name
      const x = p as { name_en?: string; note_en?: string };
      return [{ id, name: p.name, kind: p.kind, city: p.city, subtitle: p.kind === 'city' ? tr(lang, 'app.wholeCity') : city, note_uk: p.note_uk,
        name_en: nameEn(p.name, x.name_en), ...(x.note_en ? { note_en: x.note_en } : {}), ...(city && p.kind !== 'city' ? { subtitle_en: nameEn(city) } : {}) }];
    });
  }, [s.meta, lang]);

  const onPick = (h: PlaceHit) => {
    searchPrior.current = null;
    setCollapsed(false); // a new result opens expanded
    const preset = s.meta?.presets.find((p) => p.id === h.id);
    void selectPreset({ id: h.id, name: h.name, name_en: h.name_en, subtitle: h.subtitle, city: preset?.city ?? h.city });
  };

  // Роман 15.11: a basemap name click = picking that place in the search (preset near the label, else the geocoder hit)
  const labelSeq = useRef(0);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const pickLabel = useCallback(async (lab: MapLabel) => {
    const my = ++labelSeq.current;
    const startSeq = seq.current;
    const hits = await searchPlaces(lab.name).catch(() => [] as PlaceHit[]);
    // a newer label click or any other selection meanwhile wins
    if (my !== labelSeq.current || seq.current !== startSeq) return;
    const h = choosePlaceHit(hits, lab);
    if (h) pickRef.current(h);
  }, []);

  const gapStops = useMemo(() => {
    const g = s.meta?.layers.find((l) => l.id === 'gap');
    return g ? (theme === 'dark' && g.stops_dark ? g.stops_dark : g.stops) : undefined;
  }, [s.meta, theme]);
  // item 17 C: only the 4 user-facing layers (a stale ?layer=gap_fill falls back to the first one)
  const userLayers = useMemo(() => (s.meta?.layers ?? []).filter(isMapLayer), [s.meta]);
  const layerMeta = userLayers.find((l) => l.id === s.layer) ?? userLayers[0];
  const years = s.meta?.years ?? [];
  // Details also open for a report without a gap (empty state), so its caveats are reachable (QA R3-4)
  const detailsReport = s.report.status === 'ready' || s.report.status === 'empty' ? s.report.report : null;
  const details = s.panel === 'details' && detailsReport;
  // item 29: share link from app state — zone / area, year, layer; no transient view=details or card state
  const shareUrl = s.selection ? `${window.location.origin}${window.location.pathname}${withLang(toSearch({
    zone: s.selection.kind === 'preset' ? s.selection.id : null, area: s.selection.kind === 'drawn' ? s.selection.geometry : null,
    year: s.year, layer: s.layer, panel: 'card',
  }), lang)}` : window.location.href;
  const exportFor = (up: boolean) => (
    <ExportMenu reportId={detailsReport?.report_id ?? null} shareUrl={shareUrl} title={title ? tr(lang, 'app.docTitle', { place: title }) : tr(lang, 'app.name')} demo={s.demo} up={up} />
  );

  const setDraw = (m: DrawMode) => dispatch({ type: 'draw', mode: m });
  const closeChat = () => { dispatch({ type: 'chat', open: false }); chatBtn.current?.focus(); };

  return (
    <>
      <a className="skip-link" href="#search" onClick={(e) => { e.preventDefault(); document.getElementById('search')?.focus(); }}>{tr(lang, 'app.skipToSearch')}</a>
      <Suspense fallback={null}>
      <MapView
        theme={theme} geometry={s.geometry} label={s.selection && title ? title : null} cityGeometry={cityGeom}
        layer={layerMeta?.id ?? 'gap'} year={s.year} tiles={!!s.meta && !s.demo}
        leftInset={leftInset({ details: !!details, collapsed })} draw={s.draw}
        onDrawn={(g) => { setCollapsed(false); selectDrawn(g); }} onDrawCancel={() => setDraw(null)} mapRef={mapRef}
        hotspots={report?.hotspots?.map((h, i) => ({ center: h.center, tip: hotspotTip(h, i) + (hotOtherYear ? tr(lang, 'app.hotspotOtherYear', { year: s.year ?? '', years: hotYears }) : ''), polygon: h.polygon }))}
        showHotspots={hotspotsOnLayer(s.layer)}
        chrome={`${!!(s.year && years.length > 0 && !s.chatOpen)}-${!!details}-${collapsed}`} exploring={collapsed}
        overview={overview} onOverviewZoom={setLowZoom}
        fillLayer={s.layer === 'gap' || s.layer === 'lst' ? s.meta?.fill?.[s.layer as 'gap' | 'lst'] ?? null : null}
        gapStops={gapStops}
        onPickPlace={(p) => { setCollapsed(false); void selectPreset({ id: p.place_id, name: p.name, name_en: p.name_en, subtitle: p.oblast ?? undefined, city: p.city ?? undefined }); }}
        onPickLabel={(l) => { void pickLabel(l); }}
      />
      </Suspense>
      <header className="top">
        <div className="brand">
          <Logo /><span className="brand-name">{tr(lang, 'app.name')}</span><span className="brand-tag" data-testid="brand-tag">{tr(lang, 'app.tagline')}</span>
          {s.demo && <span className="demo-chip" title={tr(lang, 'app.demoChipTitle')} data-testid="demo-chip">{tr(lang, 'app.demoChip')}</span>}
        </div>
        <p className="team-credit" lang="en" data-testid="team-credit">Made by Coaches Team from KSE Delta Engineering</p>
        <Search examples={examples} onSelect={onPick} />
        <div className="top-right">
          <LangSwitch lang={lang} onChange={setLocale} locales={LOCALES} labels={LOCALE_LABEL} />
          <button type="button" ref={chatBtn} className="pill" aria-pressed={s.chatOpen} aria-expanded={s.chatOpen} onClick={() => (s.chatOpen ? closeChat() : dispatch({ type: 'chat', open: true }))} data-testid="ask">
            <ChatIcon />{tr(lang, 'app.askAnalyst')}
          </button>
        </div>
      </header>

      <main>
        {s.metaError ? (
          <section className="card answer" data-testid="answer-error" aria-labelledby="ans-title">
            <h1 id="ans-title" style={{ fontSize: 28 }}>{tr(lang, 'app.unavailableTitle')}</h1>
            <p className="lead" style={{ marginTop: 14 }} role="alert">{s.metaError}</p>
            <div className="card-foot"><button type="button" className="btn" onClick={() => { dispatch({ type: 'metaRetry' }); boot(); }}>{tr(lang, 'app.retry')}</button></div>
          </section>
        ) : details ? (
          <Suspense fallback={<section className="card details" aria-busy="true"><div className="skel" style={{ height: 300 }} /></section>}>
          <DetailsPanel
            report={detailsReport!} title={title} year={s.year} onYear={(y) => dispatch({ type: 'year', year: y })}
            onBack={() => dispatch({ type: 'panel', panel: 'card' })} layers={userLayers} layer={layerMeta?.id ?? 'gap'}
            onLayer={(l) => dispatch({ type: 'layer', layer: l })} compare={compareRows} climate={climate} demo={s.demo} exportMenu={exportFor(true)}
          />
          </Suspense>
        ) : collapsed ? (
          <CardPill name={title} loading={s.report.status === 'loading' || s.report.status === 'idle'}
            mean={s.report.status === 'ready' ? s.report.report.gap_summary.mean : s.report.status === 'empty' ? null : undefined}
            onExpand={() => { awayHold.current = true; toggleCard(false); }} />
        ) : (
          <div className="card-wrap" id={CARD_ID}>
          <AnswerCard selection={s.selection} state={s.report} onDetails={() => dispatch({ type: 'panel', panel: 'details' })} onRetry={retry}
            onSearch={() => document.getElementById('search')?.focus()} climate={climate} placeKind={selPlaceKind} year={s.year} exportMenu={exportFor(true)}
            onHotspot={(c) => mapRef.current?.flyTo({ center: c, zoom: 15, duration: 900 })} />
          {s.selection && <CollapseButton onCollapse={() => toggleCard(true)} />}
          </div>
        )}
      </main>

      <MapTools draw={s.draw} onDraw={setDraw} mapRef={mapRef} hidden={s.chatOpen} />
      <DrawHint mode={s.draw} onCancel={() => setDraw(null)} />
      {s.drawError && (
        <div className="alert" role="alert" data-testid="draw-error">
          <span>{s.drawError}</span>
          <button type="button" aria-label={tr(lang, 'app.closeMessage')} onClick={() => dispatch({ type: 'drawError', message: null })}><Close /></button>
        </div>
      )}

      {s.year && years.length > 0 && !s.chatOpen && (
        <BottomStrip year={s.year} years={years} series={report?.series ?? null} layer={layerMeta} layers={userLayers} theme={theme}
          onYear={(y) => dispatch({ type: 'year', year: y })} onLayer={(l) => dispatch({ type: 'layer', layer: l })} showBars={!details}
          hotLegend={hotspotsOnLayer(s.layer) && !lowZoom ? report?.hotspots?.length ?? 0 : 0} hotYears={hotYears} overview={lowZoom && !!overview}
          fillNote={!lowZoom && (s.layer === 'gap' || s.layer === 'lst') && s.meta?.fill?.[s.layer as 'gap' | 'lst'] ? (lang === 'en' ? tr(lang, 'strip.fillNote') : s.meta.fill.label_uk ?? 'заповнено з сусідніх років') : null} />
      )}

      {s.chatOpen && (
        <Suspense fallback={null}>
        <ChatPanel
          context={{ report_id: report?.report_id ?? null, place_id: s.selection?.kind === 'preset' ? s.selection.id : null, layer: s.layer, year: s.year }}
          zoneName={title} onClose={closeChat}
          onMapView={(v) => {
            if (v.layer) dispatch({ type: 'layer', layer: v.layer });
            if (v.year) dispatch({ type: 'year', year: v.year });
            const pid = v.place_ids?.[0];
            const p = pid ? s.meta?.presets.find((x) => x.id === pid) : undefined;
            if (pid) void selectPreset({ id: pid, name: p?.name ?? pid, name_en: p?.name_en, city: p?.city });
          }}
        />
        </Suspense>
      )}
    </>
  );
}
