import type { INodeCategory } from '@core/model/contracts/node';
import type { IPortTypeDefinition } from '@core/model/contracts/ports';

/**
 * The catalogue's shared vocabulary: palette sections and the data types
 * that flow along links.
 *
 * Both are registered rather than hardcoded, so a plugin can add a section
 * ("Retrieval", "Evaluators") or a port type ("embedding", "image") without
 * touching the editor.
 */

export const CATEGORY = {
  inputs: 'inputs',
  tools: 'tools',
  output: 'output',
  agent: 'agent',
  compose: 'compose',
  annotate: 'annotate',
} as const;

/**
 * Sections in atomic-design tier order — atoms, then molecules, then
 * organisms — because the tier is the thing a developer is actually
 * choosing between, and a palette that interleaves them teaches the wrong
 * mental model.
 *
 * **Every label's tier is load-bearing and must stay honest.** The bug this
 * ordering replaces: `Team` and `Workflow` (whole workflows, run as one
 * step) sat under a section labelled `Agents · molecules`, so the palette
 * claimed an organism was a molecule.
 *
 * The judgement calls, recorded here rather than in a commit message:
 *
 * - **Orchestrator (supervisor) is a molecule, not an organism.** Alone it
 *   is one model call that emits a plan and a `Send` fan-out — a single
 *   reasoning step, exactly like Router or Grader. The *organism* is
 *   supervisor + workers + a join, and that organism is a shape you draw on
 *   the canvas, not an item you drag from the palette. Tiering the palette
 *   entry as an organism would promise an assembly the drag does not
 *   deliver.
 * - **Team and Workflow are organisms**, and are the only ones: each is an
 *   entire compiled workflow — its own nodes, edges, state and loop —
 *   mounted as one step. Dragging one *does* deliver the assembly.
 * - **Function (Format Report) is a molecule, not an output atom.** It is a
 *   deterministic reasoning-free graph step that joins many worker results;
 *   it composes, so it is not an atom. `Formatted Output` — a sink with one
 *   input and no logic — is the atom.
 * - **Annotate carries no tier**, and says so instead of borrowing one:
 *   notes and groups are excluded from execution entirely, so they are not
 *   made of anything and nothing is made of them.
 */
export const CATEGORIES: readonly INodeCategory[] = [
  {
    id: CATEGORY.inputs,
    label: 'Inputs · atoms',
    order: 10,
    description: 'Sources. No logic, nothing upstream.',
  },
  {
    id: CATEGORY.tools,
    label: 'Tools · atoms',
    order: 20,
    description: 'One capability each, bound to an agent rather than wired in sequence.',
  },
  {
    id: CATEGORY.output,
    label: 'Output · atoms',
    order: 30,
    description: 'Sinks. One input, no decision.',
  },
  {
    id: CATEGORY.agent,
    label: 'Reasoning & control · molecules',
    order: 40,
    description:
      'One decision step each — agent, router, grader, approval, worker, supervisor, function. A supervisor alone is a molecule; supervisor + workers + join is an organism you draw, not one you drag.',
  },
  {
    id: CATEGORY.compose,
    label: 'Composition · organisms',
    order: 50,
    description: 'A whole workflow — its own nodes, state and loop — mounted as one step.',
  },
  {
    id: CATEGORY.annotate,
    label: 'Annotate · no tier',
    order: 60,
    description: 'Canvas decoration. Never compiled, never executed.',
  },
];

export const PORT = {
  text: 'text',
  skill: 'skill',
  tool: 'tool',
  result: 'result',
  /** Carries a grader's rejection back upstream. The only type a cycle may close on. */
  feedback: 'feedback',
  /**
   * A fan-out declaration, not control flow — matches the compiler's
   * `WORKER_PORT_TYPE`. An edge landing here becomes a `Send` dispatch
   * target, never a `workflow.json` graph edge.
   */
  worker: 'worker',
} as const;

export const PORT_TYPES: readonly IPortTypeDefinition[] = [
  {
    id: PORT.text,
    label: 'Text',
    iconId: 'port-text',
    accent: 'amber',
  },
  {
    id: PORT.skill,
    label: 'Skill',
    iconId: 'port-skill',
    accent: 'orange',
  },
  {
    id: PORT.tool,
    label: 'Tool',
    iconId: 'port-tool',
    accent: 'violet',
  },
  {
    id: PORT.feedback,
    label: 'Feedback',
    iconId: 'port-feedback',
    accent: 'red',
  },
  {
    id: PORT.worker,
    label: 'Worker',
    iconId: 'port-worker',
    accent: 'blue',
  },
  {
    id: PORT.result,
    label: 'Result',
    iconId: 'port-result',
    // A result port also accepts raw text, so a plain input can be wired
    // straight to an output node while a graph is being sketched out.
    accepts: [PORT.result, PORT.text],
    accent: 'green',
  },
];
