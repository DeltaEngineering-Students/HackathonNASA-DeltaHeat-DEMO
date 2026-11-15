import { applyChatEvent, UNSOURCED_WARNING, type Turn } from './ChatPanel';
import { parseSse, type ChatEvent } from '../api/client';

const run = (blocks: string[]): Turn =>
  blocks.map(parseSse).filter((e): e is ChatEvent => !!e).reduce(applyChatEvent, { role: 'assistant', content: '', steps: [] } as Turn);

describe('analyst chat stream', () => {
  it('replaces the rejected answer on text_reset (no concatenation)', () => {
    const t = run([
      'event: text\ndata: {"delta":"Розрив виріс на 5 °C."}',
      'event: validation\ndata: {"repairing":true,"ok":false,"unsourced":["5"]}',
      'event: text_reset\ndata: {}',
      'event: text\ndata: {"delta":"Розрив +0,3 °C за 10 років — у межах шуму."}',
      'event: done\ndata: {"validation":{"ok":true}}',
    ]);
    expect(t.content).toBe('Розрив +0,3 °C за 10 років — у межах шуму.');
    expect(t.warning).toBeUndefined();
    expect(t.steps!.find((s) => s.tool === 'перевірка чисел')?.status).toBe('done');
  });
  it('warns when the final validation fails', () => {
    const t = run(['event: text\ndata: {"delta":"Відповідь"}', 'event: done\ndata: {"validation":{"ok":false}}']);
    expect(t.warning).toBe(UNSOURCED_WARNING);
  });
  it('tracks tool steps by id', () => {
    const t = run(['event: tool_call\ndata: {"id":"a","name":"get_report"}', 'event: tool_result\ndata: {"id":"a","name":"get_report","is_error":false}']);
    expect(t.steps).toEqual([{ id: 'a', tool: 'get_report', status: 'done' }]);
  });
});

describe('analyst chat — P0 additions', () => {
  it('maps backend SSE error codes, never shows backend English', async () => {
    const { errorText } = await import('./chatStrings');
    const e = parseSse('event: error\ndata: {"error":"too_expensive","message":"stopped: cap $0.50"}');
    expect(e).toEqual({ type: 'error', code: 'too_expensive', message: 'stopped: cap $0.50' });
    expect(errorText('too_expensive', 'uk')).toMatch(/задорог/);
    expect(errorText('too_expensive', 'en')).toMatch(/too expensive/);
    expect(errorText('agent_budget_exhausted', 'uk')).toMatch(/Ліміт аналітика на сьогодні вичерпано/);
    expect(errorText('something_new', 'uk')).not.toMatch(/[a-z]/);
  });
  it('an error drops the unvalidated draft text', () => {
    const t = run(['event: text\ndata: {"delta":"Чернетка 9,9 °C"}', 'event: error\ndata: {"error":"upstream_error"}']);
    expect(t.content).toBe('');
  });
  it('collects summarized thinking and the unsourced numbers', () => {
    const t = run([
      'event: thinking\ndata: {"delta":"Дивлюся звіт. "}', 'event: thinking\ndata: {"delta":"Беру розрив."}',
      'event: text\ndata: {"delta":"Розрив 7,7 °C."}',
      'event: done\ndata: {"validation":{"ok":false,"unsourced":[{"text":"7,7","value":7.7}]},"cost_usd":0.08}',
    ]);
    expect(t.thinking).toBe('Дивлюся звіт. Беру розрив.');
    expect(t.unsourced).toEqual(['7,7']);
    expect(t.draft).toBe(false);
  });
  it('caveat-only repair says so', async () => {
    const t = run(['event: validation\ndata: {"repairing":true,"ok":true,"unsourced":[],"caveats":[{"code":"lst_not_air"}]}']);
    expect(t.steps![0]!.summary).toBe('analyst.caveatsRepairing');
    const { say } = await import('./chatStrings');
    expect(say(t.steps![0]!.summary!, 'uk')).toMatch(/застереження/);
    expect(say(t.steps![0]!.summary!, 'en')).toMatch(/caveat/);
  });
  it('has a Ukrainian label for every backend tool id', async () => {
    const { toolLabel } = await import('./ChatPanel');
    const ids = ['search_places', 'get_overview', 'get_report', 'zone_timeseries', 'land_change', 'list_scenes',
      'get_scene_stats', 'get_weather', 'climate_projection', 'rank_zones', 'create_report', 'set_map_view',
      'list_reports', 'run_analysis', 'web_search', 'web_fetch'];
    for (const id of ids) for (const l of ['uk', 'en'] as const) expect(toolLabel(id, l), id).not.toMatch(/працює з даними|working with the data/);
    expect(toolLabel('get_report', 'uk')).toBe('перевіряє цифри звіту');
  });
});
