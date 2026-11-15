import type { Map as MlMap } from 'maplibre-gl';
import { useEffect, useRef, useState, type ButtonHTMLAttributes, type MutableRefObject, type ReactNode } from 'react';
import { muteApplies, setBasemap, setMapUi, useMapUi } from '../lib/mapUi';
import { Hint, useHint } from './Hint';
import type { GlossaryKey } from '../lib/glossary';
import type { DrawMode } from '../state/store';
import { showAllUkraine } from '../lib/ukraine';
import { captureMonth, esriVersion, satMosaicYear } from '../lib/satellite';
import { CircleIcon, Minus, Plus, PolyIcon, UaIcon } from './icons';
import { useLocale, useT } from '../i18n';
import { pctUi } from './mapI18n';
import { layerShort } from '../lib/layers';

/** A map tool button whose glossary tip (board item 22, TOOLTIPS §3) opens on its left, replacing `title`. */
function TipButton({ k, quiet, children, ...rest }: { k: GlossaryKey; quiet?: boolean; children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const tip = useHint(k, 'left');
  return (
    <>
      <button type="button" className="tool" ref={tip.ref} {...rest} {...tip.props}>{children}</button>
      {!quiet && tip.node}
    </>
  );
}

export function MapTools({ draw, onDraw, mapRef, hidden }: {
  draw: DrawMode; onDraw: (m: DrawMode) => void; mapRef: MutableRefObject<MlMap | null>; hidden?: boolean;
}) {
  const t = useT();
  if (hidden) return null;
  return (
    <section className="tools" aria-label={t('tools.aria')}>
      <LayersPanel />
      <div className="toolgroup" role="group" aria-label={t('tools.drawGroup')}>
        <TipButton k="drawPolygon" aria-pressed={draw === 'polygon'}
          aria-label={t('tools.drawPolygon')} data-testid="draw-polygon" onClick={() => onDraw(draw === 'polygon' ? null : 'polygon')}><PolyIcon /></TipButton>
        <TipButton k="drawCircle" aria-pressed={draw === 'circle'}
          aria-label={t('tools.drawCircle')} data-testid="draw-circle" onClick={() => onDraw(draw === 'circle' ? null : 'circle')}><CircleIcon /></TipButton>
      </div>
      <div className="toolgroup" role="group" aria-label={t('tools.zoomGroup')}>
        <TipButton k="zoom" aria-label={t('tools.zoomIn')} onClick={() => mapRef.current?.zoomIn()}><Plus /></TipButton>
        <TipButton k="zoom" aria-label={t('tools.zoomOut')} onClick={() => mapRef.current?.zoomOut()}><Minus /></TipButton>
      </div>
      <div className="toolgroup" role="group" aria-label={t('tools.overviewGroup')}>
        <TipButton k="fitUkraine" aria-label={t('tools.fitUkraine')} data-testid="fit-ukraine"
          onClick={() => mapRef.current && showAllUkraine(mapRef.current)}><UaIcon /></TipButton>
      </div>
    </section>
  );
}

export function DrawHint({ mode, onCancel }: { mode: DrawMode; onCancel: () => void }) {
  const t = useT();
  if (!mode) return null;
  return (
    <div className="draw-hint" role="status" data-testid="draw-hint">
      <span>{mode === 'polygon'
        ? t('tools.hintPolygon')
        : t('tools.hintCircle')}</span>
      <button type="button" onClick={onCancel}>{t('tools.cancel')}</button>
    </div>
  );
}

const LayersIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" />
  </svg>
);


/**
 * «Шари» (item 7 + item 13): basemap «Карта / Супутник», «Видимість тепла» (100 % = as designed; 50 % on satellite
 * until the user sets it, item 26) and, on «Розрив» only (item 27) when the backend offers it, «Приглушити не-забудову». Native controls: keyboard works out of the box.
 */
export function LayersPanel() {
  const ui = useMapUi();
  const t = useT();
  const l = useLocale();
  const pct = (x: number) => pctUi(x, l);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); (box.current?.querySelector('button') as HTMLButtonElement | null)?.focus(); } };
    const onDown = (e: PointerEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('pointerdown', onDown);
    return () => { window.removeEventListener('keydown', onKey, true); window.removeEventListener('pointerdown', onDown); };
  }, [open]);
  const mute = muteApplies(ui);
  return (
    <div className="toolgroup layers" ref={box}>
      {/* the tip shows on hover/focus only, never over the open panel (TOOLTIPS §3) */}
      <TipButton k="layersPanel" quiet={open} aria-expanded={open} aria-controls="layers-panel" aria-label={t('tools.layers')}
        data-testid="layers-toggle" onClick={() => setOpen((o) => !o)}><LayersIcon /></TipButton>
      {open && (
        <div className="layers-panel" id="layers-panel" role="group" aria-label={t('tools.layers')} data-testid="layers-panel">
          <div className="lp-h">{t('tools.layersHead')}</div>
          <div className="lp-line"><div className="seg seg-sm" role="radiogroup" aria-label={t('tools.basemap')}>
            {(['map', 'sat'] as const).map((b) => (
              <button key={b} type="button" role="radio" aria-checked={ui.basemap === b} data-basemap={b}
                onClick={() => setBasemap(b)}>{b === 'map' ? t('tools.basemapMap') : t('tools.basemapSat')}</button>
            ))}
          </div><Hint k="basemap" side="above" /></div>
          <label className="lp-row">
            {/* Роман P1-4: the slider fades whichever layer is shown, so it is named after it */}
            <span><span data-testid="heat-visibility-label">{t('tools.layerVisibility', { layer: layerShort(ui.layer) })} <Hint k="heatTransparency" side="above" /></span> <b data-testid="heat-visibility-value">{pct(1 - ui.heatTransparency)}</b></span>
            <input type="range" min={0} max={100} step={5} value={Math.round((1 - ui.heatTransparency) * 100)} data-testid="heat-visibility"
              aria-valuetext={t('tools.layerVisibilityValue', { value: pct(1 - ui.heatTransparency) })}
              onChange={(e) => setMapUi({ heatTransparency: 1 - Number(e.target.value) / 100, heatTouched: true })} />
            <span className="xs lp-ends"><span>{t('tools.basemapOnly')}</span><span>{t('tools.fullLayer')}</span></span>
          </label>
          {mute && (
            <label className="lp-row">
              <span><span>{t('tools.mute')} <Hint k="muteNonBuilt" side="above" /></span> <b data-testid="mute-value">{pct(ui.mute)}</b></span>
              <input type="range" min={0} max={100} step={5} value={Math.round(ui.mute * 100)} data-testid="mute"
                aria-valuetext={t('tools.muteValue', { value: pct(ui.mute) })} onChange={(e) => setMapUi({ mute: Number(e.target.value) / 100 })} />
              <span className="xs lp-ends"><span>{t('tools.allLand')}</span><span>{t('tools.builtOnly')}</span></span>
            </label>
          )}
          {ui.reportId && (
            <label className="lp-check">
              <input type="checkbox" checked={ui.showReference} data-testid="show-reference" onChange={(e) => setMapUi({ showReference: e.target.checked })} />
              <span>{t('tools.showRef')} <span className="ref-key" aria-hidden="true" /></span>
            </label>
          )}
          {ui.showReference && ui.reportId && ui.reference === 'loading' && <p className="xs lp-note">{t('tools.refLoading')}</p>}
          {ui.showReference && ui.reportId && ui.reference === 'none' && <p className="xs lp-note" data-testid="reference-none">{t('map.refNone')}</p>}
          {ui.basemap === 'sat' && <p className="xs lp-note">{ui.satEox ? t('tools.satNoteEox', { year: satMosaicYear(ui.mapYear) }) : (ui.satShown?.captured ? t('tools.satNoteCaptured', { date: captureMonth(l, ui.satShown.captured) }) : t('tools.satNote', { version: (ui.satShown?.date ?? esriVersion(ui.mapYear).date).slice(0, 7) }))}</p>}
        </div>
      )}
    </div>
  );
}
