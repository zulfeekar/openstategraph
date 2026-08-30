import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The legend against the fold that draws it — `memory-and-replay` 69.
 *
 * `66` gave every tool call its own bar, still `data-kind="tool"`. Before
 * this ticket the swatch's label was **"No model time"**, written for the
 * other bar that shares the kind: a node whose own frame folded no model
 * step, drawn hollow (`barVocabulary.test.ts` — `in1`, `router`, `join`,
 * `out1` in the recorded run, none of which ever called a tool either). Both
 * are real: a genuinely idle structural bar, and an eleven-bar measured tool
 * call. Neither the swatch nor the CSS distinguishes them (`RunDock.css` has
 * no `.rtl__bar[data-kind='tool']` rule at all — only `model`, `mount` and
 * `refusal` get one), so this is one thing wearing one label, and the label
 * has to be true of both rather than of only the older meaning.
 *
 * Read from source rather than rendered, in the idiom
 * `theDockKeepsBothColumns.test.ts` set for this surface: the legend's words
 * are a decision the fold made, not a rendering a browser has to reproduce.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const CHART = read('./RunTimeline.tsx');
const TIMELINE = read('./timeline.ts');

describe('the legend labels the tool swatch honestly for both bars that wear it', () => {
  it('no longer claims the bar spent no time, which is false of a measured tool call', () => {
    const legend = CHART.match(/const keys:[\s\S]*?\];/)?.[0] ?? '';
    const tool = legend.match(/\['tool',\s*'([^']+)'\]/)?.[1] ?? '';
    expect(tool).not.toBe('');
    expect(tool).not.toMatch(/no model time/i);
    // True of the idle structural bar (it made no model call) and of a real
    // tool-call bar (it is a tool call, not a model call) alike.
    expect(tool).toMatch(/not a model call/i);
  });

  it('leaves the detail pane’s own hollow-bar sentence alone', () => {
    // `barDetail.ts`'s `WHY.tool` is pinned by `replayIsNotRerun.test.ts` and
    // is not what this ticket touches — it describes the node-level bar
    // specifically, and stays true of it regardless of what the legend says.
    const barDetail = read('../run/barDetail.ts');
    expect(barDetail).toMatch(/No model time was spent in this bar/);
  });
});

describe('the legend lists exactly the kinds the fold can emit, and nothing else', () => {
  it('every StepKind the fold assigns has a legend entry', () => {
    const stepKind = TIMELINE.match(/export type StepKind = ([^;]+);/)?.[1] ?? '';
    const kinds = [...stepKind.matchAll(/'([a-z]+)'/g)].map((m) => m[1]);
    expect(kinds).toEqual(['model', 'tool', 'mount', 'refusal']);
    const legend = CHART.match(/const keys:[\s\S]*?\];/)?.[0] ?? '';
    for (const kind of kinds) {
      expect(legend).toMatch(new RegExp(`\\['${kind}',`));
    }
  });

  it('the legend’s one non-StepKind entry — the settled tick — is drawn unconditionally on every closed, dispatched lane', () => {
    // Not a bar kind at all (`RunLane.kind` is `run | fanout | subagent |
    // async`), so it cannot appear in `StepKind` above; it is the 2px mark
    // `54`'s settled frame leaves on any lane the run closed. Real on every
    // fan-out, subagent or async spawn that settles — which is not rare.
    const legend = CHART.match(/const keys:[\s\S]*?\];/)?.[0] ?? '';
    expect(legend).toMatch(/\['settled',/);
    expect(CHART).toMatch(/row\.whole && row\.lane\.endMs !== null/);
  });
});
