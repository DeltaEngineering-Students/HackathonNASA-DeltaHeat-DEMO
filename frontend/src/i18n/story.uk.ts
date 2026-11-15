// Ukrainian sentence builders — the current product wording (lib/story.ts, lib/verdict.ts), TERMS-UK.md.
import type { Sentences } from './sentences';
import { NBSP, num, summersGen } from './format';

const f = (x: number | null | undefined, d = 1, sign = false) => num(x, 'uk', d, sign);
const CITY_GEN: Record<string, string> = { kyiv: 'Києва', kharkiv: 'Харкова', lviv: 'Львова' };
const gen = (r: { city?: string; cityGen?: string }) => r.cityGen ?? (r.city ? CITY_GEN[r.city] : undefined) ?? 'міста';
const degC = (x: number) => `${f(x, 1, true)}${NBSP}°C`;
const vsForest = (g: number) => `на ${f(Math.abs(g), 1)} °C ${g >= 0 ? 'гарячіша' : 'прохолодніша'} за ліс`;

export const uk: Sentences = {
  rank(r) {
    if (r.hotterThan === r.of) return `гарячіше, ніж у середньому в будь-якому з ${r.of} районів ${gen(r)}`;
    if (r.hotterThan === 0) return `прохолодніше, ніж у середньому в кожному з ${r.of} районів ${gen(r)}`;
    return `гарячіше, ніж у середньому в ${r.hotterThan} з ${r.of} районів ${gen(r)}`;
  },
  districtRange(r) {
    if (!r.range) return null;
    const lo = r.coolest ? `${f(r.coolest.gap, 1, true)} (${r.coolest.name})` : f(r.range[0], 1, true);
    const hi = r.hottest ? `${f(r.hottest.gap, 1, true)} °C (${r.hottest.name})` : `${f(r.range[1], 1, true)} °C`;
    return `Для порівняння: забудова районів ${gen(r)} — від ${lo} до ${hi}.`;
  },
  forest(city, derived) {
    const g = city ? CITY_GEN[city] : undefined;
    if (g) return `ліс навколо ${g}`;
    void derived; // Роман P1-3: the auto-picked reference is said in Details, not in the card sentence
    return 'ліс навколо міста';
  },
  stableHot: (n) => `помітної зміни не видно (дані ${summersGen(n, 'uk')})`,
  parksCooler: (g) => `Парки й сквери в місті на ${f(g, 1)}${NBSP}°C прохолодніші за цю забудову`,
  greenTrend: (up, a, b) => `Зелені ${up ? 'суттєво більшає' : 'суттєво меншає'} (NDVI ${f(a, 2)} → ${f(b, 2)})`,
  newBuilt(nb) {
    const b = nb.before, a = nb.after;
    const since = b.years.length ? ` з’явилась після ${b.years[b.years.length - 1]} р.` : '';
    const area = nb.area_km2 != null ? `${f(nb.area_km2, 1)} км²${since ? ',' : ''}` : '';
    const after = Math.sign(a.gap) === Math.sign(b.gap) || a.gap === 0 ? `на ${f(Math.abs(a.gap), 1)} °C` : vsForest(a.gap);
    const yrs = (ys: number[]) => (ys.length ? ` (${ys.join(', ')})` : '');
    const text = ` (${area}${since}): до будівництва${yrs(b.years)} ця земля була ${vsForest(b.gap)}, після${yrs(a.years)} — ${after}.`;
    let title = 'Відкритий ґрунт, будмайданчик чи суха трава влітку вдень гріються не менше за дахи й асфальт, тому після забудови розрив не обов’язково росте.';
    if (nb.spread && Math.abs(a.gap - b.gap) < nb.spread[1] - nb.spread[0])
      title += ` Різниця «до/після» тут менша за коливання між літніми сезонами (${f(nb.spread[0], 1)}–${f(nb.spread[1], 1)} °C).`;
    return { lead: 'Нова забудова', text: text.replace(' (: ', ' (').replace(' ()', ''), title };
  },
  climate(c, nModels) {
    if (typeof c.delta !== 'number' || !c.period) return null;
    const until = c.period.split(/[-–]/).pop();
    const bp = c.baseline_period;
    const bpText = Array.isArray(bp) ? (bp.length === 2 ? `${bp[0]}–${bp[1]}` : '') : (bp ?? '').replace('-', '–');
    const verb = c.delta >= 0 ? 'зросте' : 'знизиться';
    const main = `Прогноз: до ${until} денний максимум приземної температури повітря (на висоті 2 м) ${verb} приблизно на ${f(c.delta >= 0 ? c.delta : -c.delta, 1, c.delta >= 0)}${NBSP}°C${bpText ? ` (порівняно з ${bpText})` : ''}`;
    const n = nModels && nModels > 1 ? nModels : null;
    const scen = c.scenario === 'ssp245' ? 'Помірний сценарій (SSP2‑4.5)' : `Сценарій ${c.scenario.toUpperCase()}`;
    const spread = c.delta_range ? `від ${f(c.delta_range[0], 1, true)} до ${f(c.delta_range[1], 1, true)}${NBSP}°C` : null;
    const models = n ? `, медіана ${n} моделей${spread ? `; діапазон 10–90${NBSP}%: ${spread}` : ''}` : spread ? `; діапазон моделей 10–90${NBSP}%: ${spread}` : '';
    return { main, sub: `${scen}${models}. Повітря, не поверхня.` };
  },
  hotspotTip(h, i) {
    let t = `Місце ${i + 1}: на ${f(Math.abs(h.gap), 1)} °C ${h.gap >= 0 ? 'гарячіше' : 'прохолодніше'} за ліс`;
    if (h.delta_vs_zone != null && h.delta_vs_zone > 0) t += ` — на ${f(h.delta_vs_zone, 1)} °C гарячіше, ніж забудова ділянки в середньому`;
    t += '.';
    const ys = h.years?.length ? h.years.join(', ') : '';
    if (ys) t += ` ${h.years!.length > 1 ? 'Літні сезони' : 'Літо'} ${ys}.`;
    if (h.type_uk) t += ` Тут переважно ${h.type_uk}.`;
    return t;
  },
  ci(t) {
    if (t.verdict === 'insufficient_data' || !t.ci95 || t.slope_per_decade == null)
      return 'Замало чистих літніх сезонів, щоб оцінити, як змінюється розрив.';
    const [lo, hi] = t.ci95;
    const includesZero = lo <= 0 && hi >= 0;
    const head = `Найімовірніше ${degC(t.slope_per_decade)} за 10 років`;
    const range = `від ${f(lo, 1, true)} до ${degC(hi)}`;
    if (t.verdict === 'significant')
      return includesZero
        ? `${head}. Тест Манна–Кендалла бачить зміну (p < 0,05), але довірчий інтервал ${range} ще зачіпає «без змін» — доказ слабкий.`
        : `${head}; довірчий інтервал ${range} не включає «без змін», і тест Манна–Кендалла це підтверджує — це статистичний доказ, не вирок.`;
    return includesZero
      ? `${head}, але справжня зміна може бути будь-де ${range} — разом із «без змін». Поки це в межах погодного шуму.`
      : `${head}; довірчий інтервал ${range} не включає «без змін», але тест Манна–Кендалла не бачить статистично значущої зміни — сприймайте обережно.`;
  },
  // Ukrainian always comes from the backend (verdict_text_uk)
  verdict: () => null,
};
