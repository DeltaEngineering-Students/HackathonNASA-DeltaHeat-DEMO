import { fetchRetry, parseSse, retryingTileUrl } from './client';

describe('SSE parsing for the analyst chat (backend agent/loop.py events)', () => {
  it('maps text, tool calls and results', () => {
    expect(parseSse('event: text\ndata: {"type":"text","delta":"Привіт"}')).toEqual({ type: 'delta', text: 'Привіт' });
    expect(parseSse('event: tool_call\ndata: {"type":"tool_call","id":"t1","name":"get_report","input":{}}')).toEqual({ type: 'step', step: { id: 't1', tool: 'get_report', status: 'running' } });
    expect(parseSse('event: tool_result\ndata: {"id":"t1","name":"get_report","is_error":false}')).toEqual({ type: 'step', step: { id: 't1', tool: 'get_report', status: 'done' } });
    expect(parseSse('event: web\ndata: {"name":"web_search"}')).toMatchObject({ type: 'step', step: { tool: 'web_search' } });
  });
  it('maps map_view, error and done', () => {
    expect(parseSse('event: map_view\ndata: {"layer":"gap","year":2020,"place_ids":["kyiv-obolon"]}')).toMatchObject({ type: 'map_view', view: { year: 2020 } });
    expect(parseSse('event: error\ndata: {"error":"rate_limited","message":"slow down"}')).toEqual({ type: 'error', code: 'rate_limited', message: 'slow down' });
    expect(parseSse('event: done\ndata: {"answer":"x"}')).toEqual({ type: 'done' });
    expect(parseSse('event: thinking\ndata: {"delta":"..."}')).toEqual({ type: 'thinking', text: '...' });
  });
  it('maps text_reset and validation (H4)', () => {
    expect(parseSse('event: text_reset\ndata: {"type":"text_reset"}')).toEqual({ type: 'reset' });
    expect(parseSse('event: validation\ndata: {"repairing":true,"ok":false,"unsourced":["5"]}')).toEqual({ type: 'validation', ok: false, repairing: true, caveats: 0, unsourced: ['5'] });
    expect(parseSse('event: done\ndata: {"answer":"x","validation":{"ok":false,"n_checked":3}}')).toEqual({ type: 'done', validationOk: false, unsourced: [] });
  });
  it('accepts plain-text deltas', () => {
    expect(parseSse('data: просто текст')).toEqual({ type: 'delta', text: 'просто текст' });
  });
});

describe('fetchRetry (RB-14)', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('retries a GET once after a network error', async () => {
    const ok = new Response('x');
    const f = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(ok);
    vi.stubGlobal('fetch', f);
    expect(await fetchRetry('/api/meta', undefined, 1)).toBe(ok);
    expect(f).toHaveBeenCalledTimes(2);
  });
  it('does not retry POST, aborts or HTTP errors', async () => {
    const f = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', f);
    await expect(fetchRetry('/api/analyze', { method: 'POST', body: '{}' }, 1)).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
    const ac = new AbortController(); ac.abort();
    await expect(fetchRetry('/api/meta', { signal: ac.signal }, 1)).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(2);
    const g = vi.fn().mockResolvedValue(new Response('no', { status: 502 }));
    vi.stubGlobal('fetch', g);
    expect((await fetchRetry('/api/meta', undefined, 1)).status).toBe(502);
    expect(g).toHaveBeenCalledTimes(1);
  });
});

describe('retrying tile URL', () => {
  it('keeps the {z}/{x}/{y} placeholders literal', () => {
    expect(retryingTileUrl('/tiles/gap/2025/{z}/{x}/{y}.png?theme=light&v=a%2Fb', 'http://h:8100'))
      .toBe('uhdt://http://h:8100/tiles/gap/2025/{z}/{x}/{y}.png?theme=light&v=a%2Fb');
    expect(retryingTileUrl('http://x/tiles/{z}/{x}/{y}.png')).toBe('uhdt://http://x/tiles/{z}/{x}/{y}.png');
  });
});

describe('country overview freshness', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('revalidates /api/overview and /api/overlays (server max-age=86400 must not pin a pre-deploy copy)', async () => {
    vi.resetModules();
    const f = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"places":[]}', { status: 200 })));
    vi.stubGlobal('fetch', f);
    const c = await import('./client');
    await c.getOverview(); await c.getOverlays();
    const calls = f.mock.calls.filter(([u]) => /\/api\/(overview|overlays)/.test(String(u)));
    expect(calls.length).toBe(2);
    for (const [, init] of calls) expect((init as RequestInit).cache).toBe('no-cache');
  });
});
