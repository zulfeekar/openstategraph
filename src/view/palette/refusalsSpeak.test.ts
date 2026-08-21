import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * **Four rules can stop you adding a workflow, and a user meets them as one
 * experience.**
 *
 * `say-it-on-the-surface` 02. The owner asked *"why is it not able to add
 * another workflow — what is the business rule, is it broken or obvious?"* and
 * the repository could not answer, because at least four independent
 * mechanisms produce that symptom and each had its own presentation:
 *
 * 1. **Self-inclusion** — `mountCycleRefusal` over `mountAncestry()`: a greyed,
 *    non-draggable package row and a label suffix in the mount combobox.
 * 2. **A greyed row that is not `disabled`** — deliberately, so it keeps firing
 *    mouse events and can still speak.
 * 3. **The duplicate-name `confirm`** — which used to abort in total silence.
 * 4. **`maxInstances`** — a flat palette row. Not `workflow.subgraph`, which
 *    declares no cap; recorded so the next reader does not re-check it.
 *
 * A user cannot tell four mechanisms apart, so the standard is one shape of
 * answer: **the refusal is audible on the gesture that was refused**. That is
 * `consistency-sweep` 10's conclusion, generalised from one row to every path
 * that can say no.
 *
 * The reproduction of the owner's own case stays open on the ticket — only the
 * person who hit it knows which state they were in. What is closed here is the
 * silence each path could fall into.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const palette = read('./Palette.tsx');
const saving = read('../workflow/saveWorkflow.ts');
const shell = read('../AppShell.tsx');
const manager = read('../workflow/WorkflowManager.tsx');

describe('every way to refuse a workflow', () => {
  it('speaks when a package row refuses a mount — on both gestures', () => {
    // Dragging was the silent one before `consistency-sweep` 10; the keyboard
    // became a placing gesture in `say-it-on-the-surface` 04 and had to join.
    expect(palette).toMatch(/onDragStart=\{\(event\) => \{\s*if \(refused\) \{\s*refuse\(event\)/);
    expect(palette).toMatch(/onClick=\{\(event\) => \{\s*if \(refused\) refuse\(event\);/);
    expect(palette).toMatch(/onKeyDown=\{onKeyboardActivate\(\(\) => \{\s*if \(refused\)/);
  });

  it('speaks when a capped row refuses, which the keyboard path made necessary', () => {
    // Silent by accident and harmlessly while a click placed: the flat styling
    // and the hover text carried it. Once Enter became the placement path, a
    // keyboard user pressing it got nothing — no styling to read, no hover to
    // reach.
    expect(palette).toContain('onRefuse(atLimitMessage(definition))');
    // One sentence, used by the hover text and the toast alike.
    expect(palette).toMatch(/title=\{\s*disabled\s*\?\s*atLimitMessage\(definition\)/);
  });

  it('speaks when a save is abandoned rather than failing', () => {
    // The worst of the four, because nothing was even attempted: `confirm`
    // returning false produced no message, so the button looked broken rather
    // than obeyed — and a browser that suppresses dialogs answers "no" for you.
    expect(saving).toMatch(/case 'cancelled':/);
    expect(saving).toContain('Not saved — that would have created a second workflow');
  });

  it('speaks when New is asked for and then not done — on both surfaces', () => {
    // **The fifth path**, and the one this ticket's audit predicted it would
    // find: *"if the answer is 'nothing at all', the remaining bug is a fifth
    // path this audit did not find."* Reproduced from the owner's own sentence
    // — a node on a never-saved document, press New, decline, and the editor
    // neither adds a workflow nor says why.
    //
    // Both New buttons had the identical `if (!confirm(warning)) return;` that
    // `saveWorkflow`'s duplicate-name confirm had before it was given a voice,
    // so both are pinned. A bare return after a declined confirm is the shape
    // to watch for.
    for (const surface of [shell, manager]) {
      expect(surface).toContain('discardDeclined(subject)');
      expect(surface).not.toMatch(/!(?:window\.)?confirm\(warning\)\) return;/);
    }
  });

  it('keeps the greyed row firing events, because silence is the failure mode', () => {
    // A `disabled` button fires no mouse events, so it would swallow the hover
    // text — the compiler's own sentence and the best thing on the row.
    expect(palette).toContain('aria-disabled={refused}');
    expect(palette).not.toMatch(/<button[^>]*\n\s*disabled=\{refused\}/);
  });
});
