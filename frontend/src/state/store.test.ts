import { defaultYear, errorMessage, initialState, reducer, type AppState } from './store';
import { META, REPORTS } from '../fixtures';

const sel = { kind: 'preset' as const, id: 'kyiv-obolon', name: 'Оболонь' };

describe('app reducer', () => {
  it('picks the last year from meta and keeps a valid URL year', () => {
    expect(reducer(initialState, { type: 'meta', meta: META, demo: true }).year).toBe(2025);
    const withYear = { ...initialState, year: 2019 };
    expect(reducer(withYear, { type: 'meta', meta: META, demo: false }).year).toBe(2019);
    expect(reducer({ ...initialState, year: 1990 }, { type: 'meta', meta: META, demo: false }).year).toBe(2025);
  });
  it('ignores stale analysis responses', () => {
    let s: AppState = reducer(initialState, { type: 'select', seq: 1, selection: sel });
    s = reducer(s, { type: 'select', seq: 2, selection: { ...sel, id: 'kyiv-teremky', name: 'Теремки' } });
    s = reducer(s, { type: 'reportOk', seq: 1, report: REPORTS['kyiv-obolon']! });
    expect(s.report.status).toBe('loading');
    s = reducer(s, { type: 'reportOk', seq: 2, report: REPORTS['kyiv-teremky']! });
    expect(s.report.status).toBe('ready');
  });
  it('routes reports without any valid gap to the empty state', () => {
    const r = structuredClone(REPORTS['kyiv-obolon']!);
    r.gap_summary.mean = null;
    r.series.forEach((p) => (p.gap = null));
    const s = reducer(reducer(initialState, { type: 'select', seq: 1, selection: sel }), { type: 'reportOk', seq: 1, report: r });
    expect(s.report.status).toBe('empty');
  });
  it('selecting a zone leaves draw mode and clears draw errors', () => {
    let s = reducer(initialState, { type: 'draw', mode: 'polygon' });
    s = reducer(s, { type: 'drawError', message: 'x' });
    expect(s.draw).toBe('polygon');
    s = reducer(s, { type: 'select', seq: 1, selection: sel });
    expect(s.draw).toBeNull();
    expect(s.drawError).toBeNull();
  });
  it('maps errors to friendly messages', () => {
    expect(errorMessage(422, 'insufficient_data')).toMatch(/замало/);
    expect(errorMessage(503, undefined)).toMatch(/недоступний/);
    expect(errorMessage(undefined, undefined)).toMatch(/з’єднання/);
  });
});

describe('reducer: QA fixes', () => {
  it('drops an unknown layer from the URL once meta arrives (QA-19)', () => {
    expect(reducer({ ...initialState, layer: 'nope' }, { type: 'meta', meta: META, demo: false }).layer).toBe('gap');
    expect(reducer({ ...initialState, layer: 'ndvi' }, { type: 'meta', meta: META, demo: false }).layer).toBe('ndvi');
  });
  it('meta retry clears the error; rename only for the current request', () => {
    const e = reducer(initialState, { type: 'metaError', message: 'x' });
    expect(reducer(e, { type: 'metaRetry' }).metaError).toBeNull();
    let s = reducer(initialState, { type: 'select', seq: 3, selection: { ...sel, name: '' } });
    expect(reducer(s, { type: 'rename', seq: 2, name: 'Старе' }).selection).toMatchObject({ name: '' });
    s = reducer(s, { type: 'rename', seq: 3, name: 'Хрещатик' });
    expect(s.selection).toMatchObject({ name: 'Хрещатик' });
  });
});

describe('default map year (QA-UX R4-6)', () => {
  const r = REPORTS['kyiv-pozniaky']!;
  const years = META.years;
  const latest = years[years.length - 1]!;
  const st = (year: number | null) => ({ ...initialState, meta: META, year }) as AppState;
  const excl = { ...r, series: r.series.map((x) => (x.year === latest ? { ...x, excluded: 'too_few_scenes', gap: null, zone_lst: null } : x)) };
  it('moves off the latest summer when the report excludes it', () => {
    const lastValid = [...excl.series].reverse().find((x) => x.year !== latest && !x.excluded)!.year;
    expect(defaultYear(st(latest), excl)).toBe(lastValid);
  });
  it('keeps a year the user picked, and the latest when it has data', () => {
    expect(defaultYear(st(2016), excl)).toBe(2016);
    expect(defaultYear(st(latest), r)).toBe(latest);
  });
});
