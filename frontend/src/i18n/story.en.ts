// English sentence builders (TERMS-EN.md). Written as English sentences, not translated word by word; the numbers and
// their rounding are the same as in Ukrainian (half-up via i18n/format).
import type { Report } from '../api/types';
import type { Sentences } from './sentences';
import { NBSP, num, plural, summers } from './format';

const f = (x: number | null | undefined, d = 1, sign = false) => num(x, 'en', d, sign);
export const CITY_EN: Record<string, string> = { kyiv: 'Kyiv', kharkiv: 'Kharkiv', lviv: 'Lviv',
  // api/adapt.ts replaces reference.city with the Ukrainian label; accept it until the adapter keeps the id (phase 2)
  'Київ': 'Kyiv', 'Харків': 'Kharkiv', 'Львів': 'Lviv' };
const cityOf = (r: { city?: string }) => (r.city ? CITY_EN[r.city] : undefined);
const degC = (x: number) => `${f(x, 1, true)}${NBSP}°C`;
const vsForest = (g: number) => `${f(Math.abs(g), 1)} °C ${g >= 0 ? 'hotter' : 'cooler'} than the forest`;
const districtsOf = (r: { city?: string }, n: number) => {
  const c = cityOf(r);
  const d = plural(n, 'en', { one: 'district', other: 'districts' });
  return c ? `${n} ${c} ${d}` : `${n} ${d} of the city`;
};

/** English lead for a report, mirroring science `verdict_text` (uhd/backend/uhd/science/report.py). */
function verdictEn(r: Report, name?: string | null): string | null {
  const mean = r.gap_summary.mean;
  if (mean == null) return name ? `${name}: too little data for a conclusion.` : 'Too little data for a conclusion.';
  const built = r.zone.analysed !== 'all_land';
  const subj = built ? 'the built-up surface' : 'the surface here';
  const city = r.reference.kind === 'derived' ? undefined : CITY_EN[r.reference.city];
  const forest = `the forest around ${city ?? 'the city'}`;
  const s1 = Math.abs(mean) < 0.5
    ? `${subj} is almost as warm on summer days as ${forest} (a difference of ${f(Math.abs(mean))} °C)`
    : `${subj} is on average ${f(Math.abs(mean))} °C ${mean > 0 ? 'hotter' : 'cooler'} on summer days than ${forest}`;
  const t = r.trend, n = t.n_years;
  let s2: string;
  if (t.verdict === 'insufficient_data') s2 = ', but there are too few data to say whether this gap is changing.';
  else if (t.verdict === 'significant' && t.slope_per_decade != null)
    s2 = `, and over ${summers(n, 'en')} this gap has ${t.slope_per_decade > 0 ? 'grown' : 'shrunk'} — by about ${f(Math.abs(t.slope_per_decade))} °C per 10 years (statistically significant, p = ${f(t.p, 3)}).`;
  else s2 = `, and over ${summers(n, 'en')} this gap has not changed noticeably (not statistically significant, p = ${f(t.p, 2)}).`;
  let lead = (name ? `${name}: ` : '') + s1 + s2;
  if (!name) lead = lead[0]!.toUpperCase() + lead.slice(1);
  const parts = [lead];
  const z = r.zone_trend, ref = r.ref_trend;
  if (r.gap_driver === 'reference' && t.slope_per_decade != null && ref?.slope_per_decade != null && z?.slope_per_decade != null) {
    parts.push(`The gap has ${t.slope_per_decade > 0 ? 'grown' : 'shrunk'} mostly because of the reference forest: in these summer seasons it was ` +
      `${ref.slope_per_decade < 0 ? 'cooler' : 'warmer'} (${f(ref.slope_per_decade)} °C per 10 years), while the surface here changed less ` +
      `(${f(z.slope_per_decade)} °C per 10 years).`);
  } else if (r.gap_driver === 'zone' && z?.verdict === 'significant' && z.slope_per_decade != null) {
    const s = `its surface is ${z.slope_per_decade > 0 ? 'warming' : 'cooling'} by ${f(Math.abs(z.slope_per_decade))} °C per 10 years.`;
    parts.push(ref?.verdict === 'significant'
      ? `It is this area itself that is changing: ${s}`
      : `The reference forest has no statistically significant trend, so the change comes from the area itself: ${s}`);
  }
  const nb = r.new_built_gap;
  if (nb && nb.area_km2 >= 0.2 && nb.before.gap != null && nb.after.gap != null && Math.abs(nb.after.gap - nb.before.gap) >= 1) {
    const yb = nb.before.years, ya = nb.after.years;
    parts.push(`Where new buildings appeared during these years (≈${f(nb.area_km2)} km²), the surface became ` +
      `${nb.after.gap > nb.before.gap ? 'hotter' : 'cooler'}: the gap with the forest was ${f(nb.before.gap)} °C in ${yb[0]}–${yb[yb.length - 1]} ` +
      `and ${f(nb.after.gap)} °C in ${ya[0]}–${ya[ya.length - 1]}.`);
  }
  const nd = r.ndvi_trend;
  if (nd?.verdict === 'significant' && nd.slope_per_decade != null)
    parts.push(`Greenness in the area is ${nd.slope_per_decade > 0 ? 'increasing' : 'decreasing'} (statistically significant).`);
  if (r.green_gap != null && built && r.green_gap > 0)
    parts.push(`Parks and squares inside the city are ${f(r.green_gap)} °C cooler than this built-up land.`);
  return parts.join(' ');
}

export const en: Sentences = {
  rank(r) {
    if (r.hotterThan === r.of) return `hotter than the average of any of the ${districtsOf(r, r.of)}`;
    if (r.hotterThan === 0) return `cooler than the average of each of the ${districtsOf(r, r.of)}`;
    return `hotter than the average of ${r.hotterThan} of the ${districtsOf(r, r.of)}`;
  },
  districtRange(r) {
    if (!r.range) return null;
    const lo = r.coolest ? `${f(r.coolest.gap, 1, true)} (${r.coolest.name})` : f(r.range[0], 1, true);
    const hi = r.hottest ? `${f(r.hottest.gap, 1, true)} °C (${r.hottest.name})` : `${f(r.range[1], 1, true)} °C`;
    const c = cityOf(r);
    return `For comparison: built-up land in ${c ? `${c}’s districts` : 'the city’s districts'} ranges from ${lo} to ${hi}.`;
  },
  forest(city, derived) {
    const c = city ? CITY_EN[city] : undefined;
    if (c) return `the forest around ${c}`;
    void derived; // Роман P1-3: the auto-picked reference is said in Details, not in the card sentence
    return 'the forest around the city';
  },
  stableHot: (n) => `no clear change (data from ${summers(n, 'en')})`,
  parksCooler: (g) => `Parks and squares in the city are ${f(g, 1)}${NBSP}°C cooler than this built-up land`,
  greenTrend: (up, a, b) => `Greenness is significantly ${up ? 'increasing' : 'decreasing'} (NDVI ${f(a, 2)} → ${f(b, 2)})`,
  newBuilt(nb) {
    const b = nb.before, a = nb.after;
    const since = b.years.length ? `appeared after ${b.years[b.years.length - 1]}` : '';
    const area = nb.area_km2 != null ? `${f(nb.area_km2, 1)} km²` : '';
    const paren = [area, since].filter(Boolean).join(', ');
    const after = Math.sign(a.gap) === Math.sign(b.gap) || a.gap === 0 ? `${f(Math.abs(a.gap), 1)} °C` : vsForest(a.gap);
    const yrs = (ys: number[]) => (ys.length ? ` (${ys.join(', ')})` : '');
    const text = `${paren ? ` (${paren})` : ''}: before construction${yrs(b.years)} this land was ${vsForest(b.gap)}, after${yrs(a.years)} — ${after}.`;
    let title = 'Bare soil, a building site or dry grass heat up on summer days at least as much as roofs and asphalt, so the gap does not necessarily grow after construction.';
    if (nb.spread && Math.abs(a.gap - b.gap) < nb.spread[1] - nb.spread[0])
      title += ` The before/after difference here is smaller than the variation between summer seasons (${f(nb.spread[0], 1)}–${f(nb.spread[1], 1)} °C).`;
    return { lead: 'New built-up land', text, title };
  },
  climate(c, nModels) {
    if (typeof c.delta !== 'number' || !c.period) return null;
    const until = c.period.split(/[-–]/).pop();
    const bp = c.baseline_period;
    const bpText = Array.isArray(bp) ? (bp.length === 2 ? `${bp[0]}–${bp[1]}` : '') : (bp ?? '').replace('-', '–');
    const verb = c.delta >= 0 ? 'rise' : 'fall';
    const main = `Outlook: by ${until} the summer daily maximum near-surface air temperature (2 m) will ${verb} by about ${f(Math.abs(c.delta), 1, c.delta >= 0)}${NBSP}°C${bpText ? ` (compared with ${bpText})` : ''}`;
    const n = nModels && nModels > 1 ? nModels : null;
    const scen = c.scenario === 'ssp245' ? 'Moderate scenario (SSP2‑4.5)' : `Scenario ${c.scenario.toUpperCase()}`;
    const spread = c.delta_range ? `from ${f(c.delta_range[0], 1, true)} to ${f(c.delta_range[1], 1, true)}${NBSP}°C` : null;
    const models = n ? `, median of ${n} models${spread ? `; 10–90% range: ${spread}` : ''}` : spread ? `; 10–90% model range: ${spread}` : '';
    return { main, sub: `${scen}${models}. Air, not surface.` };
  },
  hotspotTip(h, i) {
    let t = `Spot ${i + 1}: ${f(Math.abs(h.gap), 1)} °C ${h.gap >= 0 ? 'hotter' : 'cooler'} than the forest`;
    if (h.delta_vs_zone != null && h.delta_vs_zone > 0) t += ` — ${f(h.delta_vs_zone, 1)} °C hotter than the area’s built-up land on average`;
    t += '.';
    const ys = h.years?.length ? h.years.join(', ') : '';
    if (ys) t += ` ${h.years!.length > 1 ? 'Summer seasons' : 'Summer'} ${ys}.`;
    // land-class label: the backend sends label_uk only for now (phase 3 adds label_en); omitted rather than mixed
    return t;
  },
  ci(t) {
    if (t.verdict === 'insufficient_data' || !t.ci95 || t.slope_per_decade == null)
      return 'Too few clear summer seasons to estimate how the gap is changing.';
    const [lo, hi] = t.ci95;
    const includesZero = lo <= 0 && hi >= 0;
    const head = `Most likely ${degC(t.slope_per_decade)} per 10 years`;
    const range = `from ${f(lo, 1, true)} to ${degC(hi)}`;
    if (t.verdict === 'significant')
      return includesZero
        ? `${head}. The Mann–Kendall test detects a change (p < 0.05), but the confidence interval ${range} still includes «no change» — the evidence is weak.`
        : `${head}; the confidence interval ${range} excludes «no change», and the Mann–Kendall test confirms it — statistical evidence, not a verdict.`;
    return includesZero
      ? `${head}, but the true change could be anywhere ${range} — including «no change». For now this is within the weather noise.`
      : `${head}; the confidence interval ${range} excludes «no change», but the Mann–Kendall test finds no statistically significant change — treat it with caution.`;
  },
  verdict: verdictEn,
};
