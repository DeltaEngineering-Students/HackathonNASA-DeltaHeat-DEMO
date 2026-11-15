// «EN | УКР» language switch in the header, next to the theme toggle (I18N.md §3). Each label in its own language.
import type { Locale } from '../i18n';
import { tr } from '../i18n';
import '../i18n/i18n.css';

export function LangSwitch({ lang, onChange, locales, labels }: {
  lang: Locale; onChange: (l: Locale) => void; locales: readonly Locale[]; labels: Record<Locale, string>;
}) {
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const i = locales.indexOf(lang);
    const next = locales[(i + (e.key === 'ArrowRight' ? 1 : locales.length - 1)) % locales.length]!;
    onChange(next);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-testid="lang-${next}"]`)?.focus());
  };
  return (
    <div className="seg seg-sm lang-switch" role="group" aria-label={tr(lang, 'app.langSwitch')} data-testid="lang-switch" onKeyDown={onKey}>
      {locales.map((l) => (
        <button key={l} type="button" lang={l} aria-pressed={l === lang} data-testid={`lang-${l}`}
          aria-label={tr(l, l === 'en' ? 'app.langToEn' : 'app.langToUk')} title={tr(l, l === 'en' ? 'app.langToEn' : 'app.langToUk')}
          tabIndex={l === lang ? 0 : -1} onClick={() => onChange(l)}>{labels[l]}</button>
      ))}
    </div>
  );
}
