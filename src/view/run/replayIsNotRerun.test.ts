import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { transportOffered } from './replayTransport';
import { WHY } from './barDetail';

/**
 * **Replay** and **re-run** are two words for two things, and only one of them
 * is built here.
 *
 * `memory-and-replay` 52's own "done when", pinned the way
 * `slugIsExplained.test.ts` pins *slug*: a claim about copy has no way to fail
 * unless a test reads the copy. The collision is not hypothetical — LangGraph
 * publishes *replay* for the fork-and-re-execute operation, so a reader who
 * follows its time-travel guide arrives holding the other meaning, and the
 * word this product prints on a button has to be unambiguous where they land.
 */
const ROOT = fileURLToPath(new URL('../../../', import.meta.url));
const read = (path: string): string => readFileSync(ROOT + path, 'utf8');

describe('replay is not re-run', () => {
  it('gives both words a row in the one lexicon table, each with what it must never mean', () => {
    const rules = read('CLAUDE.md');
    const replay = rules.match(/^\| \*\*Replay\*\* \|.*$/m)?.[0] ?? '';
    const rerun = rules.match(/^\| \*\*Re-run\*\* \|.*$/m)?.[0] ?? '';
    // Three cells, like every other row in that table: the word, what it
    // means, and the column that is the whole point — what it must never mean.
    expect(replay.split('|').filter((cell) => cell.trim() !== '')).toHaveLength(3);
    expect(rerun.split('|').filter((cell) => cell.trim() !== '')).toHaveLength(3);
    expect(replay).toMatch(/profiler/);
    expect(replay).toMatch(/re-execut/);
    expect(rerun).toMatch(/\*different\* run/);
  });

  it('never offers re-execution as a mode of the transport', () => {
    // The button set, read out of the component rather than asserted about it.
    const chart = read('src/view/ask/RunTimeline.tsx');
    const labels = [...chart.matchAll(/>\s*\{?['"]?(Play|Pause|Restart|◀ Step|Step ▶)/g)];
    expect(labels.length).toBeGreaterThan(0);
    for (const forbidden of [/Re-run/i, /Run again/i, /Replay from/i]) {
      expect(chart).not.toMatch(forbidden);
    }
  });

  it('withholds the transport from a live run and from a run with no clock', () => {
    // The load-bearing refusal, and two different reasons for it: a live run
    // has no right-hand edge to reach, and an unclocked one has no axis at
    // all — `launch-readiness` 108's rule at the level of the whole control.
    expect(transportOffered(true, 52493)).toBe(false);
    expect(transportOffered(false, null)).toBe(false);
    expect(transportOffered(false, 0)).toBe(false);
    expect(transportOffered(false, 52493)).toBe(true);
  });

  it('explains hollow as spent-nothing rather than as missing', () => {
    // The prototype's own sentence, kept because it is the one thing a reader
    // cannot deduce from the drawing: a ring is an absence of cost, not an
    // absence of data.
    expect(WHY.tool).toMatch(/No model time was spent/);
    expect(WHY.refusal).toMatch(/accent/);
  });

  it('binds the transport in the one table that also feeds the shortcuts drawer', () => {
    // A control wired to a handler inside the panel works and is
    // undiscoverable — `51` wrote that down for the dock's own toggle, and
    // four more rows is four more chances to forget it.
    const shell = read('src/view/AppShell.tsx');
    for (const keys of [
      'Mod+Shift+Enter',
      'Mod+Shift+ArrowRight',
      'Mod+Shift+ArrowLeft',
      'Mod+Shift+0',
    ]) {
      expect(shell).toContain(`keys: '${keys}'`);
    }
    // Every row takes the functional form — calling the module singleton
    // rather than closing over transport state, which is the stale-closure
    // bug `51`'s own comment records.
    expect(shell).not.toMatch(/run: \(\) => \w*[Tt]ransport\.\w+\(\w/);
    expect([...shell.matchAll(/run: \(\) => replayTransport\.\w+\(\)/g)]).toHaveLength(4);
  });
});
