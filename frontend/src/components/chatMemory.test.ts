import { beforeEach, describe, expect, it, vi } from 'vitest';
import { persistable, chatKey, clearChat, loadChat, saveChat, MAX_CONVERSATIONS, MAX_TURNS, type StoredTurn } from './chatMemory';

const u = (c: string): StoredTurn => ({ role: 'user', content: c });
const a = (c: string): StoredTurn => ({ role: 'assistant', content: c });

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('chat memory', () => {
  it('keys: report → place → global', () => {
    expect(chatKey({ report_id: 'r1', place_id: 'p' })).toBe('uhd-chat:r1');
    expect(chatKey({ report_id: null, place_id: 'p' })).toBe('uhd-chat:p');
    expect(chatKey({})).toBe('uhd-chat:global');
  });
  it('saves and loads per report, versioned', () => {
    saveChat('uhd-chat:r1', [u('q'), { ...a('ans'), steps: [{ tool: 't', status: 'done', summary: 's' }], warning: 'w', unsourced: ['9'] }]);
    saveChat('uhd-chat:r2', [u('other')]);
    expect(JSON.parse(localStorage.getItem('uhd-chat:r1')!).v).toBe(1);
    expect(loadChat('uhd-chat:r1')).toEqual([u('q'), { ...a('ans'), steps: [{ tool: 't', status: 'done', summary: 's' }], warning: 'w', unsourced: ['9'] }]);
    expect(loadChat('uhd-chat:r2')).toEqual([u('other')]);
  });
  it('drops unfinished answers and running steps, never stores thinking', () => {
    saveChat('k', [u('q'), { ...a(''), steps: [] }]);
    expect(loadChat('k')).toEqual([u('q')]);
    saveChat('k', [u('q'), { ...a('x'), thinking: 'secret', steps: [{ tool: 't', status: 'running' }] } as StoredTurn]);
    expect(loadChat('k')).toEqual([u('q'), a('x')]);
    expect(localStorage.getItem('k')).not.toContain('secret');
  });
  it('keeps the last 40 turns', () => {
    saveChat('k', Array.from({ length: 60 }, (_, i) => u(`m${i}`)));
    const t = loadChat('k');
    expect(t).toHaveLength(MAX_TURNS);
    expect(t[0]!.content).toBe('m20');
  });
  it('evicts the least recently used conversation beyond 30', () => {
    for (let i = 0; i < MAX_CONVERSATIONS; i++) saveChat(`c${i}`, [u('x')]);
    saveChat('c0', [u('x'), a('y')]); // touch c0 → c1 is now the oldest
    saveChat('new', [u('x')]);
    expect(loadChat('c1')).toEqual([]);
    expect(loadChat('c0')).toHaveLength(2);
    expect(loadChat('new')).toHaveLength(1);
    expect(JSON.parse(localStorage.getItem('uhd-chat-index')!).keys).toHaveLength(MAX_CONVERSATIONS);
  });
  it('ignores corrupt or foreign data', () => {
    for (const raw of ['{', 'null', '[]', '{"v":2,"t":[]}', '{"v":1,"t":"x"}', '{"v":1,"t":[{"role":"system","content":"x"}]}', '{"v":1,"t":[{"role":"user","content":5}]}']) {
      localStorage.setItem('k', raw);
      expect(loadChat('k')).toEqual([]);
    }
    localStorage.setItem('uhd-chat-index', 'garbage');
    expect(() => saveChat('k', [u('q')])).not.toThrow();
    expect(loadChat('k')).toEqual([u('q')]);
  });
  it('clear removes the conversation and its index entry', () => {
    saveChat('k', [u('q')]);
    clearChat('k');
    expect(localStorage.getItem('k')).toBeNull();
    expect(JSON.parse(localStorage.getItem('uhd-chat-index')!).keys).toEqual([]);
  });
  it('a throwing storage (quota / private mode) neither throws nor persists', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('full', 'QuotaExceededError'); });
    expect(() => saveChat('k', [u('q')])).not.toThrow();
    vi.restoreAllMocks();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
    expect(loadChat('k')).toEqual([]);
  });
  it('mid-stream reload: the user message is restored, no fake answer', () => {
    saveChat('k', persistable([u('old'), a('done'), u('pending'), { ...a('half'), draft: true }, ]));
    expect(loadChat('k')).toEqual([u('old'), a('done'), u('pending')]);
    saveChat('k', persistable([u('q'), { ...a(''), steps: [{ tool: 't', status: 'running' }] }]));
    expect(loadChat('k')).toEqual([u('q')]);
  });
});
