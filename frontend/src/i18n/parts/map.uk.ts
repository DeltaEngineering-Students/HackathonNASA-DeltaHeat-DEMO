// Slot «map» Ukrainian keys: the same keys and {placeholders} as map.en.ts (typed).
import type { UkOf } from '../messages';
import type { mapEn } from './map.en';

export const mapUk: UkOf<typeof mapEn> = {
  'map.refNone': 'Контур ліс-еталону для цієї ділянки поки недоступний.',
  'map.satCaption': 'Супутник: Esri World Imagery, версія архіву {version} (дата зйомки може бути ранішою)',
  'map.satCaptionEox': 'Супутник: Sentinel‑2, {year}',
  /** short on-map credit of the occupied-territories overlay (the full source is in Details) */
  'map.occAttr': 'Окуповані території: Мінрозвитку №376',
  'map.satNearest': '(найближча доступна версія)',
  'map.satNearestEox': '(найближчий доступний рік)',
  /** {date} = «липня 2024» (родовий відмінок) */
  'map.satCaptured': 'Супутник: Esri World Imagery, знімок {date}',
  'map.satNearestCapture': '(найближчий доступний)',
  'map.satZoomIn': '· наблизьте, щоб побачити',
};
