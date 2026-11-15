import { adaptPlaces } from './adapt';

// item 32: /api/places?lang=en adds English siblings; the adapter keeps them for Search (Ukrainian fields unchanged)
describe('adaptPlaces — English siblings', () => {
  it('keeps name_en / note_en and derives subtitle_en from the city', () => {
    const [p] = adaptPlaces({ presets: [{ id: 'kyiv-pozniaky', name: 'Позняки (≈1 км)', kind: 'demo_zone', city: 'kyiv',
      note_uk: 'Щільні багатоповерхівки', name_en: 'Pozniaky (≈1 km)', note_en: 'Dense high-rise blocks' }] });
    expect(p).toMatchObject({ name: 'Позняки (≈1 км)', subtitle: 'Київ', note_uk: 'Щільні багатоповерхівки',
      name_en: 'Pozniaky (≈1 km)', subtitle_en: 'Kyiv', note_en: 'Dense high-rise blocks' });
  });

  it('oblast_en for cities without `city`; nothing added when the backend sends no English', () => {
    const [a, b] = adaptPlaces({ presets: [
      { id: 'odesa', name: 'Одеса', kind: 'city', oblast: 'Одеська область', oblast_en: 'Odesa Oblast', name_en: 'Odesa' },
      { id: 'x', name: 'Ікс', kind: 'district' },
    ] });
    expect(a).toMatchObject({ subtitle: 'Одеська область', subtitle_en: 'Odesa Oblast', name_en: 'Odesa' });
    expect(b).not.toHaveProperty('name_en');
    expect(b).not.toHaveProperty('subtitle_en');
  });
});
