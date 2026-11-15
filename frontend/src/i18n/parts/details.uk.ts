// Ukrainian twin of details.en.ts: the current wording, verbatim (the Ukrainian UI must not change).
import type { UkOf } from '../messages';
import type { detailsEn } from './details.en';

export const detailsUk: UkOf<typeof detailsEn> = {
  'details.ringKm': '{a}–{b} км',
  'details.ringKmOne': '{a} км',
  'details.trendRow': '{v} °C / 10 р. · {word}',
  'details.trendShort': '{v} °C/10 р. ({word})',
  'details.perDecadeUnit': '°C / 10 р.',
  'details.caveatsAria': 'Застереження',
  'details.reportId': ' id {id}',
};
