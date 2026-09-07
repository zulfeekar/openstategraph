import { describe, expect, it } from 'vitest';
import { NO_ENTRY_QUESTION, runIntent } from './runIntent';

/**
 * Ticket 21, verbatim: *"Clicking the toolbar Run button on `concierge` does
 * nothing at all — no panel, no toast, no error, nothing in console."*
 *
 * The cause was not a diagnostic, which is what the ticket suspected —
 * `WorkflowValidator.isRunnable` has no call site outside its own class. It
 * was `disabled={!canRun}` with `canRun = question !== ''`, and `concierge`'s
 * Text Input is deliberately blank because its question arrives at run time.
 * The wrapper `<span>` carries a tooltip explaining exactly that, and it
 * never appeared either: a `disabled` button dispatches no mouse events, so
 * neither the click nor the hover reached anything.
 *
 * The map's standard is "no gesture that silently does nothing". A refusal
 * may be correct; it may not be inaudible. So the button stays live and
 * answers, and *what* it answers is decided here rather than inside a React
 * closure — this repo has no component-test harness, and a rule that cannot
 * be tested is a rule that gets quietly re-broken.
 */
describe('runIntent', () => {
  it('runs the entry question when there is one', () => {
    expect(runIntent('Who are you?', false)).toEqual({
      kind: 'run',
      question: 'Who are you?',
    });
  });

  it('stops a run that is in flight, whatever the question says', () => {
    expect(runIntent('', true)).toEqual({ kind: 'stop' });
    expect(runIntent('Who are you?', true)).toEqual({ kind: 'stop' });
  });

  it('explains itself rather than doing nothing when there is no question', () => {
    expect(runIntent('', false)).toEqual({ kind: 'explain', reason: NO_ENTRY_QUESTION });
  });

  it('never returns a silent outcome — every press produces something', () => {
    for (const question of ['', '   ', 'ask me']) {
      for (const inFlight of [true, false]) {
        expect(['run', 'stop', 'explain']).toContain(runIntent(question, inFlight).kind);
      }
    }
  });

  it('treats whitespace as no question, the way entryQuestion does', () => {
    expect(runIntent('   ', false).kind).toBe('explain');
  });

  it('says where the question is meant to go, not merely that one is missing', () => {
    // A reason a developer can act on. "Nothing to run" would restate the
    // symptom; naming the Text Input node and Chat names the two ways out.
    expect(NO_ENTRY_QUESTION).toContain('Text Input');
    expect(NO_ENTRY_QUESTION).toContain('Chat');
  });
});
