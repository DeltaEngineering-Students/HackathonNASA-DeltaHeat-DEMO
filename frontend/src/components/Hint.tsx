// Board item 22: one accessible tooltip implementation for the whole app (spec: uhd/docs/TOOLTIPS.md §2).
// <Term k="gap">розрив</Term> — a dotted word; <Hint k="pValue" /> — an ⓘ button next to an element.
// Texts come only from lib/glossary.ts. One open tip in the whole app; Esc closes the tip only.
import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { gloss, type GlossaryKey } from '../lib/glossary';
import { getLocale as getLocaleNow, tr, useLocale } from '../i18n';
import type { CustomTip } from '../lib/cardTips';

/** «Див. також» shows at most this many links (Володя 15.11: no rabbit holes). */
export const SEE_ALSO_MAX = 2;
/** Glossary keys whose text is already on screen (Details provides them): never offered as «Див. також». */
export const TipShownContext = createContext<ReadonlySet<string>>(new Set());
/** The «Див. також» links of an entry: minus what is on screen, at most SEE_ALSO_MAX. */
export const seeAlsoLinks = (list: readonly string[] | undefined, shown: ReadonlySet<string>, self: string) =>
  (list ?? []).filter((x) => x !== self && !shown.has(x)).slice(0, SEE_ALSO_MAX);

type Side = 'above' | 'below' | 'left';
const OPEN_DELAY = 250;
const CLOSE_GRACE = 150;
const MARGIN = 8;

// ---- one open tip at a time --------------------------------------------------------------------------------------
let closeCurrent: (() => void) | null = null;
function claim(close: () => void) {
  if (closeCurrent && closeCurrent !== close) closeCurrent();
  closeCurrent = close;
}
function release(close: () => void) {
  if (closeCurrent === close) closeCurrent = null;
}

const isTouch = (e?: { pointerType?: string }) =>
  e?.pointerType === 'touch' || e?.pointerType === 'pen' || (typeof window !== 'undefined' && !!window.matchMedia?.('(hover: none)').matches);

/** Where the bubble goes: the preferred side, flipped if it does not fit, shifted to stay 8 px inside the viewport. */
export function placeBubble(t: { left: number; top: number; right: number; bottom: number }, b: { width: number; height: number }, vw: number, vh: number, side: Side): { left: number; top: number; side: Side } {
  const clampX = (x: number) => Math.max(MARGIN, Math.min(vw - b.width - MARGIN, x));
  const clampY = (y: number) => Math.max(MARGIN, Math.min(vh - b.height - MARGIN, y));
  const cx = (t.left + t.right) / 2 - b.width / 2;
  const fitsBelow = t.bottom + 6 + b.height + MARGIN <= vh;
  const fitsAbove = t.top - 6 - b.height - MARGIN >= 0;
  if (side === 'left') {
    const x = t.left - 8 - b.width;
    if (x >= MARGIN) return { left: x, top: clampY((t.top + t.bottom) / 2 - b.height / 2), side: 'left' };
    side = fitsBelow ? 'below' : 'above';
  }
  if (side === 'above' && !fitsAbove && fitsBelow) side = 'below';
  if (side === 'below' && !fitsBelow && fitsAbove) side = 'above';
  return side === 'above'
    ? { left: clampX(cx), top: clampY(t.top - 6 - b.height), side }
    : { left: clampX(cx), top: clampY(t.bottom + 6), side };
}

function useTip(k: GlossaryKey, side: Side, custom?: CustomTip) {
  useLocale(); // re-render the tip texts on a language switch
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState<GlossaryKey>(k);
  const [more, setMore] = useState(false);
  const trigger = useRef<HTMLElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const viaHover = useRef(false);
  const id = useId();
  const tipId = `tip-${id}`;
  const srId = `tipsr-${id}`;

  const clear = () => { if (timer.current !== undefined) { window.clearTimeout(timer.current); timer.current = undefined; } };
  const close = useCallback(() => { clear(); setOpen(false); setMore(false); setCur(k); viaHover.current = false; }, [k]);
  const show = useCallback(() => { clear(); claim(close); setOpen(true); }, [close]);
  useEffect(() => { if (open) claim(close); else release(close); }, [open, close]);
  useEffect(() => () => { clear(); release(close); }, [close]);

  // Esc closes the tip only (capture phase, before the app's own Esc handlers); outside tap / press closes it too
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      const back = bubble.current?.contains(document.activeElement);
      close();
      if (back) trigger.current?.focus();
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (trigger.current?.contains(t) || bubble.current?.contains(t)) return;
      close();
    };
    window.addEventListener('keydown', onKey, true);
    document.addEventListener('pointerdown', onDown, true);
    return () => { window.removeEventListener('keydown', onKey, true); document.removeEventListener('pointerdown', onDown, true); };
  }, [open, close]);

  const handlers = {
    onPointerEnter: (e: React.PointerEvent) => { if (isTouch(e)) return; clear(); if (!open) { viaHover.current = true; timer.current = window.setTimeout(show, OPEN_DELAY); } },
    onPointerLeave: (e: React.PointerEvent) => { if (isTouch(e) || !viaHover.current) return; clear(); timer.current = window.setTimeout(close, CLOSE_GRACE); },
    onFocus: () => { if (!open) show(); },
    onBlur: (e: React.FocusEvent) => { const n = e.relatedTarget as Node | null; if (!n || !bubble.current?.contains(n)) close(); },
    onClick: (e: React.MouseEvent) => {
      e.stopPropagation(); // a tip trigger never also triggers its parent
      const touch = isTouch((e.nativeEvent as PointerEvent));
      if (open && (touch || !viaHover.current)) close();
      else { viaHover.current = false; show(); }
    },
  };
  const bubbleHandlers = {
    onPointerEnter: (e: React.PointerEvent) => { if (!isTouch(e)) clear(); },
    onPointerLeave: (e: React.PointerEvent) => { if (!isTouch(e) && viaHover.current && !more) { clear(); timer.current = window.setTimeout(close, CLOSE_GRACE); } },
    onBlur: (e: React.FocusEvent) => { const n = e.relatedTarget as Node | null; if (!n || (!bubble.current?.contains(n) && n !== trigger.current)) close(); },
  };

  const node = open ? <Bubble ref={bubble} id={tipId} k={cur} more={more} side={side} anchor={trigger} custom={cur === k ? custom : undefined} onClose={close} {...bubbleHandlers}
    onMore={() => { clear(); setMore(true); }} onSee={(n) => { setCur(n); setMore(false); }} /> : null;
  // the description lives at the end of <body>: aria-describedby works document-wide, and the sentence never leaks into
  // the surrounding text (copy-paste, textContent of the card line)
  const sr = typeof document === 'undefined' ? null : createPortal(<span id={srId} className="sr-only">{custom?.short ?? gloss(k).short}</span>, document.body);
  return { open, close, trigger, handlers, node, sr, srId, tipId };
}

interface BubbleProps {
  id: string; k: GlossaryKey; more: boolean; side: Side; anchor: React.RefObject<HTMLElement | null>;
  onMore: () => void; onSee: (k: GlossaryKey) => void;
  /** a report-specific text instead of the glossary entry: no «Детальніше», no «Див. також», at most one link */
  custom?: CustomTip; onClose: () => void;
  onPointerEnter: (e: React.PointerEvent) => void; onPointerLeave: (e: React.PointerEvent) => void; onBlur: (e: React.FocusEvent) => void;
  ref: React.RefObject<HTMLDivElement | null>;
}
function Bubble({ id, k, more, side, anchor, onMore, onSee, custom, onClose, ref, ...h }: BubbleProps) {
  const l = useLocale();
  const g = gloss(k);
  const shown = useContext(TipShownContext);
  const see = seeAlsoLinks(g.seeAlso, shown, k);
  const [pos, setPos] = useState<CSSProperties>({ left: -9999, top: 0 });
  const moreBtn = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    const a = anchor.current, b = ref.current;
    if (!a || !b) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    if (vw <= 600) { setPos({ left: MARGIN, right: MARGIN, bottom: 120, top: 'auto' }); return; } // phone: bottom sheet above the strip
    const p = placeBubble(a.getBoundingClientRect(), b.getBoundingClientRect(), vw, vh, side);
    setPos({ left: p.left, top: p.top });
  }, [anchor, ref, side, k, more]);
  useEffect(() => { if (more) ref.current?.querySelector<HTMLElement>('.tip-more')?.focus(); }, [more, ref]);
  const interactive = more || !!custom?.link;
  if (custom) return createPortal(
    <div ref={ref} id={id} className={`tip${interactive ? ' is-open' : ''}`} style={pos} data-testid="tip" data-custom="1"
      role="tooltip" {...h}>
      <b className="tip-term">{custom.term}</b>
      <p className="tip-short" data-testid="tip-text">{custom.short}</p>
      {custom.link && <button type="button" className="tip-link" data-testid="tip-how" onClick={() => { onClose(); custom.link!.onClick(); }}>{custom.link.label}</button>}
    </div>,
    document.body,
  );
  return createPortal(
    <div ref={ref} id={id} className={`tip${interactive ? ' is-open' : ''}`} style={pos} data-testid="tip"
      role={interactive ? 'dialog' : 'tooltip'} aria-label={interactive ? g.term : undefined} {...h}>
      <b className="tip-term">{g.term}</b>
      <p className="tip-short">{g.short}</p>
      {g.more && !more && <button ref={moreBtn} type="button" className="tip-link" onClick={onMore}>{tr(l, 'tip.more')}</button>}
      {more && g.more && <p className="tip-more" tabIndex={-1}>{g.more}</p>}
      {more && see.length > 0 && (
        <p className="tip-see">{tr(l, 'tip.seeAlso')} {see.map((s, i) => (
          <span key={s}>{i ? ', ' : ''}<button type="button" className="tip-link" onClick={() => onSee(s as GlossaryKey)}>{gloss(s as GlossaryKey)?.term ?? s}</button></span>
        ))}</p>
      )}
    </div>,
    document.body,
  );
}

/** A dotted word that explains itself. Children default to the glossary term. */
export function Term({ k, children, side = 'below', className, tip }: { k: GlossaryKey; children?: ReactNode; side?: Side; className?: string; tip?: CustomTip }) {
  const t = useTip(k, side, tip);
  return (
    <>
      {/* a span, not a <button>: a button is always an inline-block, so a long term in a sentence broke the line (and
          left the full stop alone on the next one); Enter / Space do what a button would */}
      <span ref={t.trigger} role="button" tabIndex={0} className={`term${className ? ` ${className}` : ''}`} data-term={k}
        aria-describedby={t.srId} aria-expanded={t.open} aria-controls={t.open ? t.tipId : undefined} {...t.handlers}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); (e.currentTarget as HTMLElement).click(); } }}>
        {children ?? gloss(k).term}
      </span>
      {t.sr}
      {t.node}
    </>
  );
}

/**
 * A tip on an existing control (map tool buttons): hover / focus open it, Esc closes it, the control keeps its own click
 * (a click just closes the tip). Usage:
 *   const tip = useHint('drawPolygon', 'left');
 *   <button ref={tip.ref} {...tip.props} onClick={…}>…</button>{tip.node}
 * `aria-label` stays the control's name; the glossary sentence is its description.
 */
export function useHint<E extends HTMLElement = HTMLButtonElement>(k: GlossaryKey, side: Side = 'left') {
  const t = useTip(k, side);
  const { onPointerEnter, onPointerLeave, onFocus, onBlur } = t.handlers;
  const pressed = useRef(false); // focus that comes from a click is not a keyboard visit → no tip
  return {
    ref: t.trigger as React.RefObject<E | null>,
    props: {
      'aria-describedby': t.srId, onPointerEnter, onPointerLeave, onBlur,
      onFocus: () => { if (!pressed.current) onFocus(); },
      onPointerDown: () => { pressed.current = true; t.close(); window.setTimeout(() => { pressed.current = false; }, 0); },
    },
    node: <>{t.sr}{t.node}</>,
  };
}

/** An ⓘ button after an element (controls, numbers, headings). */
export function Hint({ k, side = 'below', for: forId, className, tip }: { k: GlossaryKey; side?: Side; for?: string; className?: string; tip?: CustomTip }) {
  const t = useTip(k, side, tip);
  return (
    <>
      <button ref={t.trigger as React.RefObject<HTMLButtonElement | null>} type="button" className={`hint-btn${className ? ` ${className}` : ''}`} data-hint={k} data-for={forId}
        aria-label={tr(getLocaleNow(), 'tip.whatIs', { term: tip?.term ?? gloss(k).term })} aria-describedby={t.srId} aria-expanded={t.open} aria-controls={t.open ? t.tipId : undefined} {...t.handlers}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M8 7.2v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /><circle cx="8" cy="4.9" r=".95" fill="currentColor" /></svg>
      </button>
      {t.sr}
      {t.node}
    </>
  );
}
