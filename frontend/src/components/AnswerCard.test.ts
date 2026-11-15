import { bigNumber, cardLead, emptyReason, eyebrowFor, shortName, splitName, zoneTitle } from './AnswerCard';
import { yearValue } from './BottomStrip';
import { toolLabel } from './ChatPanel';
import { REPORTS } from '../fixtures';
import type { Report } from '../api/types';
import { sendsPlaceId } from '../api/types';

const base = REPORTS['kyiv-pozniaky']!;

describe('card copy (QA-UX)', () => {
  it('C10: no double negative; near zero is «≈ 0°»', () => {
    expect(bigNumber(-1.24)).toEqual({ text: '1,2°', caption: 'прохолодніше за ліс', tone: 'cool' });
    expect(bigNumber(-0.2)).toMatchObject({ text: '≈ 0°', caption: 'майже як ліс' });
    expect(bigNumber(0.49).caption).toBe('майже як ліс');
    expect(bigNumber(11.4)).toMatchObject({ text: '+11,4°', caption: 'поверхня гарячіша за ліс' });
  });
  it('C3/C8: title without «(≈1 км)», capitalised; extent goes to the eyebrow', () => {
    expect(splitName('Позняки (≈1 км)')).toEqual({ name: 'Позняки', extent: 'коло ≈1\u00a0км' });
    expect(splitName('вулиця Драгоманова').name).toBe('Вулиця Драгоманова');
    expect(splitName('Нижні Сади (Осокорки)').name).toBe('Нижні Сади (Осокорки)');
    expect(zoneTitle({ kind: 'preset', id: 'kyiv-pozniaky', name: 'Позняки (≈1 км)' })).toBe('Позняки');
  });
  it('R3-7 eyebrow rule: Приклад / Район / Коло навколо адреси / Місто', () => {
    const sel = { kind: 'preset' as const, id: 'kyiv-pozniaky', name: 'Позняки (≈1 км)' };
    const r: Report = { ...base, zone: { ...base.zone, analysed: 'built' }, reference: { ...base.reference, city: 'Київ' } };
    expect(eyebrowFor(sel, r, 'demo_zone')).toBe('Приклад · Київ');
    expect(eyebrowFor({ ...sel, id: 'kyiv-obolon', name: 'Оболонь' }, r, 'district')).toBe('Район · Київ');
    expect(eyebrowFor({ ...sel, id: 'osm:W1', name: 'Хрещатик, 22 (≈1 км навколо)' }, r, 'geocoder_circle')).toBe('Коло ≈1\u00a0км навколо адреси · Київ');
    const derived: Report = { ...r, reference: { ...r.reference, city: '' } };
    // R3-6: a searched whole city is not «Навколо адреси»
    expect(eyebrowFor({ ...sel, id: 'osm:R1748539', name: 'Маріуполь' }, derived, 'geocoder')).toBe('Місто / населений пункт');
    expect(eyebrowFor({ kind: 'preset', id: 'kyiv', name: 'Київ', cityId: 'kyiv' }, r, 'city')).toBe('Вся забудова');
  });
  it('R3-8: the lead keeps the direction of a small gap', () => {
    const t = 'Поверхня тут влітку вдень майже така ж тепла, як ліс навколо Києва (різниця 0,2 °C), і за 13 літ цей розрив помітно не змінився (поки не значуще, p = 0,50).';
    expect(cardLead(t, 'Голосіївський ліс', -0.15)).toBe('Поверхня тут влітку вдень майже така ж тепла, як ліс навколо Києва (на 0,2\u00a0°C прохолодніша), і за 13 літ цей розрив помітно не змінився.');
    expect(cardLead(t, 'x', 0.04)).toContain('(різниця менша за 0,1\u00a0°C)');
  });
  it('R3-1/R3-9: short display names; raw ids are never titles', () => {
    expect(shortName('Котеджне містечко «Деснянське» (Троєщина)')).toBe('Деснянське (Троєщина)');
    expect(shortName('Нижні Сади (Осокорки)')).toBe('Нижні Сади (Осокорки)');
    expect(zoneTitle({ kind: 'preset', id: 'kharkiv-saltivka', name: 'kharkiv-saltivka' })).toBe('');
    expect(zoneTitle({ kind: 'preset', id: 'kharkiv-saltivka', name: 'Салтівка' })).toBe('Салтівка');
  });
  it('R3-4: empty state reason comes from the caveats', () => {
    const none: Report = { ...base, caveats: [{ code: 'no_lst_product', text_uk: 'x' }, { code: 'war_zone', text_uk: 'y' }] };
    expect(emptyReason(none)).toEqual({ lead: 'Тут немає супутникової температури поверхні для цієї місцевості (прогалина в продукті USGS).', hint: null });
    expect(emptyReason({ ...base, caveats: [] }).hint).toBe('Спробуйте більшу ділянку чи інший район.');
    expect(sendsPlaceId('kyiv-solomianskyi', 'district')).toBe(true);
    expect(sendsPlaceId('osm:R1017311', 'city')).toBe(true);
    expect(sendsPlaceId('osm:W173607149', 'geocoder_circle')).toBe(false);
    expect(sendsPlaceId('osm:R1748539', 'geocoder')).toBe(false);
    expect(sendsPlaceId(undefined)).toBe(false);
  });
  it('S1: selected year value in the strip', () => {
    const row = base.series.find((x) => x.gap != null)!;
    expect(yearValue('gap', row)).toMatch(/^[+−]\d+,\d °C на ділянці$/);
    expect(yearValue('gap', { ...row, gap: null })).toBeNull();
    expect(yearValue('dndvi', row)).toBeNull();
  });
  it('A2: tool ids are never shown raw', () => {
    expect(toolLabel('get_report')).toBe('перевіряє цифри звіту');
    expect(toolLabel('some_new_tool')).not.toMatch(/[a-z_]/);
  });
});

describe('card lead (sci-v3.3 text)', () => {
  it('drops the p aside, keeps both halves of the answer', () => {
    const t = 'Поверхня забудови влітку вдень у середньому на 11,4 °C гарячіша, ніж ліс навколо Києва, і за 12 літ цей розрив помітно не змінився (поки не значуще, p = 0,37). Зелені більшає.';
    expect(cardLead(t, 'Позняки')).toBe('Поверхня забудови влітку вдень у середньому на 11,4 °C гарячіша, ніж ліс навколо Києва, і за 12 літ цей розрив помітно не змінився.');
  });
});
