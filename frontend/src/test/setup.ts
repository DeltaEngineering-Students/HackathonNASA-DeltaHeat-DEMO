import '@testing-library/jest-dom/vitest';
// I18N.md §7: unit tests written for the Ukrainian copy run in Ukrainian; English tests set the locale themselves
// (`setLocale('en')` / `tr('en', …)`). Each test file starts in Ukrainian.
import { initLocale } from '../i18n/locale';
initLocale('?lang=uk');
