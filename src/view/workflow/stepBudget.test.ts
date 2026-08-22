import { describe, expect, it } from 'vitest';
import { makeWorkbench } from '@core/testing/fixtures';
import {
  STEP_BUDGET_DEFAULT,
  STEP_BUDGET_HINT,
  STEP_BUDGET_KEY,
  STEP_BUDGET_LABEL,
  STEP_BUDGET_MAX,
  STEP_BUDGET_MIN,
  STEP_BUDGET_PLACEHOLDER,
  parseStepBudget,
  readStepBudget,
} from './stepBudget';

/**
 * `workflow-gallery` 58 — the write half of the step budget.
 *
 * 26 made a document's `settings.recursionLimit` reach the graph config on
 * every surface, and left the number reachable only by hand-editing
 * `workflow.json`. These tests are the write half, and they are deliberately
 * *not* "the setter was called": they drive the gesture through the command
 * stack and assert on the bytes a saved document would carry, because those
 * bytes are what `backend/openstategraph/step_budget.py` reads.
 */
describe('the step budget a document saves', () => {
  it('writes the exact key the runtime reads', () => {
    // `workflow_step_budget` looks for `recursionLimit` (then
    // `recursion_limit`). A rename on this side is a silent no-op on that one.
    const workbench = makeWorkbench();
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, 200);

    const parsed = JSON.parse(workbench.controller.document.exportJSON()) as {
      settings?: Record<string, unknown>;
    };
    expect(STEP_BUDGET_KEY).toBe('recursionLimit');
    expect(parsed.settings).toEqual({ recursionLimit: 200 });
  });

  it('survives a save and a reload', () => {
    const workbench = makeWorkbench();
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, 120);
    const json = workbench.controller.document.exportJSON();

    const reloaded = makeWorkbench();
    expect(reloaded.controller.document.importJSON(json).ok).toBe(true);
    expect(readStepBudget(reloaded.model.settings)).toBe(120);
  });

  it('clears to *unset*, never to zero and never to a number', () => {
    const workbench = makeWorkbench();
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, 300);
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, undefined);

    const parsed = JSON.parse(workbench.controller.document.exportJSON()) as Record<
      string,
      unknown
    >;
    // The whole `settings` block goes, because it held nothing else — the
    // canonical shape a document that never had a budget already has.
    expect(parsed).not.toHaveProperty('settings');
    expect(readStepBudget(workbench.model.settings)).toBeNull();
  });

  it('leaves a document that never had the setting byte-for-byte unchanged', () => {
    const workbench = makeWorkbench();
    const before = workbench.controller.document.exportJSON();
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, 200);
    workbench.controller.history.undo();

    expect(workbench.controller.document.exportJSON()).toBe(before);
  });

  it('does not disturb the other settings beside it', () => {
    const workbench = makeWorkbench();
    workbench.model.setSettings({ model: 'ollama:gpt-oss:120b-cloud' });
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, 400);
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, undefined);

    expect(workbench.model.settings).toEqual({ model: 'ollama:gpt-oss:120b-cloud' });
  });

  it('is undoable, like every other gesture', () => {
    const workbench = makeWorkbench();
    workbench.controller.document.setSetting(STEP_BUDGET_KEY, 100);
    workbench.controller.history.undo();
    expect(readStepBudget(workbench.model.settings)).toBeNull();

    workbench.controller.history.redo();
    expect(readStepBudget(workbench.model.settings)).toBe(100);
  });

  it('reads only a whole number, from a document written by anyone', () => {
    expect(readStepBudget({})).toBeNull();
    expect(readStepBudget({ recursionLimit: 60 })).toBe(60);
    // A hand-written package or a script is as likely to write the snake case,
    // and `step_budget.py` reads both. So does this.
    expect(readStepBudget({ recursion_limit: 60 })).toBe(60);
    expect(readStepBudget({ recursionLimit: '60' })).toBeNull();
    expect(readStepBudget({ recursionLimit: true })).toBeNull();
    expect(readStepBudget({ recursionLimit: 12.5 })).toBeNull();
  });
});

describe('what a person may type into the field', () => {
  it('takes an empty box to mean unset', () => {
    expect(parseStepBudget('')).toEqual({ ok: true, value: null });
    expect(parseStepBudget('   ')).toEqual({ ok: true, value: null });
  });

  it('takes a whole number inside the runtime window', () => {
    expect(parseStepBudget(' 50 ')).toEqual({ ok: true, value: 50 });
    expect(parseStepBudget(String(STEP_BUDGET_MIN))).toEqual({ ok: true, value: STEP_BUDGET_MIN });
    expect(parseStepBudget(String(STEP_BUDGET_MAX))).toEqual({ ok: true, value: STEP_BUDGET_MAX });
  });

  it('refuses anything the runtime would silently change under them', () => {
    // Out of range is clamped by `step_budget.py` rather than refused, so a
    // field that accepted 5 would show 5 and run 10 — a number that lies.
    for (const text of ['0', '9', '1001', '-20', 'lots', '12.5', 'Infinity', 'NaN']) {
      expect(parseStepBudget(text).ok, text).toBe(false);
    }
  });

  it('names the window in the refusal rather than just saying no', () => {
    const refused = parseStepBudget('4');
    expect(refused.ok).toBe(false);
    if (refused.ok) return;
    expect(refused.error).toContain(String(STEP_BUDGET_MIN));
    expect(refused.error).toContain(String(STEP_BUDGET_MAX));
  });
});

describe('the words the field uses', () => {
  const copy = [STEP_BUDGET_LABEL, STEP_BUDGET_HINT, STEP_BUDGET_PLACEHOLDER].join(' ');

  it('calls it the step budget', () => {
    expect(STEP_BUDGET_LABEL).toBe('Step budget');
  });

  it('says supersteps, and says a lap is not one', () => {
    expect(STEP_BUDGET_HINT).toMatch(/superstep/i);
    expect(STEP_BUDGET_HINT).toMatch(/lap/i);
    // The whole point: a fan-out spends several supersteps per lap, so the
    // number cannot be sized as if it were a lap count.
    expect(STEP_BUDGET_HINT).toMatch(/several|more than one/i);
  });

  it('says the number sizes this workflow, not a whole composition', () => {
    // `organisms-first-class` 63. Each mount is a separate run with a counter
    // of its own, so a composition of seven workflows given 60 may spend
    // seven sixties. Measured, and the number is per-graph — which is exactly
    // what a reader of a box labelled "Step budget" does not assume.
    expect(STEP_BUDGET_HINT).toMatch(/this workflow|each mounted|its own/i);
    expect(STEP_BUDGET_HINT).toMatch(/from zero|of its own|separately/i);
  });

  it('never calls it iterations, turns or retries', () => {
    for (const forbidden of [/iteration/i, /max turns/i, /retr(y|ies)/i, /recursion/i]) {
      expect(copy, `"${copy}"`).not.toMatch(forbidden);
    }
  });

  it('says what the default is, so an empty box is not a mystery', () => {
    expect(copy).toContain(String(STEP_BUDGET_DEFAULT));
  });

  it('says what this number means when the package is mounted', () => {
    // `organisms-first-class` 61. The field is one number with two effects:
    // run this package directly and it is the run's budget; mount it inside
    // another workflow and it can only take LESS than what that run allowed,
    // never more. A developer who sets 1000 here and mounts the package into
    // a 50-superstep run gets 50, and nothing on the canvas said so.
    expect(STEP_BUDGET_HINT).toMatch(/mount/i);
    expect(STEP_BUDGET_HINT).toMatch(/less/i);
  });

  it('does not teach "make it bigger" as the answer to a loop that will not stop', () => {
    // CLAUDE.md prefers a guard that routes to END over raising the number,
    // and a field that only offers the number teaches the opposite move.
    expect(STEP_BUDGET_HINT).toMatch(/grader/i);
  });
});
