// 2e-map helpers. Keys live in i18n/parts/map.*.ts (merged into t()).
import type { Locale } from '../i18n/locale';

/** «50 %» in Ukrainian (as today, plain space), «50%» in English (I18N.md §4) */
export const pctUi = (x: number, l: Locale) => `${Math.round(x * 100)}${l === 'en' ? '' : ' '}%`;
