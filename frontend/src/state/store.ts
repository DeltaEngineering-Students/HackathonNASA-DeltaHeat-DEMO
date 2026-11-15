import type { Polygon } from 'geojson';
import type { Meta, Report, ZoneGeometry } from '../api/types';
import { isCounted, isEmptyReport } from '../lib/verdict';
import type { Panel } from '../lib/url';
import { getLocale } from '../i18n/locale';
import { tr } from '../i18n';

export type Selection =
  | { kind: 'preset'; id: string; name: string; name_en?: string; subtitle?: string; cityId?: string }
  | { kind: 'drawn'; geometry: Polygon; areaKm2: number };

export type ReportState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; report: Report }
  | { status: 'empty'; report: Report }
  | { status: 'error'; message: string; code?: string };

export type DrawMode = null | 'polygon' | 'circle';

export interface AppState {
  meta: Meta | null;
  metaError: string | null;
  demo: boolean;
  selection: Selection | null;
  geometry: ZoneGeometry | null;
  report: ReportState;
  /** Id of the latest analysis request; responses for older ids are ignored. */
  requestSeq: number;
  year: number | null;
  layer: string;
  panel: Panel;
  chatOpen: boolean;
  draw: DrawMode;
  drawError: string | null;
}

export const initialState: AppState = {
  meta: null,
  metaError: null,
  demo: false,
  selection: null,
  geometry: null,
  report: { status: 'idle' },
  requestSeq: 0,
  year: null,
  layer: 'gap',
  panel: 'card',
  chatOpen: false,
  draw: null,
  drawError: null,
};

export type Action =
  | { type: 'meta'; meta: Meta; demo: boolean }
  | { type: 'metaError'; message: string }
  | { type: 'metaRetry' }
  | { type: 'rename'; seq: number; name: string; name_en?: string }
  | { type: 'select'; seq: number; selection: Selection; geometry?: ZoneGeometry | null }
  | { type: 'geometry'; geometry: ZoneGeometry }
  | { type: 'reportOk'; seq: number; report: Report }
  | { type: 'reportError'; seq: number; message: string; code?: string }
  | { type: 'retry'; seq: number }
  | { type: 'year'; year: number }
  | { type: 'layer'; layer: string }
  | { type: 'panel'; panel: Panel }
  | { type: 'chat'; open: boolean }
  | { type: 'draw'; mode: DrawMode }
  | { type: 'drawError'; message: string | null };

export function reducer(s: AppState, a: Action): AppState {
  switch (a.type) {
    case 'meta': {
      const years = a.meta.years;
      const year = s.year && years.includes(s.year) ? s.year : years[years.length - 1] ?? null;
      const layer = a.meta.layers.some((l) => l.id === s.layer) ? s.layer : 'gap';
      return { ...s, meta: a.meta, demo: a.demo, year, layer, metaError: null };
    }
    case 'metaError':
      return { ...s, metaError: a.message };
    case 'metaRetry':
      return { ...s, metaError: null };
    case 'rename':
      if (a.seq !== s.requestSeq || s.selection?.kind !== 'preset') return s;
      return { ...s, selection: { ...s.selection, name: a.name, name_en: a.name_en ?? s.selection.name_en } };
    case 'select':
      return {
        ...s,
        selection: a.selection,
        geometry: a.geometry ?? (a.selection.kind === 'drawn' ? a.selection.geometry : null),
        report: { status: 'loading' },
        requestSeq: a.seq,
        draw: null,
        drawError: null,
      };
    case 'geometry':
      return { ...s, geometry: a.geometry };
    case 'retry':
      return { ...s, report: { status: 'loading' }, requestSeq: a.seq };
    case 'reportOk':
      if (a.seq !== s.requestSeq) return s;
      return { ...s, year: defaultYear(s, a.report), report: isEmptyReport(a.report) ? { status: 'empty', report: a.report } : { status: 'ready', report: a.report } };
    case 'reportError':
      if (a.seq !== s.requestSeq) return s;
      return { ...s, report: { status: 'error', message: a.message, code: a.code } };
    case 'year':
      return { ...s, year: a.year };
    case 'layer':
      return { ...s, layer: a.layer };
    case 'panel':
      return { ...s, panel: a.panel };
    case 'chat':
      return { ...s, chatOpen: a.open };
    case 'draw':
      return { ...s, draw: a.mode, drawError: null };
    case 'drawError':
      return { ...s, drawError: a.message };
    default:
      return s;
  }
}

/**
 * QA-UX R4-6: when the map is on the default (latest) year and that summer is excluded in the new report, show the last
 * summer with data instead — the first impression must not be «немає даних». A year the user picked is kept.
 */
export function defaultYear(s: AppState, r: Report): number | null {
  const years = s.meta?.years ?? [];
  const latest = years[years.length - 1];
  if (s.year == null || s.year !== latest) return s.year;
  const row = r.series.find((x) => x.year === s.year);
  if (!row || isCounted(row)) return s.year;
  const last = [...r.series].reverse().find((x) => isCounted(x) && years.includes(x.year));
  return last?.year ?? s.year;
}

/** Human message for an analysis failure. */
export function errorMessage(status: number | undefined, code: string | undefined): string {
  if (getLocale() === 'en') {
    if (code === 'insufficient_data' || code === 'too_small') return tr('en', 'error.insufficientData');
    if (code === 'outside_coverage') return tr('en', 'error.outsideCoverage');
    if (status === 422) return tr('en', 'error.rejected');
    if (status && status >= 500) return tr('en', 'error.serverDown');
    return tr('en', 'error.network');
  }
  if (code === 'insufficient_data' || code === 'too_small')
    return 'На цій ділянці замало забудови або чистих знімків, щоб чесно порахувати розрив. Спробуйте більшу ділянку.';
  if (code === 'outside_coverage') return 'Ця територія поза межами наших даних (Україна, літні сезони 2013–2025).';
  if (status === 422) return 'Сервер не прийняв цю ділянку. Перевірте контур і спробуйте ще раз.';
  if (status && status >= 500) return 'Сервер аналізу зараз недоступний. Спробуйте за хвилину.';
  return 'Не вдалося отримати аналіз. Перевірте з’єднання і спробуйте ще раз.';
}
