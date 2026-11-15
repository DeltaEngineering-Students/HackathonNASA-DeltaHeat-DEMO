// Quote / reply in the analyst chat: the quote goes into the input as Markdown blockquote lines («> …») plus an empty line,
// and rides in the user message as plain text. The backend validator treats the user's message as a source of numbers.

export const QUOTE_MAX = 300;

/** Markdown of an assistant answer → plain text for quoting (links keep their label, emphasis markers go). */
export function plainFromMarkdown(md: string): string {
  return md
    .replace(/\[([^\]]+)\]\((?:uhd:|https?:)[^)]*\)/g, '$1')
    .replace(/^#{1,6}[ \t]+/gm, '')
    .replace(/(\*\*|__)(.+?)\1/g, '$2')
    .replace(/^[ \t]*[-*][ \t]+/gm, '• ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** `> ` before every line; the text is cut at a word boundary to `max` characters with «…». Ends with an empty line. */
export function toQuote(text: string, max = QUOTE_MAX): string {
  let t = text.replace(/\r/g, '').trim();
  if (!t) return '';
  if (t.length > max) {
    const cut = t.slice(0, max);
    const sp = cut.lastIndexOf(' ');
    t = `${(sp > max * 0.6 ? cut.slice(0, sp) : cut).trimEnd()}…`;
  }
  return `${t.split('\n').map((ln) => (ln.trim() ? `> ${ln}` : '>')).join('\n')}\n\n`;
}

/** The text already in the input + a new quote: the quote goes after it, separated by an empty line. */
export const appendQuote = (current: string, quote: string) => (current.trim() ? `${current.trimEnd()}\n\n${quote}` : quote);

/** A user message → its leading blockquote (without «> ») and the rest. Only a leading block counts as a quote. */
export function splitQuote(content: string): { quote: string | null; rest: string } {
  const lines = content.split('\n');
  let i = 0;
  while (i < lines.length && /^>/.test(lines[i]!)) i++;
  if (i === 0) return { quote: null, rest: content };
  const quote = lines.slice(0, i).map((ln) => ln.replace(/^>\s?/, '')).join('\n').trim();
  return { quote: quote || null, rest: lines.slice(i).join('\n').replace(/^\n+/, '') };
}
