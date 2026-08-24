import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

/**
 * `launch-readiness` 31 — "Ask the workflow" does nothing and says nothing.
 *
 * The stranger clicked the toolbar's "Ask the workflow" button on a fresh
 * install with nothing saved or published: "Nothing. No panel, no toast, no
 * disabled state, no cursor change, no explanation." That toggle itself
 * could not be reproduced dead here — it is wired unconditionally
 * (`onAskToggle`, pinned by `topbarSurface.test.ts`) and opens the panel in
 * every state this session tried: a published workflow, an unsaved draft, and
 * a brand-new zero-node canvas.
 *
 * What *is* silent, one level in: the panel's own composer. Its Send button
 * was `disabled={question.trim() === ''}` with no `Tooltip` around it — the
 * exact anti-pattern `runIntent.ts` names and fixed for the toolbar's Run
 * button (ticket 21): "A disabled button dispatches no mouse events... The
 * one explanation that existed was reachable only by someone who did not need
 * it." Pressing Enter on an empty composer, or clicking a Send that looks
 * identical to a working one, produced nothing — no toast, no reason, exactly
 * the shape CLAUDE.md forbids by name.
 *
 * This is the sibling sweep the ticket itself asked for: "any toolbar control
 * whose precondition is 'something is saved' and which currently no-ops
 * instead of saying so." The fix taken here is the cheaper of the two the
 * ticket allows — disabled, with the reason on hover — because unlike Run's
 * entry question (which the workflow states on the developer's behalf), an
 * empty composer has no fallback value to fall through to: there is
 * genuinely nothing to send, so staying disabled is correct, and the bug was
 * only the silence around it.
 *
 * Source-based, in the idiom of `composerHoldsAMultiLineBrief.test.ts`: this
 * repo's vitest config has no component-test harness, so a rule that lives
 * only inside a React closure is a rule with no test.
 */
const SOURCE = readFileSync(new URL('./AskPanel.tsx', import.meta.url), 'utf8');

/** The composer's Send/Stop control, not another button in the same file. */
function sendElement(): string {
  const start = SOURCE.indexOf('className="ask__composer-send"');
  expect(start).toBeGreaterThan(-1);
  const open = SOURCE.lastIndexOf('<Button', start);
  const close = SOURCE.indexOf('</Button>', start);
  expect(open).toBeGreaterThan(-1);
  expect(close).toBeGreaterThan(-1);
  return SOURCE.slice(open, close + '</Button>'.length);
}

/** Everything from the nearest `<Tooltip` before the button to its `</Tooltip>`. */
function sendTooltip(): string {
  const buttonStart = SOURCE.indexOf('className="ask__composer-send"');
  expect(buttonStart).toBeGreaterThan(-1);
  const tooltipStart = SOURCE.lastIndexOf('<Tooltip', buttonStart);
  expect(tooltipStart).toBeGreaterThan(-1);
  const tooltipEnd = SOURCE.indexOf('</Tooltip>', buttonStart);
  expect(tooltipEnd).toBeGreaterThan(-1);
  return SOURCE.slice(tooltipStart, tooltipEnd + '</Tooltip>'.length);
}

describe('the Ask composer Send control', () => {
  it('stays disabled when there is nothing typed — a real refusal, not a bug', () => {
    const element = sendElement();
    expect(element).toMatch(/disabled=\{running \? false : question\.trim\(\) === ''\}/);
  });

  it('wraps the button in a Tooltip, so the refusal is audible on hover', () => {
    const tooltip = sendTooltip();
    // The same element the disabled test above inspects, so a rewrite that
    // moves the Tooltip away from this button — rather than removing it —
    // still fails here.
    expect(tooltip).toContain('ask__composer-send');
  });

  it('names what is missing, in the tooltip content, rather than staying blank', () => {
    const tooltip = sendTooltip();
    expect(tooltip).toMatch(/Type a question/i);
  });
});
