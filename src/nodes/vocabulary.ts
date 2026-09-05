import type { INodeCategory } from '@core/model/contracts/node';
import type { IPortTypeDefinition } from '@core/model/contracts/ports';
import type { ICompositionTerm } from '@core/runtime/compositionVocabulary';

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
  memory: 'memory',
  resolve: 'resolve',
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
 * - **Memory is its own section, and that is the point.** `memory.segment` is
 *   a molecule by the same argument `function.format_report` is one: it is a
 *   deterministic, reasoning-free step that *composes*, so it is not an atom,
 *   and it brings no nodes, state or loop of its own, so it is not an
 *   organism. What it is not is *reasoning or control* — a tollbooth decides
 *   nothing — and every label's tier and wording being load-bearing is the
 *   first thing `vocabulary.test.ts` asserts. Filing it under the agents'
 *   heading to avoid adding a section would have made that heading false,
 *   which is the defect this ordering was written to fix in the first place.
 */
export const CATEGORIES: readonly INodeCategory[] = [
  {
    id: CATEGORY.inputs,
    label: 'Inputs · atoms',
    order: 10,
    // The "which node comes first?" cue (ticket 22), in the smallest honest
    // form: a hedge, because nothing makes a flow begin here — an Agent's
    // `prompt` accepts a `result` as readily as a `text`, so a mounted
    // workflow or a worker can open a graph just as well. "Usually" is the
    // whole difference between a cue and a false rule.
    description: 'Sources. No logic, nothing upstream — usually where a flow starts.',
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
    // The other half of the cue, hedged for the other reason: `has-output`
    // asks whether *anything* is terminal, not whether one of these exists,
    // so a flow ending at an Agent is legitimate and warns about nothing.
    description: 'Sinks. One input, no decision — usually where a flow ends.',
  },
  {
    id: CATEGORY.agent,
    label: 'Reasoning & control · molecules',
    order: 40,
    description:
      'One decision step each — agent, router, grader, guardrail, approval, worker, supervisor, function. A supervisor alone is a molecule; supervisor + workers + join is an organism you draw, not one you drag.',
  },
  {
    id: CATEGORY.memory,
    label: 'Memory · molecules',
    order: 45,
    description:
      'What a workflow keeps between runs, at the position you draw it. Deterministic and free — nothing here calls a model.',
  },
  {
    id: CATEGORY.resolve,
    label: 'Resolution · molecules',
    order: 47,
    // Its own section for exactly the reason Memory has one: a resolver is
    // *not* reasoning or control — it decides nothing, it looks a word up —
    // and filing it under "Reasoning & control" to avoid adding a heading
    // would make that heading false, which is the defect this ordering was
    // written to fix. A molecule by the same argument `memory.segment` is
    // one: deterministic, model-free, and it composes.
    description:
      'What a word means here, looked up before the model runs. Deterministic and free — ' +
      'nothing here calls a model, and every lookup reports what it covered.',
  },
  {
    id: CATEGORY.compose,
    label: 'Composition · organisms',
    order: 50,
    // Said "its own nodes, state and revision loop", which overstated it: a
    // mounted workflow loops only if the child does, and Workflow is the
    // entry that does not promise one. The loop belongs to Team's copy, where
    // it is read out of the child rather than asserted (ticket 02).
    description:
      'A whole workflow — its own nodes, state and tools — mounted as one step, by reference. Change the original and every mount of it changes.',
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

/**
 * The words a mount card counts its child's nodes in.
 *
 * These lived in `src/core/runtime/compositionSummary.ts` as a hardcoded
 * table of node-type ids, so a new node family was invisible in every mount
 * card until somebody edited `core/` — the one counter-example to open/closed
 * the system design review found (reviews-2026-08-14 ticket 13). They belong
 * here for the reason the sections and port types above do: they are the
 * catalogue's vocabulary, and a plugin adding a family should be able to add
 * its word with it.
 *
 * **The order of this list is not the order on the card.** Each term names a
 * `group`, and `CENSUS_GROUPS` in `core/` owns the reading order — actors
 * first, then what closes the loop, then what they hold. Order here decides
 * only between terms *within* one group, which is why the two agents-and-
 * orchestrators entries sit together and the tools after them.
 *
 * A family is written with its trailing dot (`agent.`) and covers every type
 * under it; an exact type always wins over its family, whichever appears
 * first.
 */
export const CENSUS_TERMS: readonly ICompositionTerm[] = [
  // The actors — who does the work.
  { id: 'orchestrate.supervisor', group: 'actor', one: 'supervisor', many: 'supervisors' },
  { id: 'orchestrate.worker', group: 'actor', one: 'worker', many: 'workers' },
  { id: 'agent.', group: 'actor', one: 'agent', many: 'agents' },
  // What closes the loop.
  { id: 'route.classifier', group: 'control', one: 'router', many: 'routers' },
  // `revisePort` is what earns a mount card its "loops until its grader
  // passes" line. It used to be `type === 'route.grader'` and a literal
  // `'revise'` inside `core/`, so no other node family could ever close a
  // loop the card would notice.
  {
    id: 'route.grader',
    group: 'control',
    one: 'grader',
    many: 'graders',
    revisePort: 'revise',
  },
  // A fork a package function decides (`osg-agent-experience` 42). Control
  // for the same reason `guard.policy` below is: it *decides*, which is what
  // this group counts, and it calls no model while doing it. Named rather
  // than left to the family fallback, which would have counted it as "1
  // route" beside "1 router" and made a reader wonder which was which.
  { id: 'route.check', group: 'control', one: 'check router', many: 'check routers' },
  { id: 'human.approval', group: 'control', one: 'approval', many: 'approvals' },
  // Control, not reasoning: a guardrail calls no model. It is here because
  // it *decides* — `allowed` or `blocked` — which is what this group counts,
  // and because a mount card that never mentioned the child's policy would
  // be describing a safer workflow than the one it holds.
  { id: 'guard.policy', group: 'control', one: 'guardrail', many: 'guardrails' },
  // What they hold.
  // A mount card that never mentioned the child's memory would describe a
  // more forgetful workflow than the one it holds — the same argument that
  // put `guard.policy` above.
  { id: 'memory.', group: 'held', one: 'memory segment', many: 'memory segments' },
  { id: 'function.', group: 'held', one: 'function', many: 'functions' },
  { id: 'tool.', group: 'held', one: 'tool', many: 'tools' },
  { id: 'workflow.subgraph', group: 'held', one: 'workflow', many: 'workflows' },
  // The mount's own ports, drawn on the parent canvas — counting them inside
  // the box would describe the same wire twice.
  { id: 'input.', group: 'boundary', one: 'input', many: 'inputs' },
  { id: 'output.', group: 'boundary', one: 'output', many: 'outputs' },
  // Not machinery at all. Declared rather than omitted: an unregistered type
  // is *counted* under its family name, so silence would make a note-only
  // child read as "1 annotate".
  { id: 'annotate.', group: 'ignored', one: 'annotation', many: 'annotations' },
];
