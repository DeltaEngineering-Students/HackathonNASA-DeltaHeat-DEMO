import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Hint, Term, placeBubble, useHint } from './Hint';
import { GLOSSARY } from '../lib/glossary';

describe('<Term> / <Hint> (item 22)', () => {
  it('focus shows a tooltip with the glossary text; Esc hides it and does not reach the app', async () => {
    const user = userEvent.setup();
    // app-level Esc handlers (Details, card, chat) must see it as handled: stopped, or at least defaultPrevented
    const seen: boolean[] = [];
    const appEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') seen.push(e.defaultPrevented); };
    window.addEventListener('keydown', appEsc);
    render(<p>Це <Term k="gap">розрив</Term></p>);
    const t = screen.getByRole('button', { name: 'розрив' });
    expect(t).toHaveAccessibleDescription(GLOSSARY.gap.short); // reachable without hover
    await user.tab();
    expect(t).toHaveFocus();
    expect(screen.getByRole('tooltip')).toHaveTextContent(GLOSSARY.gap.short);
    expect(t).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).toBeNull();
    expect(seen.every(Boolean)).toBe(true);
    window.removeEventListener('keydown', appEsc);
  });
  it('one tip at a time; «Детальніше» turns it into a dialog with «see also» links in the same bubble', async () => {
    const user = userEvent.setup();
    render(<div><Hint k="gap" /><Hint k="pValue" /></div>);
    const [a, b] = screen.getAllByRole('button', { name: /^Що таке:/ });
    await user.click(a!);
    expect(screen.getAllByRole('tooltip')).toHaveLength(1);
    await user.click(b!);
    expect(screen.getAllByRole('tooltip')).toHaveLength(1);
    expect(screen.getByRole('tooltip')).toHaveTextContent(GLOSSARY.pValue.term);
    await user.click(a!);
    await user.click(screen.getByRole('button', { name: 'Детальніше' }));
    const dlg = screen.getByRole('dialog', { name: GLOSSARY.gap.term });
    expect(dlg).toHaveTextContent(GLOSSARY.gap.more!);
    await user.click(screen.getByRole('button', { name: GLOSSARY.referenceForest.term }));
    expect(screen.getAllByTestId('tip')).toHaveLength(1);
    expect(screen.getByTestId('tip')).toHaveTextContent(GLOSSARY.referenceForest.short);
  });
  it('touch: tap toggles, tap outside closes; the tap does not reach the parent', () => {
    const parent = vi.fn();
    render(<div><div onClick={parent}><Hint k="ndvi" /></div><span>outside</span></div>);
    const h = screen.getByRole('button', { name: /^Що таке:/ });
    const tap = (el: Element) => { fireEvent.pointerDown(el, { pointerType: 'touch' }); fireEvent.click(el, { pointerType: 'touch' }); };
    act(() => tap(h));
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    expect(parent).not.toHaveBeenCalled();
    act(() => tap(h));
    expect(screen.queryByRole('tooltip')).toBeNull();
    act(() => tap(h));
    act(() => { fireEvent.pointerDown(screen.getByText('outside'), { pointerType: 'touch' }); });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
  it('placement flips and stays 8 px inside the viewport', () => {
    const b = { width: 280, height: 100 };
    expect(placeBubble({ left: 10, top: 850, right: 30, bottom: 870 }, b, 1440, 900, 'below')).toMatchObject({ side: 'above', left: 8 });
    expect(placeBubble({ left: 1430, top: 100, right: 1440, bottom: 120 }, b, 1440, 900, 'below')).toMatchObject({ side: 'below', left: 1440 - 280 - 8, top: 126 });
    expect(placeBubble({ left: 1380, top: 300, right: 1420, bottom: 340 }, b, 1440, 900, 'left')).toMatchObject({ side: 'left', left: 1380 - 8 - 280 });
  });
  it('useHint: an existing tool button gets a keyboard tip; its own click still works and does not open the tip', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    function Tool() {
      const tip = useHint('zoom', 'left');
      return <><button ref={tip.ref} {...tip.props} aria-label="Наблизити" onClick={onClick}>+</button>{tip.node}</>;
    }
    render(<Tool />);
    const b = screen.getByRole('button', { name: 'Наблизити' });
    expect(b).toHaveAccessibleDescription(GLOSSARY.zoom.short);
    await user.tab();
    expect(screen.getByRole('tooltip')).toHaveTextContent(GLOSSARY.zoom.short);
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).toBeNull();
    b.blur();
    await user.click(b);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
