import { AgentNotConfigured, AgentUnavailable, chat, setTeamToken, type ChatEvent } from './client';

const sse = (blocks: string[]) => new Response(blocks.join('\n\n') + '\n\n', { headers: { 'content-type': 'text/event-stream' } });

describe('chat client', () => {
  afterEach(() => { vi.restoreAllMocks(); setTeamToken(null); });
  it('distinguishes 503 not configured / budget / 429', async () => {
    const f = vi.spyOn(globalThis, 'fetch');
    f.mockResolvedValueOnce(new Response(JSON.stringify({ error: 'agent_not_configured' }), { status: 503 }));
    await expect(chat([{ role: 'user', content: 'x' }], {}, () => {})).rejects.toBeInstanceOf(AgentNotConfigured);
    f.mockResolvedValueOnce(new Response(JSON.stringify({ error: 'agent_budget_exhausted' }), { status: 503 }));
    await expect(chat([{ role: 'user', content: 'x' }], {}, () => {})).rejects.toMatchObject({ code: 'agent_budget_exhausted' });
    f.mockResolvedValueOnce(new Response(JSON.stringify({ error: 'rate_limited' }), { status: 429 }));
    const e = await chat([{ role: 'user', content: 'x' }], {}, () => {}).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(AgentUnavailable);
    expect(e).not.toBeInstanceOf(AgentNotConfigured);
    expect((e as AgentUnavailable).code).toBe('rate_limited');
  });
  it('sends the team token only when team mode is on, and streams events', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(sse(['event: text\ndata: {"delta":"Привіт"}', 'event: done\ndata: {"validation":{"ok":true}}']));
    const evs: ChatEvent[] = [];
    await chat([{ role: 'user', content: 'x' }], {}, (e) => evs.push(e));
    expect((f.mock.calls[0]![1]!.headers as Record<string, string>)['X-UHD-Team-Token']).toBeUndefined();
    expect(evs.map((e) => e.type)).toEqual(['delta', 'done']);
    setTeamToken('secret-team');
    f.mockResolvedValue(sse(['event: done\ndata: {}']));
    await chat([{ role: 'user', content: 'x' }], {}, () => {});
    expect((f.mock.calls[1]![1]!.headers as Record<string, string>)['X-UHD-Team-Token']).toBe('secret-team');
  });
});
