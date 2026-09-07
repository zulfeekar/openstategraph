import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { starterAssembly } from '@nodes/assemblies';
import {
  EMPTY_CANVAS_EXAMPLES,
  EMPTY_CANVAS_HINT,
  EMPTY_CANVAS_PATTERN,
  EMPTY_CANVAS_TITLE,
} from './emptyStateCopy';

/**
 * production-ready ticket 22 asked, first, whether a business rule exists —
 * "does a flow have to start at an input and end at `output.formatted`?" —
 * because the answer decides what the empty canvas is allowed to say.
 *
 * **It does not.** These tests are that answer, executable, so the copy and
 * the validator cannot drift apart later.
 */
describe('what the editor actually requires of a flow', () => {
  const load = (nodes: unknown[], edges: unknown[]) => {
    const workbench = new Workbench();
    workbench.controller.document.importJSON(
      JSON.stringify({ version: 2, name: 'Shape', nodes, edges }),
    );
    return workbench;
  };

  const node = (id: string, type: string) => ({
    id,
    type,
    position: { x: 0, y: 0 },
    size: { width: 260, height: 130 },
    parentId: null,
    data: {},
  });

  const errors = (workbench: Workbench) =>
    workbench.workflowValidator.validate().filter((d) => d.severity === 'error');

  it('complains about an empty port, never about a missing input node', () => {
    // Agent → Output with nothing upstream. The single error names the
    // agent's **`prompt` port**, not the shape of the graph.
    const workbench = load(
      [node('a', 'agent.llm'), node('o', 'output.formatted')],
      [
        {
          id: 'e1',
          source: { nodeId: 'a', portId: 'result' },
          target: { nodeId: 'o', portId: 'result' },
        },
      ],
    );
    expect(errors(workbench).map((d) => d.code)).toEqual(['required-input-missing']);
  });

  it('lets anything that produces an answer feed an agent — not only an input', () => {
    // Which is what makes the above a *port* requirement rather than "a flow
    // starts at an Input": `prompt` accepts `result` too, so an Agent, a
    // Worker, a Grader's pass or a mounted Workflow satisfies it.
    const definition = new Workbench().registry.nodeTypes.get('agent.llm');
    const ports =
      typeof definition?.ports === 'function' ? definition.ports({}) : definition?.ports;
    const prompt = (ports ?? []).find((port) => port.id === 'prompt');
    expect(prompt?.accepts).toEqual(expect.arrayContaining(['text', 'result']));
  });

  it('lets a flow end at an agent, with no diagnostic at all', () => {
    // Input → Agent, no Output. `has-output` asks whether *anything* is
    // terminal, not whether an `output.formatted` exists — its own notes
    // record that checking for the node type made every agent-ended workflow
    // a false positive. Nothing here is an error or a warning.
    const workbench = load(
      [node('i', 'input.text'), node('a', 'agent.llm')],
      [
        {
          id: 'e1',
          source: { nodeId: 'i', portId: 'text' },
          target: { nodeId: 'a', portId: 'prompt' },
        },
      ],
    );
    expect(
      workbench.workflowValidator.validate().filter((d) => d.severity !== 'info'),
    ).toHaveLength(0);
  });

  it('is quiet about the shape the empty state teaches', () => {
    // The taught starter must not itself trip a diagnostic — guidance that
    // produces a complaint the moment it is followed is worse than none.
    const workbench = new Workbench();
    workbench.controller.clipboard.insertFragment(starterAssembly.fragment, { x: 0, y: 0 });
    expect(
      workbench.workflowValidator.validate().filter((d) => d.severity !== 'info'),
    ).toHaveLength(0);
  });
});

describe('the empty-canvas copy', () => {
  it('names the three nodes in the order they are wired', () => {
    expect(EMPTY_CANVAS_TITLE).toContain('Input');
    expect(EMPTY_CANVAS_TITLE.indexOf('Input')).toBeLessThan(EMPTY_CANVAS_TITLE.indexOf('Agent'));
    expect(EMPTY_CANVAS_TITLE.indexOf('Agent')).toBeLessThan(EMPTY_CANVAS_TITLE.indexOf('Output'));
  });

  it('says what each of the three is for', () => {
    for (const word of ['question', 'thinking', 'answer']) {
      expect(EMPTY_CANVAS_PATTERN).toContain(word);
    }
  });

  it('states a convention, never a rule — because there is no rule', () => {
    // Ticket 23's line is inside the sweep, not beside it: a fourth string on
    // the same surface is a fourth chance to tell a beginner something the
    // validator will contradict.
    const copy = [
      EMPTY_CANVAS_TITLE,
      EMPTY_CANVAS_PATTERN,
      EMPTY_CANVAS_HINT,
      EMPTY_CANVAS_EXAMPLES,
    ].join(' ');
    expect(copy).not.toMatch(/\bmust\b|\bhas to\b|\brequired\b|\bevery flow\b|\balways\b/i);
    // …and hedges explicitly, rather than merely omitting the claim.
    expect(EMPTY_CANVAS_PATTERN).toMatch(/most flows/i);
  });

  it('names the palette entry it is pointing at, exactly', () => {
    // A hint naming something the palette does not call by that name sends a
    // beginner looking for a control that is not there.
    expect(EMPTY_CANVAS_HINT).toContain(starterAssembly.label);
  });

  it('still offers the two ways in that always existed', () => {
    expect(EMPTY_CANVAS_HINT).toMatch(/one at a time/);
    expect(EMPTY_CANVAS_HINT).toContain('⌘V');
  });

  it('offers the third way in — take a finished one (ticket 23)', () => {
    // Drawing from parts is the right first lesson and the slower one. The
    // gallery was reachable from here by nothing at all.
    expect(EMPTY_CANVAS_EXAMPLES).toContain('Workflows → Examples');
    expect(EMPTY_CANVAS_EXAMPLES).toMatch(/copy/i);
  });
});
