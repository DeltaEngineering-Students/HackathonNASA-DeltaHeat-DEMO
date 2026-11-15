/**
 * Chat-panel helpers over the `analyst.*` keys (src/i18n/parts/chat.{en,uk}.ts, merged into t()/useT() by
 * parts/index.ts — I18N.md §5.1, §7).
 */
import { getLocale, tr, type Locale, type MsgKey } from '../i18n';
import { chatEn } from '../i18n/parts/chat.en';

export type ChatKey = keyof typeof chatEn & MsgKey;
export const isChatKey = (k: string | undefined): k is ChatKey => !!k && k in chatEn;

/** Backend error code (503 / 429 bodies, SSE `error`) → text; unknown codes get the generic one. */
export const errorText = (code: string | undefined, l: Locale = getLocale()): string => {
  const k = `analyst.error.${code ?? ''}`;
  return tr(l, (isChatKey(k) ? k : 'analyst.error.unknown') as 'analyst.error.unknown');
};

/** Step id used by the panel for the validator step (not a backend tool). */
export const CHECK_STEP = 'перевірка чисел';

/** Human label for a backend tool id; ids stay in `title`. */
export const toolLabel = (id: string, l: Locale = getLocale()): string => {
  const k = id === CHECK_STEP ? 'analyst.tool.check' : `analyst.tool.${id}`;
  return tr(l, (isChatKey(k) ? k : 'analyst.workingWithData') as 'analyst.workingWithData');
};

/** Text of a step summary / warning stored on a turn: a chat key (the panel's own text) or plain backend text. */
export const say = (s: string, l: Locale = getLocale()): string => (isChatKey(s) ? tr(l, s as 'analyst.workingWithData') : s);

/** Tools previewed while the analyst is not connected (decision #19). */
export const PLANNED_TOOLS = ['get_report', 'list_scenes', 'get_weather', 'web_search', 'create_report', 'set_map_view'] as const;
export const SUGGESTION_KEYS = ['analyst.suggest1', 'analyst.suggest2', 'analyst.suggest3'] as const;
