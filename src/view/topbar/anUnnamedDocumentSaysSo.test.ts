import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { UNNAMED_DOCUMENT, isUnnamedDocument } from '@core/model/documentName';

/**
 * `say-it-on-the-surface/09` — **an unsaved document must read as unsaved.**
 *
 * The owner: *"the top bar 'AI Workflow' is misleading. A user would think
 * it's saved."* And they were reading it beside a mount card that refuses to
 * open **because this workflow is not saved** — two surfaces in one screen
 * telling opposite stories.
 *
 * ## Three facts, three signals, and none of them a duplicate
 *
 * The instruction that shaped this was *make the two agree rather than adding
 * a third signal*. Establishing what was already there settled it: the top bar
 * carries three marks in this region and they answer three different
 * questions.
 *
 * | Mark | Answers | Owner |
 * | --- | --- | --- |
 * | the dot on Save | is there a folder on the backend? | `saveAffordance.marker` |
 * | the `Draft` badge | can customers see this? | `publishAffordance` |
 * | the document slot | **what is this called?** | here |
 *
 * `Unsaved` in the third slot would have been the duplicate — a second
 * spelling of the dot, in a slot that is supposed to say *which* document this
 * is. Two tabs holding two drafts would both have read `Unsaved`. `Untitled`
 * is the fact neither of the other two carries, and it is the one about to
 * become permanent: `workflow_store.mint` slugifies this word at first save
 * and freezes it, because a slug that moves renames a directory.
 *
 * The `Draft` badge already agrees rather than competing —
 * `publishAffordance`'s `slug === null` branch opens *"Draft — not on disk
 * yet"*, so the two say different halves of one situation.
 */

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('a document nobody has named', () => {
  it('starts out unnamed rather than wearing a plausible title', () => {
    const workbench = new Workbench();
    expect(workbench.model.name).toBe(UNNAMED_DOCUMENT);
    expect(isUnnamedDocument(workbench.model.name)).toBe(true);
  });

  it('is marked in the top bar, so the slot does not read as a name somebody typed', () => {
    const topbar = read('./TopBar.tsx');
    // Not a second string in the slot: the same slot, carrying a state the CSS
    // can see. A separate "unnamed" element would put two things where the
    // document's identity goes.
    expect(topbar).toMatch(/data-unnamed=\{[^}]*isUnnamedDocument\(/);
  });

  it('says what will happen next, where the name is', () => {
    const topbar = read('./TopBar.tsx');
    // The hover on the slot itself. A user who wonders what `Untitled` means
    // gets the answer at the word, not in a panel — which is the whole
    // premise of this map.
    expect(topbar).toMatch(/Not saved yet/);
    expect(topbar).toMatch(/folder/);
  });

  it('is dimmed rather than coloured, because no new colour is spent on it', () => {
    const css = read('./TopBar.css');
    const rule = /\.topbar__doc\[data-unnamed='true'\]\s*\{([^}]*)\}/.exec(css);
    expect(rule).not.toBeNull();
    const body = rule![1];
    // Existing tokens only. The tertiary text token is what every other
    // "this is secondary information" surface in `design/` already uses, and
    // italic carries the same claim without asking the palette for anything.
    expect(body).toMatch(/var\(--color-text-tertiary\)/);
    expect(body).toMatch(/font-style:\s*italic/);
    expect(body).not.toMatch(/#[0-9a-f]{3,8}|rgb|hsl/i);
  });
});
