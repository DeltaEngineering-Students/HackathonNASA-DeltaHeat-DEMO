import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent as RKeyboardEvent } from 'react';
import type { AgentStep, ChatMessage } from '../api/types';
import {
  AgentNotConfigured, AgentUnavailable, chat, getTeamToken, setTeamToken, verifyTeamToken,
  type ChatContext, type ChatEvent, type MapView,
} from '../api/client';
import { Close } from './icons';
import { persistable, chatKey, loadChat, saveChat, clearChat } from './chatMemory';
import { ChatMarkdown, type UhdLink } from './chatMarkdown';
import { CHECK_STEP, PLANNED_TOOLS, SUGGESTION_KEYS, errorText, say, toolLabel, type ChatKey } from './chatStrings';
import { useLocale, useT } from '../i18n';
import { nameEn } from '../i18n/placeName';
import { appendQuote, plainFromMarkdown, splitQuote, toQuote } from './chatQuote';
import './ChatPanel.css';

export { toolLabel };

export interface Turn extends ChatMessage {
  steps?: AgentStep[];
  warning?: string;
  thinking?: string;
  unsourced?: string[];
  /** true while the answer streams and its numbers are not yet checked */
  draft?: boolean;
}

/** Turns store dictionary keys (not text) for the panel's own messages, so a language switch re-renders them. */
export const UNSOURCED_WARNING: ChatKey = 'analyst.unsourcedWarning';
const CHECK = CHECK_STEP;

/**
 * Apply one agent event to the assistant turn being streamed (pure, tested).
 * `reset` (backend `text_reset`) drops the text streamed so far — the validator rejected it and a
 * corrected answer follows; `validation` shows up as a step; a final `done` with failed validation adds a warning
 * and the unsourced numbers (highlighted in the answer).
 */
export function applyChatEvent(turn: Turn, e: ChatEvent): Turn {
  const t: Turn = { ...turn, steps: [...(turn.steps ?? [])] };
  switch (e.type) {
    case 'delta':
      t.content += e.text;
      t.draft = true;
      break;
    case 'thinking':
      t.thinking = (t.thinking ?? '') + e.text;
      break;
    case 'reset':
      t.content = '';
      break;
    case 'step': {
      const i = t.steps!.findIndex((s) => (e.step.id ? s.id === e.step.id : s.tool === e.step.tool) && s.status === 'running');
      if (i >= 0) t.steps![i] = e.step; else t.steps!.push(e.step);
      break;
    }
    case 'validation':
      t.steps!.push({
        tool: CHECK, status: e.ok && !e.repairing ? 'done' : e.repairing ? 'running' : 'error',
        summary: e.ok && !e.repairing ? 'analyst.numbersOk' : e.repairing ? (e.ok && e.caveats ? 'analyst.caveatsRepairing' : 'analyst.numbersRepairing') : undefined,
      });
      break;
    case 'done':
      t.draft = false;
      t.steps = t.steps!.map((s) => (s.tool === CHECK && s.status === 'running'
        ? (e.validationOk === false ? { ...s, status: 'error' } : { ...s, status: 'done', summary: e.validationOk ? 'analyst.numbersOk' : s.summary })
        : s));
      if (e.validationOk === false) { t.warning = UNSOURCED_WARNING; t.unsourced = e.unsourced ?? []; }
      else if (e.validationOk === true && !t.steps.some((s) => s.tool === CHECK)) t.steps.push({ tool: CHECK, status: 'done', summary: 'analyst.numbersOk' });
      break;
    case 'error':
      // an unvalidated draft is never left on screen as if it were an answer
      t.draft = false;
      t.content = '';
      break;
    default:
      break;
  }
  return t;
}

function TeamMode({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [val, setVal] = useState('');
  const [state, setState] = useState<'idle' | 'checking' | 'wrong'>('idle');
  if (on) {
    return (
      <p className="chat-team xs" data-testid="team-on">
        <span>{t('analyst.teamOn')}</span>
        <button type="button" className="chat-link" onClick={() => { setTeamToken(null); onChange(false); }}>{t('analyst.teamOff')}</button>
      </p>
    );
  }
  if (!open) {
    return <p className="chat-team xs"><button type="button" className="chat-link" onClick={() => setOpen(true)}>{t('analyst.teamMode')}</button></p>;
  }
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const tok = val.trim();
    if (!tok) return;
    setState('checking');
    let ok = false;
    try { ok = await verifyTeamToken(tok); } catch { ok = false; }
    if (ok) { setTeamToken(tok); setVal(''); setOpen(false); setState('idle'); onChange(true); } else setState('wrong');
  };
  return (
    <form className="chat-team-form" onSubmit={(e) => void submit(e)} data-testid="team-form">
      <label className="sr-only" htmlFor="team-token">{t('analyst.teamPrompt')}</label>
      <input id="team-token" type="password" autoComplete="off" placeholder={t('analyst.teamPrompt')} value={val} onChange={(e) => setVal(e.target.value)} />
      <button type="submit" className="btn" disabled={state === 'checking' || !val.trim()}>{state === 'checking' ? t('analyst.teamChecking') : t('analyst.teamUnlock')}</button>
      <button type="button" className="chat-link" onClick={() => { setOpen(false); setState('idle'); }}>{t('analyst.teamCancel')}</button>
      <span className="xs" role={state === 'wrong' ? 'alert' : undefined}>{state === 'wrong' ? t('analyst.teamWrong') : t('analyst.teamHint')}</span>
    </form>
  );
}

export function ChatPanel({ context, zoneName, onClose, onMapView }: {
  context: ChatContext; zoneName: string; onClose: () => void;
  onMapView?: (v: MapView) => void;
}) {
  // one conversation per report (→ place → global), kept in localStorage; the key rides with the turns so a switch never cross-saves
  const key = chatKey(context);
  const [conv, setConv] = useState<{ key: string; turns: Turn[] }>(() => ({ key, turns: loadChat(key) as Turn[] }));
  if (conv.key !== key) setConv({ key, turns: loadChat(key) as Turn[] });
  const turns = conv.key === key ? conv.turns : (loadChat(key) as Turn[]);
  const setTurns = (f: (ts: Turn[]) => Turn[]) => setConv((c) => (c.key === key ? { key, turns: f(c.turns) } : c));
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [team, setTeam] = useState(() => !!getTeamToken());
  const l = useLocale();
  const tt = useT();
  const input = useRef<HTMLTextAreaElement>(null);
  const root = useRef<HTMLDivElement>(null);
  // the floating «Quote» button next to a text selection inside an assistant answer (position inside the panel)
  const [sel, setSel] = useState<{ text: string; x: number; y: number } | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const ac = useRef<AbortController | null>(null);

  useEffect(() => { input.current?.focus(); return () => ac.current?.abort(); }, []);
  useEffect(() => { ac.current?.abort(); setBusy(false); setError(null); setOffline(false); }, [key]);
  // persist final turns only: an in-flight / draft / empty assistant turn is dropped, so a reload mid-answer leaves the user message alone
  useEffect(() => { if (conv.key === key) saveChat(key, persistable(conv.turns)); }, [conv, key]);
  useEffect(() => { if (!busy) input.current?.focus(); }, [busy]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight }); }, [turns, offline, error]);

  const quoteInto = useCallback((md: string) => {
    const q = toQuote(md);
    if (!q) return;
    setText((cur) => appendQuote(cur, q));
    setSel(null);
    window.getSelection()?.removeAllRanges();
    requestAnimationFrame(() => { const el = input.current; if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } });
  }, []);
  // the selection must sit inside ONE assistant answer; the button follows the end of the selection
  useEffect(() => {
    const read = () => {
      const s = window.getSelection();
      const box = root.current;
      if (!s || s.isCollapsed || s.rangeCount === 0 || !box) { setSel(null); return; }
      const inMd = (n: Node | null) => (n instanceof Element ? n : n?.parentElement)?.closest('.msg.assistant .chat-md') ?? null;
      const a = inMd(s.anchorNode);
      if (!a || a !== inMd(s.focusNode)) { setSel(null); return; }
      const text = s.toString().trim();
      if (!text) { setSel(null); return; }
      const r = s.getRangeAt(0).getBoundingClientRect();
      const b = box.getBoundingClientRect();
      setSel({ text, x: Math.max(8, Math.min(b.width - 96, r.right - b.left - 40)), y: Math.max(8, r.top - b.top - 40) });
    };
    document.addEventListener('selectionchange', read);
    return () => document.removeEventListener('selectionchange', read);
  }, []);

  const onLink = (l: UhdLink) => {
    if (l.kind === 'place') onMapView?.({ place_ids: [l.id] });
    else if (l.kind === 'report') onMapView?.({ report_ids: [l.id] });
  };

  const send = async (q: string) => {
    const msg = q.trim();
    if (!msg || busy) return;
    setText('');
    setError(null);
    setOffline(false);
    // an unanswered earlier user message (interrupted / failed) is dropped from the request: the API wants alternating roles
    const prior = turns.filter((t) => t.content).map(({ role, content }) => ({ role, content }));
    while (prior.length && prior[prior.length - 1]!.role === 'user') prior.pop();
    const history: ChatMessage[] = [...prior, { role: 'user', content: msg }];
    setTurns((ts) => [...ts.filter((t) => t.role === 'user' || t.content), { role: 'user', content: msg }, { role: 'assistant', content: '', steps: [] }]);
    setBusy(true);
    ac.current = new AbortController();
    try {
      const signal = ac.current.signal;
      await chat(history, { ...context, lang: l }, (e) => {
        if (signal.aborted) return;
        if (e.type === 'map_view') { onMapView?.(e.view); return; }
        if (e.type === 'error') setError(errorText(e.code, l));
        setTurns((ts) => {
          const copy = [...ts];
          copy[copy.length - 1] = applyChatEvent(copy[copy.length - 1]!, e);
          return copy;
        });
      }, ac.current.signal);
    } catch (e) {
      setTurns((ts) => ts.filter((t, i) => !(t.role === 'assistant' && !t.content && i === ts.length - 1)));
      if (e instanceof AgentNotConfigured) setOffline(true);
      else if (e instanceof AgentUnavailable) setError(errorText(e.code, l));
      else if ((e as Error).name !== 'AbortError') setError(errorText('network', l));
    } finally {
      setBusy(false);
    }
  };

  // Enter sends, Shift+Enter is a new line (a quote is multi-line)
  const onInputKey = (e: RKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(text); }
  };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); void send(text); };
  const last = turns.length - 1;

  return (
    <div className="card chat" ref={root} role="dialog" aria-modal="false" aria-labelledby="chat-title" data-testid="chat">
      <div className="chat-head">
        <h2 id="chat-title">{tt('analyst.title')}</h2>
        {turns.length > 0 && (
          <button type="button" className="chat-link" data-testid="chat-new" onClick={() => { ac.current?.abort(); setBusy(false); setError(null); clearChat(key); setConv({ key, turns: [] }); }}>{tt('analyst.newChat')}</button>
        )}
        <button type="button" className="pill icon-btn" style={{ boxShadow: 'none' }} aria-label={tt('analyst.close')} onClick={onClose}><Close /></button>
      </div>
      <p className="s" style={{ marginTop: 6 }}>{tt('analyst.intro', { zone: l === 'en' ? nameEn(zoneName) : zoneName })}</p>
      <TeamMode on={team} onChange={setTeam} />
      <div className="chat-body" ref={body} aria-live="polite" aria-busy={busy}>
        {turns.length === 0 && !offline && (
          <div className="chips">
            {SUGGESTION_KEYS.map((k) => <button key={k} type="button" className="chip" onClick={() => void send(tt(k))}>{tt(k)}</button>)}
          </div>
        )}
        {turns.map((t, i) => (
          (t.role === 'user' || t.content || (t.steps?.length ?? 0) > 0 || (busy && i === last)) && (
          <div key={i} className={`msg ${t.role}${t.draft ? ' draft' : ''}`} data-testid={t.role === 'assistant' ? 'chat-answer' : undefined}>
            {t.role === 'assistant'
              ? (t.content ? <div className="chat-md"><ChatMarkdown text={t.content} unsourced={t.unsourced} onLink={onLink} /></div> : (busy && i === last ? tt('analyst.thinking') : ''))
              : <UserText content={t.content} />}
            {t.role === 'assistant' && t.content && !t.draft && (
              <button type="button" className="chat-reply xs" data-testid="chat-reply" aria-label={tt('analyst.replyLabel')} title={tt('analyst.replyLabel')}
                onClick={() => quoteInto(plainFromMarkdown(t.content))}>↩ {tt('analyst.reply')}</button>
            )}
            {t.draft && busy && i === last && <span className="chat-draft xs">{tt('analyst.draft')}</span>}
            {t.steps && t.steps.length > 0 && (
              <ul className="steps" style={{ marginTop: 8 }} aria-label={tt('analyst.stepsLabel')}>
                {t.steps.map((s, k) => <li key={k} title={s.tool}><span className={`dot ${s.status}`} /><b className="step-name">{toolLabel(s.tool, l)}</b>{s.summary && <span>{say(s.summary, l)}</span>}</li>)}
              </ul>
            )}
            {t.thinking && t.thinking.trim() && (
              <details className="chat-reasoning xs" open={team && i === last && busy}>
                <summary>{tt('analyst.reasoning')}</summary>
                <p>{t.thinking}</p>
              </details>
            )}
            {t.warning && <p className="chat-warn" role="alert">{say(t.warning, l)}</p>}
          </div>)
        ))}
        {!busy && turns.length > 0 && turns[last]!.role === 'user' && !error && !offline && (
          <p className="xs" data-testid="chat-interrupted" role="status">{tt('analyst.interrupted')}</p>
        )}
        {offline && (
          <div className="offline" data-testid="agent-offline" role="status">
            <h3>{tt('analyst.offlineTitle')}</h3>
            <p className="s">{tt('analyst.offlineText')}</p>
            <ul className="steps" style={{ marginTop: 10 }} aria-label={tt('analyst.offlinePlannedLabel')}>
              {PLANNED_TOOLS.map((id) => <li key={id}><span className="dot" /><span>{tt(`analyst.plan.${id}`)}</span></li>)}
            </ul>
            <details className="xs" style={{ marginTop: 8 }}>
              <summary>{tt('analyst.offlineToolIds')}</summary>
              <p style={{ marginTop: 4 }}>{PLANNED_TOOLS.join(', ')}</p>
            </details>
          </div>
        )}
        {error && <p className="s chat-error" role="alert" data-testid="chat-error">{error}</p>}
      </div>
      <form className="chat-form" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor="chat-input">{tt('analyst.inputLabel')}</label>
        <textarea id="chat-input" ref={input} rows={text.includes('\n') ? Math.min(6, text.split('\n').length) : 1} value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={onInputKey} placeholder={tt('analyst.placeholder')} disabled={busy} autoComplete="off" />
        <button type="submit" className="btn" style={{ height: 44 }} disabled={busy || !text.trim()}>{tt('analyst.send')}</button>
      </form>
      {sel && (
        <button type="button" className="chat-quote-btn" data-testid="chat-quote" style={{ left: sel.x, top: sel.y }} aria-label={tt('analyst.quoteLabel')}
          onMouseDown={(e) => e.preventDefault()} onClick={() => quoteInto(sel.text)}>❝ {tt('analyst.quote')}</button>
      )}
    </div>
  );
}

/** A user bubble: a leading «> …» block is shown as a quote, the rest as the question. */
function UserText({ content }: { content: string }) {
  const { quote, rest } = splitQuote(content);
  if (quote == null) return <>{content}</>;
  return (<>
    <blockquote className="msg-quote" data-testid="msg-quote">{quote}</blockquote>
    {rest && <span className="msg-rest">{rest}</span>}
  </>);
}
