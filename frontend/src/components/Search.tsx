import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import type { PlaceHit } from '../api/types';
import { searchPlaces } from '../api/client';
import { SearchIcon, Close } from './icons';
import { useLocale, useT, type Locale } from '../i18n';
import { ukIfCyrillic } from './Rich';

/** item 32: a hit's text in the UI language — `<field>_en` when the API sends it (?lang=en), else the Ukrainian one. */
export function hitText(h: PlaceHit, field: 'name' | 'subtitle' | 'note', l: Locale): string | undefined {
  const x = h as unknown as Record<string, string | null | undefined>;
  const uk = field === 'note' ? x.note_uk : x[field];
  return (l === 'en' ? x[`${field}_en`] || undefined : undefined) ?? uk ?? undefined;
}

/** Curated examples shown when the search box is empty (only those present in /api/meta). */
export const EXAMPLE_IDS = ['demo-nyzhni-sady', 'demo-desnianske', 'kyiv-pozniaky', 'demo-holosiivskyi-lis', 'kyiv-obolon', 'kyiv-teremky', 'kyiv-hatne', 'kyiv', 'kharkiv-saltivka', 'kharkiv', 'lviv-sykhiv', 'lviv'];

/** Split hits into preset examples and geocoder results (presets first). */
export function groupHits(hits: PlaceHit[]): { examples: PlaceHit[]; places: PlaceHit[] } {
  const examples = hits.filter((h) => h.kind !== 'geocoder');
  const places = hits.filter((h) => h.kind === 'geocoder');
  return { examples, places };
}

export function Search({ examples, onSelect }: { examples: PlaceHit[]; onSelect: (h: PlaceHit) => void }) {
  const t = useT();
  const l = useLocale();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  // Results belong to both a query and UI locale; never display or select an older-language response.
  const [res, setRes] = useState<{ term: string; locale: Locale; hits: PlaceHit[]; failed: boolean } | null>(null);
  const [active, setActive] = useState(-1);
  const pendingEnter = useRef(false);
  const priorLocale = useRef(l);
  const reqId = useRef(0);
  const id = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  // debounced query
  const term = q.trim();
  const querying = term.length >= 2;
  useEffect(() => {
    setActive(-1);
    if (priorLocale.current !== l) pendingEnter.current = false;
    priorLocale.current = l;
    const rid = ++reqId.current;
    if (!querying) { pendingEnter.current = false; return; }
    const ac = new AbortController();
    const timer = setTimeout(() => {
      searchPlaces(term, ac.signal, l)
        .then((h) => { if (!ac.signal.aborted && rid === reqId.current) setRes({ term, locale: l, hits: h, failed: false }); })
        .catch((e: unknown) => { if ((e as Error).name !== 'AbortError' && !ac.signal.aborted && rid === reqId.current) setRes({ term, locale: l, hits: [], failed: true }); });
    }, 220);
    return () => { clearTimeout(timer); ac.abort(); };
  }, [term, querying, l]);

  const hits = querying && res?.term === term && res.locale === l ? res.hits : null;
  const loading = querying && !hits;
  const failed = !!hits && !!res?.failed;
  const groups = useMemo(() => (querying ? groupHits(hits ?? []) : { examples, places: [] }), [querying, hits, examples]);
  const flat = [...groups.examples, ...groups.places];

  useEffect(() => {
    if (hits && pendingEnter.current) {
      pendingEnter.current = false;
      const h = flat[0];
      if (h) choose(h);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hits]);

  // close on outside click
  useEffect(() => {
    const on = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', on);
    return () => document.removeEventListener('mousedown', on);
  }, []);

  const choose = (h: PlaceHit) => {
    pendingEnter.current = false;
    setOpen(false);
    setQ('');
    input.current?.blur();
    onSelect(h);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(flat.length - 1, a + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === 'Enter') {
      if (loading) { e.preventDefault(); pendingEnter.current = true; return; } // pick the first result once it arrives
      // nothing highlighted while typing → Enter takes the first result for the current text
      const h = flat[active] ?? (querying ? flat[0] : undefined);
      if (open && h) { e.preventDefault(); choose(h); }
    }
    else if (e.key === 'Escape') { if (open) { e.preventDefault(); setOpen(false); } else setQ(''); }
    else if (e.key === 'Home' && open) { setActive(0); }
    else if (e.key === 'End' && open) { setActive(flat.length - 1); }
  };

  const optId = (i: number) => `${id}-opt-${i}`;
  let i = -1;
  const renderGroup = (title: string, list: PlaceHit[]) =>
    list.length > 0 && (
      <li role="presentation" key={title}>
        <div className="dd-group" id={`${id}-${title}`}>{title}</div>
        <ul role="group" aria-labelledby={`${id}-${title}`} style={{ listStyle: 'none' }}>
          {list.map((h) => {
            i += 1;
            const k = i;
            const name = hitText(h, 'name', l) ?? h.name, note = hitText(h, 'note', l), sub = hitText(h, 'subtitle', l);
            return (
              <li key={h.id} id={optId(k)} role="option" aria-selected={k === active} className={`dd-item${note ? ' has-note' : ''}`}
                onMouseDown={(e) => e.preventDefault()} onClick={() => choose(h)} onMouseEnter={() => setActive(k)}>
                <span><span className="dd-name" lang={ukIfCyrillic(l, name)}>{name}</span>{note && <span className="dd-note" lang={ukIfCyrillic(l, note)}>{note}</span>}</span>
                {sub && <span className="dd-sub" lang={ukIfCyrillic(l, sub)}>{sub}</span>}
              </li>
            );
          })}
        </ul>
      </li>
    );

  return (
    <div className="search" ref={wrap}>
      <div className="search-box">
        <SearchIcon />
        <input
          ref={input}
          id="search"
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={open && flat[active] ? optId(active) : undefined}
          aria-label={t('search.aria')}
          placeholder={t('search.placeholder')}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          autoComplete="off"
          spellCheck={false}
        />
        {q && <button type="button" className="search-clear" aria-label={t('search.clear')} onClick={() => { setQ(''); input.current?.focus(); }}><Close /></button>}
      </div>
      {open && (
        <ul className="dropdown" id={`${id}-list`} role="listbox" aria-label={t('search.results')}>
          {renderGroup(hits ? t('search.groupDistricts') : t('search.groupExamples'), groups.examples)}
          {renderGroup(t('search.groupPlaces'), groups.places)}
          {hits && flat.length === 0 && (
            <li className="dd-empty" role="presentation">{failed ? t('search.failed') : t('search.nothing')}</li>
          )}
          {loading && <li className="dd-empty" role="presentation" aria-live="polite" data-testid="search-pending">{t('search.pending')}</li>}
        </ul>
      )}
    </div>
  );
}
