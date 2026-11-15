// The analyst's conversation history lives in this browser only (localStorage), one conversation per report.
// Stored: final user/assistant text turns (+ tool-step summary, validation warning). Never: errors, in-flight
// streams, reasoning, the team token. Every access is wrapped: private mode / a full quota simply doesn't persist.
import type { AgentStep } from '../api/types';

export interface StoredTurn {
  role: 'user' | 'assistant';
  content: string;
  steps?: AgentStep[];
  warning?: string;
  unsourced?: string[];
}

export const MAX_TURNS = 40;
export const MAX_CONVERSATIONS = 30;
const PREFIX = 'uhd-chat:';
const INDEX = 'uhd-chat-index';
const MAX_CONTENT = 20_000;

/** report → place → global */
export function chatKey(ctx: { report_id?: string | null; place_id?: string | null }): string {
  return PREFIX + (ctx.report_id || ctx.place_id || 'global');
}

const store = (): Storage | null => { try { return window.localStorage; } catch { return null; } };

function readIndex(s: Storage): string[] {
  try {
    const o = JSON.parse(s.getItem(INDEX) ?? 'null') as { v?: number; keys?: unknown } | null;
    if (o?.v === 1 && Array.isArray(o.keys)) return o.keys.filter((k): k is string => typeof k === 'string');
  } catch { /* corrupt index → rebuilt */ }
  return [];
}

const str = (x: unknown): x is string => typeof x === 'string';

function cleanStep(x: unknown): AgentStep | null {
  const s = x as Partial<AgentStep> | null;
  if (!s || !str(s.tool) || (s.status !== 'done' && s.status !== 'error')) return null; // a stored 'running' step is stale
  return { ...(str(s.id) ? { id: s.id } : {}), tool: s.tool, status: s.status, ...(str(s.summary) ? { summary: s.summary } : {}) };
}

function cleanTurn(x: unknown): StoredTurn | null {
  const t = x as Partial<StoredTurn> | null;
  if (!t || (t.role !== 'user' && t.role !== 'assistant') || !str(t.content) || t.content.length > MAX_CONTENT) return null;
  const steps = Array.isArray(t.steps) ? t.steps.map(cleanStep).filter((s): s is AgentStep => !!s) : [];
  const out: StoredTurn = { role: t.role, content: t.content };
  if (t.role === 'assistant') {
    if (!t.content) return null; // an unfinished answer is never stored
    if (steps.length) out.steps = steps;
    if (str(t.warning)) out.warning = t.warning;
    if (Array.isArray(t.unsourced)) out.unsourced = t.unsourced.filter(str);
  }
  return out;
}

export function loadChat(key: string): StoredTurn[] {
  const s = store();
  if (!s) return [];
  try {
    const raw = s.getItem(key);
    if (!raw) return [];
    const o = JSON.parse(raw) as { v?: number; t?: unknown };
    if (o?.v !== 1 || !Array.isArray(o.t)) return [];
    const turns = o.t.map(cleanTurn);
    if (turns.some((t) => !t)) return []; // any bad element → ignore the whole record
    return (turns as StoredTurn[]).slice(-MAX_TURNS);
  } catch { return []; }
}

export function saveChat(key: string, turns: StoredTurn[]): void {
  const s = store();
  if (!s) return;
  try {
    const clean = turns.map(cleanTurn).filter((t): t is StoredTurn => !!t).slice(-MAX_TURNS);
    let keys = readIndex(s).filter((k) => k !== key);
    if (!clean.length) {
      s.removeItem(key);
      s.setItem(INDEX, JSON.stringify({ v: 1, keys }));
      return;
    }
    keys.push(key); // most recently used last
    while (keys.length > MAX_CONVERSATIONS) { const old = keys.shift()!; if (old !== key) s.removeItem(old); }
    s.setItem(key, JSON.stringify({ v: 1, t: clean }));
    s.setItem(INDEX, JSON.stringify({ v: 1, keys }));
  } catch { /* private mode / quota: the history just isn't kept */ }
}

export function clearChat(key: string): void { saveChat(key, []); }

/** What of a live conversation may be stored: user turns and finished answers (no draft, no empty in-flight turn). */
export function persistable<T extends StoredTurn & { draft?: boolean }>(turns: T[]): T[] {
  return turns.filter((t) => t.role === 'user' || (!!t.content && !t.draft));
}
