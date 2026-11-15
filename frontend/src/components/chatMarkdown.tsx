import { Fragment, type ReactNode } from 'react';

/**
 * Tiny allow-listed markdown for analyst answers (CLAUDE-API-PLAN §5 «Output rendering»): paragraphs, «- » / «1. »
 * lists, **bold**, links with https: or uhd: only, and GFM pipe tables (header + `|---|` row; cells get the same
 * inline rules) — rendered as React elements (no HTML injection). Numbers the validator could not source are wrapped
 * in <mark>, also inside table cells.
 */
export type UhdLink = { kind: 'place' | 'report' | 'scene'; id: string };

const INLINE = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(((?:https:\/\/|uhd:)[^)\s]+)\)|(https:\/\/[^\s)]+)/g;

export function parseUhdHref(href: string): UhdLink | null {
  const m = /^uhd:(place|report|scene)\/([\w:.-]{1,80})$/.exec(href);
  return m ? { kind: m[1] as UhdLink['kind'], id: m[2]! } : null;
}

function marked(text: string, unsourced: string[], key: string): ReactNode[] {
  if (!unsourced.length) return [text];
  const esc = unsourced.filter(Boolean).map((u) => u.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!esc.length) return [text];
  const re = new RegExp(`(?<![\\d,.])(${esc.join('|')})(?![\\d])`, 'g');
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(<mark key={`${key}m${i++}`}>{m[0]}</mark>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function inline(text: string, ctx: Ctx, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  INLINE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = INLINE.exec(text))) {
    if (m.index > last) out.push(...marked(text.slice(last, m.index), ctx.unsourced, `${key}t${i}`));
    const k = `${key}i${i++}`;
    if (m[1] !== undefined) out.push(<b key={k}>{marked(m[1], ctx.unsourced, k)}</b>);
    else if (m[3] !== undefined) {
      const u = parseUhdHref(m[3]);
      if (u) out.push(<button key={k} type="button" className="chat-link" onClick={() => ctx.onLink?.(u)}>{m[2]}</button>);
      else if (m[3].startsWith('https://')) out.push(<a key={k} href={m[3]} target="_blank" rel="noopener noreferrer">{m[2]}</a>);
      else out.push(m[2]);
    } else if (m[4] !== undefined) {
      out.push(<a key={k} href={m[4]} target="_blank" rel="noopener noreferrer">{m[4]}</a>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...marked(text.slice(last), ctx.unsourced, `${key}e`));
  return out;
}

interface Ctx { unsourced: string[]; onLink?: (l: UhdLink) => void }

const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const MAX_TABLE_ROWS = 30;
const NUMERIC_CELL = /^[+−–-]?\s?\d[\d\s.,]*\s*(?:°\s*C|%|км²|km²)?$/;

/** Split a row on unescaped pipes, dropping the outer ones. */
export function splitRow(line: string): string[] {
  const s = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
}

function Table({ lines, ctx, k }: { lines: string[]; ctx: Ctx; k: string }) {
  const head = splitRow(lines[0]!);
  const n = head.length;
  const body = lines.slice(2, 2 + MAX_TABLE_ROWS).map((l) => {
    const c = splitRow(l);
    return Array.from({ length: n }, (_, i) => c[i] ?? '');
  });
  return (
    <div className="chat-table-wrap" tabIndex={0} role="region" aria-label={head.join(' · ')}>
      <table className="chat-table">
        <thead>
          <tr>{head.map((h, i) => <th key={i} scope="col">{inline(h, ctx, `${k}h${i}`)}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri}>
              {r.map((c, ci) => (
                <td key={ci} className={ci > 0 && NUMERIC_CELL.test(c.replace(/\*\*/g, '')) ? 'num' : undefined}>
                  {inline(c, ctx, `${k}r${ri}c${ci}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Segment = { table: boolean; lines: string[] };

/** A block may hold a paragraph and a table without a blank line between them: split it into runs. */
function segmentsOf(lines: string[]): Segment[] {
  const out: Segment[] = [];
  let i = 0;
  while (i < lines.length) {
    if (TABLE_ROW.test(lines[i]!) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]!)) {
      let j = i + 2;
      while (j < lines.length && TABLE_ROW.test(lines[j]!)) j++;
      out.push({ table: true, lines: lines.slice(i, j) });
      i = j;
    } else {
      const last = out[out.length - 1];
      if (last && !last.table) last.lines.push(lines[i]!);
      else out.push({ table: false, lines: [lines[i]!] });
      i++;
    }
  }
  return out;
}

function TextBlock({ lines, ctx, k }: { lines: string[]; ctx: Ctx; k: string }) {
  const isList = lines.length > 0 && lines.every((l) => /^\s*(?:[-*•]|\d{1,2}[.)])\s+/.test(l));
  if (isList) {
    const ordered = /^\s*\d/.test(lines[0]!);
    const items = lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*(?:[-*•]|\d{1,2}[.)])\s+/, ''), ctx, `${k}l${li}`)}</li>);
    return ordered ? <ol>{items}</ol> : <ul>{items}</ul>;
  }
  const heading = lines.length === 1 && /^#{1,4}\s+/.test(lines[0]!);
  if (heading) return <p className="chat-h">{inline(lines[0]!.replace(/^#{1,4}\s+/, ''), ctx, k)}</p>;
  return (
    <p>
      {lines.map((l, li) => (
        <Fragment key={li}>{li > 0 && <br />}{inline(l.replace(/^#{1,4}\s+/, ''), ctx, `${k}l${li}`)}</Fragment>
      ))}
    </p>
  );
}

export function ChatMarkdown({ text, unsourced = [], onLink }: { text: string; unsourced?: string[]; onLink?: (l: UhdLink) => void }) {
  const ctx: Ctx = { unsourced, onLink };
  const blocks = text.replace(/\r\n/g, '\n').split(/\n{2,}/).filter((b) => b.trim());
  return (
    <>
      {blocks.map((b, bi) =>
        segmentsOf(b.split('\n').filter((l) => l.trim())).map((seg, si) => {
          const k = `b${bi}s${si}`;
          return seg.table ? <Table key={k} lines={seg.lines} ctx={ctx} k={k} /> : <TextBlock key={k} lines={seg.lines} ctx={ctx} k={k} />;
        }),
      )}
    </>
  );
}
