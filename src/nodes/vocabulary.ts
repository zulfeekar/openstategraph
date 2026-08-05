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
  agent: 'agent',
  tools: 'tools',
  output: 'output',
  annotate: 'annotate',
} as const;

export const CATEGORIES: readonly INodeCategory[] = [
  { id: CATEGORY.inputs, label: 'Inputs', order: 10 },
  { id: CATEGORY.agent, label: 'Agent', order: 20 },
  { id: CATEGORY.tools, label: 'Tools', order: 30 },
  { id: CATEGORY.output, label: 'Output', order: 40 },
  { id: CATEGORY.annotate, label: 'Annotate', order: 50 },
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
