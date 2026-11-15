import { parseUrl, toSearch, zoneKey, DEFAULT_ZONE } from './url';

describe('url state', () => {
  it('defaults to Pozniaky card', () => {
    expect(parseUrl('')).toMatchObject({ zone: DEFAULT_ZONE, year: null, panel: 'card', area: null });
  });
  it('round-trips zone, year, layer and panel', () => {
    const s = parseUrl('?zone=kyiv-obolon&year=2019&layer=lst&view=details');
    expect(s).toMatchObject({ zone: 'kyiv-obolon', year: 2019, layer: 'lst', panel: 'details' });
    expect(toSearch(s)).toBe('?zone=kyiv-obolon&year=2019&layer=lst&view=details');
  });
  it('omits the default layer and keeps drawn areas', () => {
    const s = parseUrl('?area=30.5,50.4;30.52,50.4;30.52,50.42&year=2025');
    expect(s.zone).toBeNull();
    expect(s.area?.coordinates[0]?.length).toBe(4);
    expect(toSearch({ ...s, layer: 'gap' })).toBe('?area=30.50000,50.40000;30.52000,50.40000;30.52000,50.42000&year=2025');
  });
  it('ignores bad years', () => {
    expect(parseUrl('?year=abc').year).toBeNull();
  });
});

describe('zoneKey (history entries, QA-09)', () => {
  it('ignores year/layer/view and defaults to Позняки', () => {
    expect(zoneKey('?zone=kyiv-obolon&year=2018&view=details')).toBe(zoneKey('?zone=kyiv-obolon'));
    expect(zoneKey('')).toBe('zone:kyiv-pozniaky');
    expect(zoneKey('?area=1,2;3,4')).toBe('area:1,2;3,4');
  });
});
