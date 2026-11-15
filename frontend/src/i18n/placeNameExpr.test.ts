import { createExpression, latest } from '@maplibre/maplibre-gl-style-spec';
import { describe, expect, it } from 'vitest';
import { romanize } from './placeName';
import { basemapNameEn, romanizeExpr } from './placeNameExpr';

const textField = latest.layout_symbol['text-field'] as unknown as Parameters<typeof createExpression>[1];
function evaluator(expr: unknown) {
  const r = createExpression(expr, textField);
  if (r.result !== 'success') throw new Error(JSON.stringify(r.value));
  return (properties: Record<string, string>) =>
    String(r.value.evaluate({ zoom: 14 }, { type: 1, properties, geometry: [] } as never));
}

describe('romanizeExpr (KMU 2010 as a MapLibre expression)', () => {
  const ev = evaluator(romanizeExpr(['get', 'name']));
  it('matches romanize() for Ukrainian names', () => {
    for (const s of ['Київ', 'Харків', 'Запоріжжя', 'Згурівка', 'Юрій', 'Яготин', 'Їжакевича', "Лук'яненка", 'Подвір’я', 'Євгена Коновальця',
      'Щастя', 'Гайова', 'Новосільська', 'Богдана Хмельницького', 'ПЕРЕМОГИ', 'Біла Церква', 'вул. 8-го Березня', 'Kyiv']) {
      expect(ev({ name: s })).toBe(romanize(s));
    }
  });
  it('leaves no Cyrillic, Russian letters included; very long names end in «…»', () => {
    expect(ev({ name: 'Ленина Ёлка Ъ ы э' })).not.toMatch(/[Ѐ-ӿ]/);
    expect(evaluator(romanizeExpr(['get', 'name'], 4))({ name: 'Шевченка' })).toBe('Shevch…');
  });
});

describe('basemapNameEn (English basemap labels)', () => {
  const ev = evaluator(basemapNameEn());
  it('OSM name:en wins', () => {
    expect(ev({ name: 'Зелена вулиця', 'name:en': 'Zelena Street', 'name:latin': 'Zelena Street', 'name:uk': 'Зелена вулиця' })).toBe('Zelena Street');
  });
  it('never the Polish name:latin; the Ukrainian name in KMU Latin with the street word translated', () => {
    expect(ev({ name: 'Новосільська вулиця', 'name:latin': 'ulica Nowosielska', 'name:uk': 'Новосільська вулиця' })).toBe('Novosilska Street');
    expect(ev({ name: 'вулиця Богдана Хмельницького', 'name:latin': 'ulica Bohdana Chmielnickiego', 'name:uk': 'вулиця Богдана Хмельницького' }))
      .toBe('Bohdana Khmelnytskoho Street');
    expect(ev({ name: 'вулиця Щастя' })).toBe('Shchastia Street');
    expect(ev({ name: 'провулок Тихий' })).toBe('Tykhyi Lane');
    expect(ev({ name: 'Алея Героя' })).toBe('Heroia Alley');
    expect(ev({ name: 'Крюківщина', 'name:uk': 'Крюківщина' })).toBe('Kriukivshchyna');
  });
  it('a name that is only the street word is transliterated, not emptied', () => {
    expect(ev({ name: 'Вулиця' })).toBe('Vulytsia');
  });
});
