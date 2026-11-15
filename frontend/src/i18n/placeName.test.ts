import { nameEn, placeNameEn, romanize } from './placeName';

describe('place names in English (KMU 2010, same rules as backend place_name_en)', () => {
  it.each([
    ['Київ', 'Kyiv'], ['Харків', 'Kharkiv'], ['Одеса', 'Odesa'], ['Запоріжжя', 'Zaporizhzhia'], ['Львів', 'Lviv'],
    ['Позняки', 'Pozniaky'], ['Згурівка', 'Zghurivka'], ['Яготин', 'Yahotyn'], ['Їжакевич', 'Yizhakevych'],
    ['Йосипівка', 'Yosypivka'], ['Знам’янка', 'Znamianka'], ['Юрій', 'Yurii'], ['Соломʼянський', 'Solomianskyi'],
  ])('%s → %s', (uk, en) => expect(romanize(uk)).toBe(en));

  it('translates the generic words and keeps parentheses, units and Latin', () => {
    expect(placeNameEn('Позняки (≈1 км)')).toBe('Pozniaky (≈1 km)');
    expect(placeNameEn('Увесь Київ')).toBe('All of Kyiv');
    expect(placeNameEn('Деснянський район (Київ)')).toBe('Desnianskyi District (Kyiv)');
    expect(placeNameEn('Your area')).toBe('Your area');
  });

  it('prefers the API name_en', () => {
    expect(nameEn('Позняки', 'Pozniaky (API)')).toBe('Pozniaky (API)');
    expect(nameEn('Позняки', null)).toBe('Pozniaky');
  });
});
