import { occupiedAttribution } from './attribution';

const F = [{ type: 'Feature', properties: {}, geometry: null }];
const UK = 'Мінрозвитку України (наказ № 376 від 28.02.2025, zakon.rada.gov.ua); © OpenStreetMap contributors';
const EN = 'Ministry of Development of Ukraine (order No. 376 of 28.02.2025, zakon.rada.gov.ua); © OpenStreetMap contributors';

describe('occupied overlay attribution', () => {
  it('reads the collection properties (API today), English when the API sent it', () => {
    const occ = { type: 'FeatureCollection', features: F, properties: { attribution: UK, attribution_en: EN } };
    expect(occupiedAttribution(occ, 'uk')).toBe(UK);
    expect(occupiedAttribution(occ, 'en')).toBe(EN);
  });
  it('English falls back to the Ukrainian credit; null / blank fields are skipped', () => {
    expect(occupiedAttribution({ type: 'FeatureCollection', features: F, properties: { attribution: UK, attribution_en: null } }, 'en')).toBe(UK);
    expect(occupiedAttribution({ type: 'FeatureCollection', features: F, properties: { attribution: '  ', source: 'Перелік ТОТ' } }, 'uk')).toBe('Перелік ТОТ');
  });
  it('older payloads: top-level attribution or source', () => {
    expect(occupiedAttribution({ type: 'FeatureCollection', features: F, attribution: UK }, 'uk')).toBe(UK);
    expect(occupiedAttribution({ type: 'FeatureCollection', features: F, source: 'Перелік ТОТ' }, 'en')).toBe('Перелік ТОТ');
  });
  it('nothing drawn → no credit', () => {
    expect(occupiedAttribution({ type: 'FeatureCollection', features: [], properties: { attribution: UK } }, 'uk')).toBeUndefined();
    expect(occupiedAttribution(null, 'uk')).toBeUndefined();
  });
});
