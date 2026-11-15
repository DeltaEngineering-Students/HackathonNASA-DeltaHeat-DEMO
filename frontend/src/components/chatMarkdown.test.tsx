import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatMarkdown, parseUhdHref, splitRow } from './chatMarkdown';

describe('chat markdown (allow-listed)', () => {
  it('renders paragraphs, bold, lists and safe links only', () => {
    const { container } = render(<ChatMarkdown text={'**Факти з даних**\n\n- перше\n- друге\n\nДив. [джерело](https://uk.wikipedia.org/wiki/Київ) і [погане](javascript:alert(1)) <img src=x onerror=alert(1)>'} />);
    expect(container.querySelector('b')!.textContent).toBe('Факти з даних');
    expect(container.querySelectorAll('li')).toHaveLength(2);
    const a = screen.getByRole('link', { name: 'джерело' });
    expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    expect(container.querySelector('img')).toBeNull(); // raw HTML stays text
    expect(container.innerHTML).not.toContain('href="javascript');
  });
  it('uhd: links become buttons and unsourced numbers are marked', async () => {
    const seen: unknown[] = [];
    const { container } = render(<ChatMarkdown text={'Розрив 7,7 °C, а не 17,7 [на мапі](uhd:place/kyiv-pozniaky)'} unsourced={['7,7']} onLink={(l) => seen.push(l)} />);
    expect([...container.querySelectorAll('mark')].map((m) => m.textContent)).toEqual(['7,7']);
    await userEvent.click(screen.getByRole('button', { name: 'на мапі' }));
    expect(seen).toEqual([{ kind: 'place', id: 'kyiv-pozniaky' }]);
    expect(parseUhdHref('uhd:report/0123456789abcdef')).toEqual({ kind: 'report', id: '0123456789abcdef' });
    expect(parseUhdHref('uhd:evil/x')).toBeNull();
  });

  it('GFM tables: header, numeric cells, inline rules and marks inside cells, no HTML', async () => {
    const seen: unknown[] = [];
    const text = [
      'Порівняння районів:',
      '| Район | Середній розрив, °C | Тренд, °C/10 р. |',
      '|---|---:|---|',
      '| [Оболонський](uhd:place/kyiv-obolonskyi) | 9,38 | **+0,31** |',
      '| <img src=x onerror=alert(1)> | 9,52 | −0,12 |',
      '',
      'Висновок.',
    ].join('\n');
    const { container } = render(<ChatMarkdown text={text} unsourced={['9,52']} onLink={(l) => seen.push(l)} />);
    const table = container.querySelector('.chat-table-wrap table')!;
    expect(table).not.toBeNull();
    expect([...table.querySelectorAll('th')].map((t) => t.textContent)).toEqual(['Район', 'Середній розрив, °C', 'Тренд, °C/10 р.']);
    expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(table.querySelector('tbody tr td.num')!.textContent).toBe('9,38');
    expect(table.querySelector('b')!.textContent).toBe('+0,31');
    expect(table.querySelector('mark')!.textContent).toBe('9,52');
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('Порівняння районів:').tagName).toBe('P');
    expect(screen.getByText('Висновок.').tagName).toBe('P');
    await userEvent.click(screen.getByRole('button', { name: 'Оболонський' }));
    expect(seen).toEqual([{ kind: 'place', id: 'kyiv-obolonskyi' }]);
  });

  it('pipes without a separator row stay text; splitRow trims and drops outer pipes', () => {
    const { container } = render(<ChatMarkdown text={'a | b\n| c |'} />);
    expect(container.querySelector('table')).toBeNull();
    expect(splitRow('| a | b \\| c |')).toEqual(['a', 'b | c']);
  });
});
