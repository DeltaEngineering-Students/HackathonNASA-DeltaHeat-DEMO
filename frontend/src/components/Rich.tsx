// Renders dictionary rich text (I18N.md §5.1): <glossaryKey>…</glossaryKey> → <Term k>, <h> → heat span, <b> → bold.
import { Fragment, type ReactNode } from 'react';
import { segments } from '../i18n';
import { GLOSSARY, type GlossaryKey } from '../lib/glossary';
import { Term } from './Hint';

export function Rich({ text, termClass }: { text: string; termClass?: Partial<Record<GlossaryKey, string>> }) {
  return <>{segments(text).map((s, i) => {
    let node: ReactNode = s.text;
    for (const tag of [...s.tags].reverse()) {
      if (tag === 'h') node = <span className="h">{node}</span>;
      else if (tag === 'b') node = <b style={{ color: 'var(--ink)' }}>{node}</b>;
      else if (tag in GLOSSARY) node = <Term k={tag as GlossaryKey} className={termClass?.[tag as GlossaryKey]}>{node}</Term>;
    }
    return <Fragment key={i}>{node}</Fragment>;
  })}</>;
}

/** lang="uk" on Ukrainian text shown in the English UI (place names, server texts without *_en). */
export const ukIfCyrillic = (l: string, s: string | null | undefined): 'uk' | undefined =>
  l === 'en' && s && /[А-Яа-яІіЇїЄєҐґ]/.test(s) ? 'uk' : undefined;
