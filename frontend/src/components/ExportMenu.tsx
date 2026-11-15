// Board item 29: one «Експорт ▾» menu (card + Details) — PDF / Excel / CSV / JSON downloads of the stored report and
// «Поділитися посиланням». Menu button pattern (WAI-ARIA APG): Enter/Space/↓ opens on the first item, ↑ on the last,
// ↑/↓/Home/End move, Esc closes and returns focus, Tab closes.
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { API_BASE } from '../api/client';
import '../styles/export.css';
import { Hint } from './Hint';
import { useLocale, useT, withLang, type Locale } from '../i18n';

export type ExportFormat = 'pdf' | 'xlsx' | 'csv' | 'json';
const ORDER: ExportFormat[] = ['pdf', 'xlsx', 'csv', 'json'];

/** Download URL: the export endpoint when the backend serves that format, else the plain report JSON (JSON only).
 * item 32: `&lang=en` asks the backend for English files; Ukrainian keeps today's URL (the backend default). */
export function exportUrl(reportId: string, f: ExportFormat, served: ReadonlySet<ExportFormat>, l: Locale = 'uk'): string | null {
  const id = encodeURIComponent(reportId);
  const lang = l === 'en' ? '&lang=en' : '';
  if (served.has(f)) return `${API_BASE}/api/reports/${id}/export?format=${f}${lang}`;
  return f === 'json' ? `${API_BASE}/api/reports/${id}${lang ? '?lang=en' : ''}` : null;
}

/** Share link with the language explicit (I18N.md §1: a link copied in English opens in English). */
export function shareWithLang(url: string, l: Locale): string {
  try {
    const u = new URL(url, typeof location !== 'undefined' ? location.href : 'http://localhost/');
    u.search = withLang(u.search, l, true);
    return u.toString();
  } catch { return url; }
}

// Feature check, once per session, per format family (HEAD; anything but 200 → «скоро», never a dead link):
// csv / xlsx / json ship together (one probe), PDF ships later (own probe; 422 until then).
let probe: Promise<Set<ExportFormat>> | null = null;
const head = (id: string, f: ExportFormat) =>
  fetch(`${API_BASE}/api/reports/${encodeURIComponent(id)}/export?format=${f}`, { method: 'HEAD', signal: AbortSignal.timeout(8000) })
    .then((r) => r.status === 200)
    .catch(() => false);
export function probeExport(reportId: string): Promise<Set<ExportFormat>> {
  probe ??= Promise.all([head(reportId, 'json'), head(reportId, 'pdf')]).then(([tab, pdf]) => {
    const out = new Set<ExportFormat>();
    if (tab) { out.add('json'); out.add('csv'); out.add('xlsx'); }
    if (pdf) out.add('pdf');
    return out;
  });
  return probe;
}
/** test hook */
export const resetExportProbe = () => { probe = null; };

const GAP = 6, EDGE = 8;
/** Fixed position for the menu: above the button when asked and it fits (else below, else whichever has more room),
 * right edge aligned with the button when the left edge would overflow; always EDGE px inside the viewport. */
export function placeMenu(b: { left: number; right: number; top: number; bottom: number }, m: { width: number; height: number }, vw: number, vh: number, up: boolean): { left: number; top: number } {
  const fitsUp = b.top - GAP - m.height >= EDGE, fitsDown = b.bottom + GAP + m.height <= vh - EDGE;
  const goUp = up ? fitsUp || (!fitsDown && b.top > vh - b.bottom) : !fitsDown && (fitsUp || b.top > vh - b.bottom);
  let top = goUp ? b.top - GAP - m.height : b.bottom + GAP;
  top = Math.max(EDGE, Math.min(vh - EDGE - m.height, top));
  let left = b.left;
  if (left + m.width > vw - EDGE) left = b.right - m.width;
  left = Math.max(EDGE, Math.min(vw - EDGE - m.width, left));
  return { left, top };
}

async function share(url: string, title: string): Promise<'shared' | 'copied' | 'failed'> {
  const touch = typeof window !== 'undefined' && !!window.matchMedia?.('(hover: none)').matches;
  if (touch && typeof navigator.share === 'function') {
    try { await navigator.share({ title, url }); return 'shared'; } catch (e) { if ((e as Error).name === 'AbortError') return 'shared'; }
  }
  try { await navigator.clipboard.writeText(url); return 'copied'; } catch { return 'failed'; }
}

export function ExportMenu({ reportId, shareUrl, title, demo = false, up = false }: {
  reportId: string | null; shareUrl: string; title: string; demo?: boolean;
  /** open above the button (card footer) */
  up?: boolean;
}) {
  const t = useT();
  const l = useLocale();
  const LABEL: Record<ExportFormat, string> = { pdf: t('export.pdf'), xlsx: t('export.xlsx'), csv: t('export.csv'), json: t('export.json') };
  const [open, setOpen] = useState(false);
  const [served, setServed] = useState<ReadonlySet<ExportFormat>>(new Set());
  const [toast, setToast] = useState<string | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const id = useId();
  const canDownload = !!reportId && !demo;

  useEffect(() => { if (canDownload) void probeExport(reportId!).then(setServed); }, [canDownload, reportId]);
  useEffect(() => { if (!toast) return; const t = window.setTimeout(() => setToast(null), 2500); return () => window.clearTimeout(t); }, [toast]);

  const items = () => [...(menu.current?.querySelectorAll<HTMLElement>('[role=menuitem]:not([aria-disabled=true])') ?? [])];
  const focusAt = (i: number) => { const xs = items(); xs[(i + xs.length) % xs.length]?.focus(); };
  const pending = useRef<0 | -1 | null>(null);
  const openAt = (where: 'first' | 'last') => { pending.current = where === 'first' ? 0 : -1; setOpen(true); };
  // focus after the menu is rendered visible (not in a rAF that can run before the commit)

  const close = (refocus = true) => { setOpen(false); if (refocus) btn.current?.focus(); };

  // The menu lives in a portal at the end of <body> (fixed): the card / Details scroll containers clip anything inside
  // them. Measure hidden, then place; follow the button on scroll / resize.
  const [pos, setPos] = useState<CSSProperties | null>(null);
  const place = () => {
    const b = btn.current?.getBoundingClientRect(), m = menu.current;
    if (!b || !m) return;
    const p = placeMenu(b, { width: m.offsetWidth, height: m.offsetHeight }, window.innerWidth, window.innerHeight, up);
    setPos({ left: p.left, top: p.top });
  };
  useLayoutEffect(() => { if (open) place(); else setPos(null); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  // focus once the menu is placed (a visibility:hidden item cannot take focus)
  useEffect(() => { if (open && pos && pending.current !== null) { focusAt(pending.current); pending.current = null; } });
  useEffect(() => {
    if (!open) return;
    const on = () => place();
    window.addEventListener('resize', on);
    window.addEventListener('scroll', on, true);
    return () => { window.removeEventListener('resize', on); window.removeEventListener('scroll', on, true); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // click / tap outside closes
  useEffect(() => {
    if (!open) return;
    const on = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !btn.current?.contains(t)) setOpen(false);
    };
    document.addEventListener('pointerdown', on, true);
    return () => document.removeEventListener('pointerdown', on, true);
  }, [open]);

  const onBtnKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); openAt('first'); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); openAt('last'); }
    else if (e.key === 'Escape' && open) { e.preventDefault(); e.stopPropagation(); close(); }
  };
  const onMenuKey = (e: KeyboardEvent) => {
    const xs = items();
    const i = xs.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); focusAt(i + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusAt(i - 1); }
    else if (e.key === 'Home') { e.preventDefault(); focusAt(0); }
    else if (e.key === 'End') { e.preventDefault(); focusAt(-1); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); } // not Details / card Esc
    else if (e.key === 'Tab') { e.preventDefault(); close(); } // the portal sits at the end of <body>: back to the button
  };
  const onShare = async () => {
    close();
    const r = await share(shareWithLang(shareUrl, l), title);
    if (r === 'copied') setToast(t('export.copied'));
    else if (r === 'failed') setToast(t('export.copyFailed'));
  };

  return (
    <div className={`export${up ? ' up' : ''}`}>
      <button ref={btn} type="button" className="btn-ghost export-btn" aria-haspopup="menu" aria-expanded={open} aria-controls={`${id}-menu`}
        onClick={() => (open ? close() : openAt('first'))} onKeyDown={onBtnKey} data-testid="export-btn">
        {t('export.button')} <span aria-hidden="true">▾</span>
      </button>
      {/* item 22: what the downloads contain (a tip button cannot live inside a menuitem) */}
      <Hint k="reportJson" side={up ? 'above' : 'below'} />
      {createPortal(
      <ul ref={menu} id={`${id}-menu`} role="menu" aria-label={t('export.button')} className="export-menu" hidden={!open} onKeyDown={onMenuKey} data-testid="export-menu"
        style={{ position: 'fixed', ...(pos ?? { left: 0, top: 0, visibility: 'hidden' }) }}>
        {ORDER.map((f) => {
          const url = canDownload ? exportUrl(reportId!, f, served, l) : null;
          const plainJson = f === 'json' && !served.has('json');
          return (
            <li key={f} role="none">
              {url ? (
                <a role="menuitem" tabIndex={-1} href={url} download={plainJson ? undefined : ''} target={plainJson ? '_blank' : undefined}
                  rel="noreferrer" data-format={f} onClick={() => close(false)}>{LABEL[f]}</a>
              ) : (
                <span role="menuitem" tabIndex={-1} aria-disabled="true" data-format={f} title={demo ? t('export.demoTitle') : t('export.soonTitle')}>{LABEL[f]}<span className="xs export-soon">{t('export.soon')}</span></span>
              )}
            </li>
          );
        })}
        <li role="separator" className="export-sep" />
        <li role="none"><button type="button" role="menuitem" tabIndex={-1} onClick={() => void onShare()} data-testid="export-share">{t('export.share')}</button></li>
      </ul>, document.body)}
      {reportId && <span className="sr-only">{t('export.reportId', { id: reportId })}</span>}
      <div className="toast" role="status" aria-live="polite" data-testid="toast">{toast}</div>
    </div>
  );
}
