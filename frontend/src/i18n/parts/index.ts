// Dictionary parts per wiring slot (I18N.md §7). Add a slot here once; index.ts merges them into en / uk.
import { mapEn } from './map.en';
import { mapUk } from './map.uk';
import { detailsEn } from './details.en';
import { detailsUk } from './details.uk';
import { searchEn } from './search.en';
import { searchUk } from './search.uk';
import { chatEn } from './chat.en';
import { chatUk } from './chat.uk';
import { polishEn } from './polish.en';
import { polishUk } from './polish.uk';

export const PARTS_EN = { map: mapEn, details: detailsEn, search: searchEn, chat: chatEn, polish: polishEn } as const;
export const PARTS_UK = { map: mapUk, details: detailsUk, search: searchUk, chat: chatUk, polish: polishUk } as const;
