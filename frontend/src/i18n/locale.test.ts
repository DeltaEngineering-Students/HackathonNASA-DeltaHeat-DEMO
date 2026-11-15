import { DEFAULT_LOCALE, detectLocale, getLocale, initLocale, localeFromSearch, setLocale, STORAGE_KEY, subscribeLocale, withLang } from './locale';

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, '', '/');
  initLocale('');
});

describe('locale', () => {
  it('a fresh browser gets DEFAULT_LOCALE (uk until the flip), whatever the browser language', () => {
    expect(['en', 'uk']).toContain(DEFAULT_LOCALE);
    expect(detectLocale('')).toBe(DEFAULT_LOCALE);
    expect(getLocale()).toBe(DEFAULT_LOCALE);
    expect(document.documentElement.lang).toBe(DEFAULT_LOCALE);
  });
  it('URL beats storage; storage beats the default', () => {
    const other = DEFAULT_LOCALE === 'en' ? 'uk' : 'en';
    localStorage.setItem(STORAGE_KEY, other);
    expect(detectLocale('')).toBe(other);
    expect(detectLocale(`?zone=kyiv-pozniaky&lang=${DEFAULT_LOCALE}`)).toBe(DEFAULT_LOCALE);
    localStorage.setItem(STORAGE_KEY, 'xx');
    expect(detectLocale('')).toBe(DEFAULT_LOCALE);
  });
  it('accepts uk / ua / uk-UA / EN and ignores junk', () => {
    expect(localeFromSearch('?lang=UA')).toBe('uk');
    expect(localeFromSearch('?lang=uk-UA')).toBe('uk');
    expect(localeFromSearch('?lang=EN')).toBe('en');
    expect(localeFromSearch('?lang=de')).toBeNull();
  });
  it('withLang: the non-default language in the URL, the default omitted unless explicit (share links)', () => {
    const other = DEFAULT_LOCALE === 'en' ? 'uk' : 'en';
    expect(withLang('?zone=a&year=2022', other)).toBe(`?zone=a&year=2022&lang=${other}`);
    expect(withLang(`?zone=a&lang=${other}`, DEFAULT_LOCALE)).toBe('?zone=a');
    expect(withLang('?zone=a', DEFAULT_LOCALE, true)).toBe(`?zone=a&lang=${DEFAULT_LOCALE}`);
    expect(withLang('', DEFAULT_LOCALE)).toBe('');
  });
  it('setLocale persists, updates <html lang>, the URL and subscribers', () => {
    history.replaceState(null, '', '/?zone=kyiv-obolon');
    const f = vi.fn();
    const off = subscribeLocale(f);
    const other = DEFAULT_LOCALE === 'en' ? 'uk' : 'en';
    setLocale(other);
    expect(getLocale()).toBe(other);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(other);
    expect(document.documentElement.lang).toBe(other);
    expect(location.search).toBe(`?zone=kyiv-obolon&lang=${other}`);
    expect(f).toHaveBeenCalledTimes(1);
    setLocale(DEFAULT_LOCALE);
    expect(location.search).toBe('?zone=kyiv-obolon');
    off();
  });
  it('survives blocked storage', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    const spy2 = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(detectLocale('')).toBe(DEFAULT_LOCALE);
    expect(() => setLocale('en')).not.toThrow();
    expect(getLocale()).toBe('en');
    spy.mockRestore(); spy2.mockRestore();
  });
});
