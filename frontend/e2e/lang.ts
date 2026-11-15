// Item 32: the app's default language is English (src/i18n/locale.ts DEFAULT_LOCALE). The existing specs assert the
// Ukrainian copy, so every context starts with the stored choice «uk» — exactly what a user who pressed УКР has.
// i18n.spec.ts opts out (empty storage) to test the real first visit.
export const LANG_KEY = 'uhd-lang';
export const ukState = (baseURL: string) => ({
  cookies: [],
  origins: [{ origin: new URL(baseURL).origin, localStorage: [{ name: LANG_KEY, value: 'uk' }] }],
});
