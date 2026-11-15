// MAP-TASKS 12: the collapsible left card — the chevron on its edge and the compact pill it collapses into.
import { bigNumber } from './AnswerCard';
import { Chevron } from './icons';
import { tr, useLocale } from '../i18n';
import { ukIfCyrillic } from './Rich';

export const CARD_ID = 'answer-card';

/** Chevron on the card's right edge (expanded state). */
export function CollapseButton({ onCollapse }: { onCollapse: () => void }) {
  const l = useLocale();
  return (
    <button type="button" className="card-collapse" aria-expanded="true" aria-controls={CARD_ID} onClick={onCollapse}
      aria-label={tr(l, 'card.collapse')} title={tr(l, 'card.collapseTitle')} data-testid="card-collapse"><Chevron dir="left" /></button>
  );
}

/** Collapsed card: zone name, the big gap and «Розгорнути». */
export function CardPill({ name, mean, loading, onExpand }: { name: string; mean: number | null | undefined; loading: boolean; onExpand: () => void }) {
  const l = useLocale();
  const big = mean === undefined ? null : bigNumber(mean);
  return (
    <section className="card card-pill" id={CARD_ID} data-testid="card-pill" aria-label={tr(l, 'card.collapsedLabel', { name })}>
      <div className="pill-text">
        <b className="pill-name" title={name} lang={ukIfCyrillic(l, name)}>{name || tr(l, 'card.place')}</b>
        {loading ? <span className="pill-gap skel" style={{ width: 64, height: 26 }} /> : big && (
          <span className={`pill-gap big${big.tone === 'cool' ? ' cool' : ''}`} title={big.caption} data-testid="pill-gap">{big.text}</span>
        )}
      </div>
      <button type="button" className="btn-ghost pill-expand" aria-expanded="false" aria-controls={CARD_ID} onClick={onExpand}
        title={tr(l, 'card.expandTitle')} data-testid="card-expand">{tr(l, 'card.expand')}<Chevron dir="right" /></button>
    </section>
  );
}
