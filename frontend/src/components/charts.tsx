// Hand-written SVG charts (design F7). Colours come from CSS variables so both themes work.
import { useId, type KeyboardEvent } from 'react';
import type { SeriesPoint, Trend } from '../api/types';
import { fmt, fmtDeg } from '../lib/format';
import { excludedLabel, excludedText } from '../lib/verdict';
import { barsMetric, NDVI_NODATA, type BarsMetric } from '../lib/layers';
import { Hint } from './Hint';
import { useT } from '../i18n';

type Pt = [number, number];
const path = (pts: Pt[]) => 'M' + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L');

/** Split into runs of consecutive non-null points so missing years break the line. */
function runs<T>(items: T[], ok: (t: T) => boolean): T[][] {
  const out: T[][] = [];
  let cur: T[] = [];
  for (const it of items) {
    if (ok(it)) cur.push(it);
    else if (cur.length) { out.push(cur); cur = []; }
  }
  if (cur.length) out.push(cur);
  return out;
}

export function niceTicks(lo: number, hi: number, target = 3): number[] {
  const raw = (hi - lo) / target;
  const steps = [1, 2, 3, 5, 6, 10, 15, 20];
  const step = steps.find((s) => s >= raw) ?? 20;
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) ticks.push(t);
  return ticks;
}

/**
 * Direct label lines: drop a trailing parenthetical («Позняки (≈1 км)» → «Позняки»), then wrap words
 * into at most 2 lines of ~`n` characters (no ellipsis unless a single word is longer than the room).
 */
export function labelLines(s: string, n = 11): string[] {
  // long single words are hyphenated instead of being cut («Голосіївський» → «Голосіїв-» «ський»)
  const words = s.replace(/\s*\(.*\)\s*$/, '').split(/\s+/).filter(Boolean)
    .flatMap((w) => {
      if (w.length <= n) return [w];
      const k = /[ьʼ’']/.test(w[n - 1]!) ? n - 2 : n - 1; // never start the second part with «ь» or an apostrophe
      return [w.slice(0, k) + '-', w.slice(k)];
    });
  const lines: string[] = [];
  for (const w of words) {
    const last = lines[lines.length - 1];
    if (last !== undefined && !last.endsWith('-') && (last + ' ' + w).length <= n) lines[lines.length - 1] = last + ' ' + w;
    else lines.push(w);
  }
  const out = lines.slice(0, 2);
  if (lines.length > 2) out[1] = out[1] + '…';
  return out.map((l) => (l.length > n + 1 ? l.slice(0, n) + '…' : l));
}

/** Two lines: zone LST vs forest reference, with direct labels (card chart). */
export function LineChart({ series, zoneName, w = 384, h = 176 }: { series: SeriesPoint[]; zoneName: string; w?: number; h?: number }) {
  const t = useT();
  const padL = 34, padR = 100, padT = 10, padB = 26;
  const vals = series.flatMap((s) => [s.zone_lst, s.ref_lst]).filter((v): v is number => v != null);
  if (vals.length === 0 || series.length < 2) return null;
  const lo = Math.floor(Math.min(...vals) - 2);
  const hi = Math.ceil(Math.max(...vals) + 2);
  const n = series.length - 1;
  const X = (i: number) => padL + (i * (w - padL - padR)) / n;
  const Y = (t: number) => padT + ((hi - t) * (h - padT - padB)) / (hi - lo);
  const idx = series.map((s, i) => ({ ...s, i }));
  const zoneRuns = runs(idx, (s) => s.zone_lst != null);
  const refRuns = runs(idx, (s) => s.ref_lst != null);
  const bandRuns = runs(idx, (s) => s.zone_lst != null && s.ref_lst != null);
  const lastZ = [...idx].reverse().find((s) => s.zone_lst != null);
  const lastR = [...idx].reverse().find((s) => s.ref_lst != null);
  let yz = lastZ ? Y(lastZ.zone_lst!) : 0;
  let yr = lastR ? Y(lastR.ref_lst!) : 0;
  // direct labels: ~8,4 px per character at 14 px → 10 characters fit into the right margin
  const zl = labelLines(zoneName, 10);
  const rl = [t('chart.forestAround'), t('chart.theCity')];
  const hz = zl.length * 8, hr = rl.length * 8; // half-heights of the label blocks (16 px lines)
  const sep = hz + hr + 4; // label centres must be at least this far apart
  if (Math.abs(yz - yr) < sep) {
    const m = (yz + yr) / 2;
    const zAbove = yz <= yr;
    yz = zAbove ? m - sep / 2 : m + sep / 2;
    yr = zAbove ? m + sep / 2 : m - sep / 2;
  }
  // «розрив» goes where the band is widest (away from the ends), and only if it fits (QA-UX C16)
  const inner = bandRuns.flat().filter((x) => x.i > 0 && x.i < n);
  const widest = inner.reduce<(typeof inner)[number] | undefined>((b, x) => (!b || x.zone_lst! - x.ref_lst! > b.zone_lst! - b.ref_lst! ? x : b), undefined);
  // the label is ~50 px wide: the band must be clear at the neighbouring years too, or it sits on the line (QA-UX R3)
  const bandPx = (i: number) => {
    const x = series[i];
    return x && x.zone_lst != null && x.ref_lst != null ? Math.abs(Y(x.zone_lst) - Y(x.ref_lst)) : 0;
  };
  const mid = widest && Math.min(bandPx(widest.i - 1), bandPx(widest.i), bandPx(widest.i + 1)) >= 34 && widest.zone_lst! - widest.ref_lst! >= 1 ? widest : undefined;
  const first = series[0]!.year, last = series[n]!.year;
  // x-axis labels (QA-UX R4-5): first year; the last year with data under the last dots when the series ends in a gap
  // (otherwise those dots read as the final year); missing summers get a grey tick (QA-UX R4-5b: no «н/д» text — it
  // read as «н/д 2024»; the «Без даних» line names them)
  const lastData = [lastZ?.i ?? -1, lastR?.i ?? -1].reduce((a, b) => Math.max(a, b), -1);
  const yearLabels: { x: number; text: string; anchor: 'start' | 'middle' | 'end' }[] = [{ x: X(0), text: String(first), anchor: 'start' }];
  if (lastData > 0 && lastData < n) yearLabels.push({ x: X(lastData), text: String(series[lastData]!.year), anchor: 'middle' });
  if (lastData === n || X(n) - X(Math.max(lastData, 0)) > 52) yearLabels.push({ x: X(n), text: String(last), anchor: 'end' });
  // consecutive missing summers → one hatched band + one label «2021–2022 · н/д» under the axis; the tooltip carries
  // the same reason as the «Без даних» line of the card
  const step = X(1) - X(0);
  const gapRuns = runs(idx, (s) => s.zone_lst == null && s.ref_lst == null);
  const gapBands = gapRuns.map((r) => {
    const a = r[0]!, z = r[r.length - 1]!;
    const x0 = Math.max(padL, X(a.i) - step / 2), x1 = Math.min(X(n), X(z.i) + step / 2);
    const text = `${a.year === z.year ? a.year : `${a.year}–${z.year}`} · ${t('chart.na')}`;
    const cx = (x0 + x1) / 2, half = text.length * 3.5;
    const anchor: 'start' | 'middle' | 'end' = cx - half < 0 ? 'start' : cx + half > w ? 'end' : 'middle';
    const lx = anchor === 'start' ? Math.max(0, x0) : anchor === 'end' ? Math.min(w, x1) : cx;
    const tip = r.map((x) => `${x.year}: ${excludedLabel(x.excluded).replace(/^(немає даних|no data): /, '').replace(/\.$/, '')}`).join('\n');
    return { x0, x1, text, lx, anchor, tip, lo: anchor === 'start' ? lx : anchor === 'end' ? lx - 2 * half : lx - half, hi: anchor === 'start' ? lx + 2 * half : anchor === 'end' ? lx : lx + half };
  });
  // an axis year is hidden when its text (not just its anchor) would touch a band label
  const extent = (x: number, text: string, anchor: 'start' | 'middle' | 'end', cw = 7): [number, number] => {
    const wd = text.length * cw;
    return anchor === 'start' ? [x, x + wd] : anchor === 'end' ? [x - wd, x] : [x - wd / 2, x + wd / 2];
  };
  const yearLabelsShown = yearLabels.filter((l) => {
    const [a, b] = extent(l.x, l.text, l.anchor);
    return !gapBands.some((g) => a < g.hi + 6 && b > g.lo - 6);
  });
  // a summer with data between two gaps has no line segment: draw it as a dot so it does not vanish
  const lone = (rs: (typeof idx)[]) => rs.filter((r) => r.length === 1).map((r) => r[0]!);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" style={{ overflow: 'visible' }}
      aria-label={t('chart.lineAria', { zone: zoneName, from: first ?? '', to: last ?? '' })} data-testid="linechart">
      <defs>
        <pattern id="nodata-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink2)" strokeWidth="1.5" opacity=".28" />
        </pattern>
      </defs>
      {niceTicks(lo, hi).map((t) => (
        <g key={t}>
          <line x1={padL} x2={w - padR + 6} y1={Y(t)} y2={Y(t)} stroke="var(--rule)" />
          <text x={padL - 8} y={Y(t) + 4} textAnchor="end" fontSize="13" fill="var(--ink2)">{t}°</text>
        </g>
      ))}
      {yearLabelsShown.map((l) => <text key={l.text} x={l.x} y={h - 6} textAnchor={l.anchor} fontSize="13" fill="var(--ink2)">{l.text}</text>)}
      {gapBands.map((g) => (
        <g key={g.text} data-testid="chart-nodata">
          <title>{g.tip}</title>
          <rect x={g.x0} y={padT} width={Math.max(1, g.x1 - g.x0)} height={h - padT - padB} fill="url(#nodata-hatch)" />
          <line x1={g.x0} x2={g.x0} y1={padT} y2={h - padB} stroke="var(--ink2)" strokeDasharray="3 3" opacity=".45" />
          <line x1={g.x1} x2={g.x1} y1={padT} y2={h - padB} stroke="var(--ink2)" strokeDasharray="3 3" opacity=".45" />
          <text x={g.lx} y={h - 6} textAnchor={g.anchor} fontSize="12" fill="var(--ink2)">{g.text}</text>
        </g>
      ))}
      {bandRuns.map((r, k) => (
        <path key={k} fill="var(--heat-l)" opacity=".8"
          d={path(r.map((s) => [X(s.i), Y(s.zone_lst!)])) + ' L' + [...r].reverse().map((s) => `${X(s.i).toFixed(1)},${Y(s.ref_lst!).toFixed(1)}`).join(' L') + 'Z'} />
      ))}
      {refRuns.map((r, k) => <path key={k} d={path(r.map((s) => [X(s.i), Y(s.ref_lst!)]))} fill="none" stroke="var(--ref)" strokeWidth="2.5" strokeLinejoin="round" />)}
      {zoneRuns.map((r, k) => <path key={k} d={path(r.map((s) => [X(s.i), Y(s.zone_lst!)]))} fill="none" stroke="var(--heat)" strokeWidth="2.5" strokeLinejoin="round" />)}
      {lone(refRuns).map((x) => <circle key={`r${x.i}`} cx={X(x.i)} cy={Y(x.ref_lst!)} r="3" fill="var(--ref)" />)}
      {lone(zoneRuns).map((x) => <circle key={`z${x.i}`} cx={X(x.i)} cy={Y(x.zone_lst!)} r="3" fill="var(--heat)" />)}
      {lastZ && <circle cx={X(lastZ.i)} cy={Y(lastZ.zone_lst!)} r="4" fill="var(--heat)" />}
      {lastR && <circle cx={X(lastR.i)} cy={Y(lastR.ref_lst!)} r="4" fill="var(--ref)" />}
      {lastZ && (
        <text x={X(n) + 10} y={yz + 5 - (zl.length - 1) * 8} fontSize="14" fontWeight="600" fill="var(--heat)">
          {zl.map((l, i) => <tspan key={i} x={X(n) + 10} dy={i ? 16 : 0}>{l}</tspan>)}
        </text>
      )}
      {lastR && (
        <text x={X(n) + 10} y={yr + 5 - (rl.length - 1) * 8} fontSize="14" fontWeight="600" fill="var(--ref)">
          {rl.map((l, i) => <tspan key={i} x={X(n) + 10} dy={i ? 16 : 0}>{l}</tspan>)}
        </text>
      )}
      {mid && <text x={X(mid.i)} y={(Y(mid.zone_lst!) + Y(mid.ref_lst!)) / 2 + 5} textAnchor="middle" fontSize="13" fill="var(--heat)" opacity=".9">{t('chart.gapWord')}</text>}
    </svg>
  );
}

/** Theil–Sen style line through the median point, as drawn in F7. */
export function trendLine(gaps: (number | null)[], slopePerYear: number): { b: number } {
  const resid = gaps.map((g, i) => (g == null ? null : g - slopePerYear * i)).filter((v): v is number => v != null).sort((a, b) => a - b);
  const m = resid.length;
  const b = m === 0 ? 0 : m % 2 ? resid[(m - 1) / 2]! : (resid[m / 2 - 1]! + resid[m / 2]!) / 2;
  return { b };
}

/** Gap per year with mean (dashed) and trend line; selected year highlighted (details §1). */
export function GapBars({ series, trend, mean, selectedYear, onSelectYear, zoneName, w = 460, h = 170 }: {
  series: SeriesPoint[]; trend: Trend; mean: number | null; selectedYear: number | null;
  onSelectYear?: (y: number) => void; zoneName: string; w?: number; h?: number;
}) {
  const t = useT();
  const padL = 42, padR = 78, padT = 22, padB = 24;
  const gaps = series.map((s) => s.gap);
  const defined = gaps.filter((g): g is number => g != null);
  if (defined.length === 0) return null;
  const hi = Math.max(5, Math.ceil((Math.max(...defined) + 1.5) / 5) * 5);
  const lo = Math.min(0, Math.floor(Math.min(...defined) / 5) * 5);
  const n = series.length;
  const cw = (w - padL - padR) / n;
  const bw = cw * 0.62;
  const Y = (t: number) => padT + ((hi - t) * (h - padT - padB)) / (hi - lo);
  const ticks = niceTicks(lo, hi, 2);
  const slopeYr = trend.slope_per_decade != null ? trend.slope_per_decade / 10 : null;
  const tl = slopeYr != null ? trendLine(gaps, slopeYr) : null;
  const maxI = gaps.indexOf(Math.max(...defined));
  const labelEvery = n > 8 ? 4 : 2;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={t('chart.barsAria', { zone: zoneName })} data-testid="gapbars" style={{ overflow: 'visible' }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={w - padR} y1={Y(t)} y2={Y(t)} stroke="var(--rule)" />
          <text x={padL - 8} y={Y(t) + 4} textAnchor="end" fontSize="13" fill="var(--ink2)">{t > 0 ? '+' : ''}{fmt(t, 0)}°</text>
        </g>
      ))}
      {series.map((s, i) => {
        const x = padL + i * cw + (cw - bw) / 2;
        const sel = s.year === selectedYear;
        const showYear = i % labelEvery === 0 || i === n - 1;
        return (
          <g key={s.year} onClick={onSelectYear ? () => onSelectYear(s.year) : undefined} style={onSelectYear ? { cursor: 'pointer' } : undefined}>
            <title>{`${s.year}: ${s.gap == null ? t('chart.noData') : fmtDeg(s.gap) + 'C'}`}</title>
            <rect x={padL + i * cw} y={padT} width={cw} height={h - padT - padB} fill="transparent" />
            {s.gap != null ? (
              <rect x={x} y={Math.min(Y(s.gap), Y(0))} width={bw} height={Math.abs(Y(0) - Y(s.gap))} rx="3" fill="var(--heat)" opacity={sel ? 1 : 0.45} />
            ) : (
              <text x={x + bw / 2} y={Y(0) - 4} textAnchor="middle" fontSize="13" fill="var(--ink2)">{t('chart.na')}</text>
            )}
            {showYear && <text x={x + bw / 2} y={h - 6} textAnchor="middle" fontSize="13" fill="var(--ink2)">{s.year}</text>}
            {(sel || i === maxI) && s.gap != null && (
              <text x={x + bw / 2} y={Y(s.gap) - 6} textAnchor="middle" fontSize="13" fontWeight={sel ? 600 : 400} fill={sel ? 'var(--heat)' : 'var(--ink2)'}>{fmt(s.gap, 1, true)}</text>
            )}
          </g>
        );
      })}
      {mean != null && (
        <>
          <line x1={padL} x2={w - padR + 6} y1={Y(mean)} y2={Y(mean)} stroke="var(--ink)" strokeDasharray="4 4" strokeWidth="1.5" />
          <text x={w - padR + 12} y={Y(mean) - 3} fontSize="13" fontWeight="600" fill="var(--ink)">
            <tspan x={w - padR + 12}>{t('chart.mean')}</tspan><tspan x={w - padR + 12} dy={15}>{fmtDeg(mean)}</tspan>
          </text>
        </>
      )}
      {tl && slopeYr != null && (
        <>
          <line x1={padL + cw / 2} x2={padL + (n - 0.5) * cw} y1={Y(tl.b)} y2={Y(tl.b + slopeYr * (n - 1))} stroke="var(--ink)" strokeWidth="2" />
          <text x={w - padR + 12} y={mean != null && Math.abs(Y(tl.b + slopeYr * (n - 1)) - Y(mean)) < 40 ? Y(mean) + 32 : Y(tl.b + slopeYr * (n - 1)) + 4} fontSize="13" fill="var(--ink2)">{t('chart.trend')}</text>
        </>
      )}
    </svg>
  );
}

/** CI interval vs «без змін» (details §2). */
export function TrendInterval({ trend, w = 460 }: { trend: Trend; w?: number }) {
  const t = useT();
  if (!trend.ci95 || trend.slope_per_decade == null) return <p className="s">{t('chart.ciTooFew')}</p>;
  const [a, b] = trend.ci95;
  const m = trend.slope_per_decade;
  const lo = Math.floor(Math.min(a, -1) - 1.5);
  const hi = Math.ceil(Math.max(b, 1) + 1.5);
  const pad = 24;
  const X = (t: number) => pad + ((t - lo) / (hi - lo)) * (w - 2 * pad);
  return (
    <svg width={w} height="58" viewBox={`0 0 ${w} 58`} role="img"
      aria-label={t('chart.ciAria', { m: fmt(m, 1, true), lo: fmt(a, 1, true), hi: fmt(b, 1, true) })}>
      <rect x={X(a)} y="18" width={Math.max(4, X(b) - X(a))} height="12" rx="6" fill="var(--heat-l)" />
      <line x1={X(0)} x2={X(0)} y1="8" y2="40" stroke="var(--ink)" strokeWidth="2" />
      <circle cx={X(m)} cy="24" r="7" fill="var(--heat)" stroke="var(--surf)" strokeWidth="2" />
      <text x={X(a)} y="12" fontSize="13" fill="var(--ink2)" textAnchor="middle">{fmt(a, 1, true)}</text>
      <text x={X(b)} y="12" fontSize="13" fill="var(--ink2)" textAnchor="middle">{fmt(b, 1, true)}</text>
      <text x={X(0)} y="54" fontSize="13" fontWeight="600" fill="var(--ink)" textAnchor="middle">{t('chart.noChange')}</text>
      <text x="0" y="54" fontSize="13" fill="var(--ink2)">{t('chart.decreasing')}</text>
      <text x={w} y="54" fontSize="13" fill="var(--ink2)" textAnchor="end">{t('chart.increasing')}</text>
    </svg>
  );
}

export interface CompareRow { id: string; name: string; value: number | null; sel: boolean }

export function CompareBars({ rows }: { rows: CompareRow[] }) {
  const t = useT();
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.value ?? 0)));
  return (
    <div role="list" aria-label={t('chart.compareAria')}>
      {rows.map((r) => (
        <div key={r.id} role="listitem" className={`cmp-row${r.sel ? ' sel' : ''}`}>
          <span className="cmp-name" title={r.name}>{r.name}</span>
          {r.value == null ? <div className="skel" style={{ height: 10 }} aria-hidden="true" /> : (
            <div className="cmp-bar" style={{ width: `${Math.max(2, (Math.abs(r.value) / max) * 100)}%`, opacity: r.sel ? 1 : 0.4 }} />
          )}
          <span style={{ textAlign: 'right' }} className={r.value == null ? 'xs' : undefined}>{r.value == null ? t('chart.computing') : fmtDeg(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** Per-year gap bars that double as the map year selector (radiogroup, arrow keys). */
export function YearBars({ series, years, year, onChange, metric = barsMetric('gap') }: {
  series: SeriesPoint[] | null; years: number[]; year: number; onChange: (y: number) => void; metric?: BarsMetric;
}) {
  const t = useT();
  const id = useId();
  // MAP-TASKS 28: NDVI has its own availability — a summer left out of the heat analysis can still have NDVI
  const byYear = new Map(series?.map((s) => [s.year, s.excluded && metric.kind !== 'ndvi' ? null : metric.value(s)]) ?? []);
  const noData = (y: number) => (metric.kind === 'ndvi' ? NDVI_NODATA : why.get(y) ? excludedText(why.get(y)!) : excludedLabel(null));
  const why = new Map(series?.map((s) => [s.year, s]) ?? []);
  const vals = [...byYear.values()].filter((v): v is number => v != null);
  // gap: |value| from 0 (sign matters); LST / NDVI: the spread between summers (absolute bars would all look equal)
  const lo = metric.signed ? 0 : Math.min(...vals) - Math.max((Math.max(...vals) - Math.min(...vals)) * 0.5, metric.kind === 'ndvi' ? 0.02 : 1);
  const max = Math.max(metric.signed ? 1 : 1e-6, ...vals.map((v) => Math.abs(v - lo)));
  const show = (v: number) => (metric.kind === 'gap' ? `${fmtDeg(v)}C` : metric.kind === 'lst' ? `${fmt(v, 1)}\u00a0°C` : `NDVI ${fmt(v, 2)}`);
  const what = metric.kind === 'gap' ? t('chart.whatGap') : metric.kind === 'lst' ? t('chart.whatLst') : t('chart.whatNdvi');
  const onKey = (e: KeyboardEvent) => {
    const i = years.indexOf(year);
    let j = i;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') j = Math.max(0, i - 1);
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') j = Math.min(years.length - 1, i + 1);
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = years.length - 1;
    else return;
    e.preventDefault();
    onChange(years[j]!);
    (document.getElementById(`${id}-${years[j]}`) as HTMLElement | null)?.focus();
  };
  return (
    <div className="yearbars">
      {/* the bars follow the map layer (board item 6 c; was always the gap, QA-UX R3-4) */}
      <div className="yearbars-head"><div className="yearbars-cap" aria-hidden="true" data-testid="yearbars-cap">{metric.caption}</div><Hint k="yearBars" side="above" /></div>
      <div className="yearbars-row" role="radiogroup" aria-label={t('chart.yearBarsAria', { caption: metric.caption })} onKeyDown={onKey}>
        {years.map((y) => {
          const g = byYear.get(y);
          const has = g != null;
          return (
            <button key={y} id={`${id}-${y}`} type="button" role="radio" aria-checked={y === year} tabIndex={y === year ? 0 : -1}
              className={`yearbar${has || !series ? '' : ' nodata'}`} onClick={() => onChange(y)}
              aria-label={`${y}${has ? `, ${what} ${show(g!)}` : series ? `, ${noData(y)}` : ''}`} title={`${y}${has ? ` · ${show(g!)}` : series ? ` · ${noData(y)}` : ''}`}>
              <span style={{ height: `${has ? Math.max(3, (Math.abs(g! - lo) / max) * 26) : series ? 3 : 10}px` }} />
            </button>
          );
        })}
      </div>
      {/* MAP-TASKS 16: the selected year sits under its own bar (bar pitch 14 + 8 px); an end year that would collide
          with it (one bar away) is left out */}
      <div className="yearbars-axis" aria-hidden="true" data-testid="yearbars-axis">
        {years.map((y, i) => {
          const sel = years.indexOf(year);
          const isEnd = i === 0 || i === years.length - 1;
          if (y !== year && !(isEnd && Math.abs(i - sel) >= 2)) return null;
          return <span key={y} className={y === year ? 'cur' : ''} data-year={y} style={{ left: `${i * 22 + 7}px` }}>{y}</span>;
        })}
      </div>
    </div>
  );
}
