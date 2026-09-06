import type { IAssemblyDefinition } from './contract';
import { CATEGORY } from '../vocabulary';

/**
 * Input → Agent → Output, wired, in one drag.
 *
 * The answer to production-ready ticket 22: a new user faces an empty canvas
 * and about twenty node types with nothing saying which one comes first. The
 * owner decided what should be taught — Input → Agent → Output — and this is
 * the *mechanism* half of the answer, the empty-state copy being the other.
 *
 * **A starting point, not a rule.** Nothing in this repository requires a flow
 * to begin at an input or end at `output.formatted`: `plan.entry` and
 * `plan.exits` are computed from in-degree and out-degree and never from a node
 * type, and the editor's `has-output` rule is a *warning* about an unconsumed
 * result that deliberately tolerates a flow ending at an Agent. So this is the
 * shape almost every flow takes, offered — never imposed. The copy that
 * surfaces it must not claim otherwise (`view/canvas/emptyStateCopy.ts`).
 *
 * **Why an assembly rather than a seeded document.** Ticket 41 removed a
 * hardcoded starting document, and rightly: an editor that puts three nodes on
 * a canvas nobody asked for has decided for the user, and the fresh canvas
 * should be honestly empty. An assembly reverses the direction — the user
 * reaches for it — while costing the same one gesture. The file-side twin of
 * the same idea already exists and is not duplicated here: `--template
 * minimal` (`templates/index.json`) scaffolds a whole package, and a template
 * severs its link at creation, whereas this adds to the document already open.
 *
 * **Three nodes here, two in the revision loop, and the difference is real.**
 * That assembly deliberately inserts no input or output, because it lands in a
 * canvas that already has them. This one exists for the canvas that has
 * nothing, so the ends are the point.
 */
export const STARTER_ASSEMBLY_ID = 'assembly.starter';

/**
 * The agent node is factory-built (`createAgentNode`, so it can carry the
 * shared model picker), so its id comes from the one table that names every
 * type rather than from a second literal here.
 */
const AGENT_TYPE = 'agent.llm';
const INPUT_TYPE = 'input.text';
const OUTPUT_TYPE = 'output.formatted';

/** Laid out left to right, the same reading order the canvas uses. */
const INPUT_AT = { x: 0, y: 0 };
const AGENT_AT = { x: 320, y: 0 };
const OUTPUT_AT = { x: 700, y: 0 };

export const starterAssembly: IAssemblyDefinition = {
  id: STARTER_ASSEMBLY_ID,
  label: 'Starter flow',
  description:
    'Input → Agent → Output, already wired — the smallest flow that runs. Type your question into the Input and press Run.',
  iconId: 'assembly-starter',
  category: CATEGORY.compose,
  keywords: [
    'start',
    'starter',
    'first',
    'basic',
    'minimal',
    'simple',
    'template',
    'input',
    'agent',
    'output',
    'hello',
  ],
  fragment: {
    origin: INPUT_AT,
    nodes: [
      {
        id: 'starter-input',
        type: INPUT_TYPE,
        position: INPUT_AT,
        size: { width: 260, height: 150 },
        // Required by `SerializedNode`: a fragment is the same shape a copy
        // produces, and a paste reparents by geometry after the drop anyway.
        parentId: null,
        title: 'Question',
        // **Empty on purpose.** Run reads this field, so a seeded question is
        // one the user never asked being spent on the first press. The Input
        // is the one thing the starter cannot supply.
        data: { prompt: '' },
      },
      {
        id: 'starter-agent',
        type: AGENT_TYPE,
        position: AGENT_AT,
        size: { width: 300, height: 220 },
        parentId: null,
        title: 'Agent',
        data: {
          systemPrompt: 'Answer the question directly and completely.',
        },
      },
      {
        id: 'starter-output',
        type: OUTPUT_TYPE,
        position: OUTPUT_AT,
        size: { width: 260, height: 130 },
        parentId: null,
        title: 'Answer',
        data: {},
      },
    ],
    edges: [
      {
        source: { nodeId: 'starter-input', portId: 'text' },
        target: { nodeId: 'starter-agent', portId: 'prompt' },
      },
      {
        source: { nodeId: 'starter-agent', portId: 'result' },
        target: { nodeId: 'starter-output', portId: 'result' },
      },
    ],
  },
};
