import type { IAssemblyDefinition } from './contract';
import { GRADER_TYPE } from '../routing/GraderNode';
import { CATEGORY } from '../vocabulary';

// The agent node is factory-built (`createAgentNode`, so it can carry the
// shared model picker), so its id comes from the one table that names every
// type rather than from a second literal here.
const AGENT_TYPE = 'agent.llm';

export const REVISION_LOOP_ASSEMBLY_ID = 'assembly.revision-loop';

/** Laid out left to right, the same reading order the canvas uses. */
const AGENT_AT = { x: 0, y: 0 };
const GRADER_AT = { x: 340, y: 0 };

/**
 * Agent and grader, with `revise` already wired back to `feedback`.
 *
 * **Two nodes, not four.** The shape a developer describes is
 * `input → agent → grader → output` with the grader revising backwards, but
 * only the middle of that is *the loop*, and it is the only part that is hard
 * to discover: `revise → feedback` is the one edge a user finds by drawing an
 * illegal one and reading the rejection.
 *
 * Inserting an input and an output as well would duplicate whatever the canvas
 * already has — `output.formatted` declares no `maxInstances`, so nothing
 * would stop a second one appearing beside the first. A wired pair the
 * developer connects at both ends is honest; two orphaned sinks are not.
 */
export const revisionLoopAssembly: IAssemblyDefinition = {
  id: REVISION_LOOP_ASSEMBLY_ID,
  label: 'Revision loop',
  description:
    'An agent and a grader, with revise already wired back — the answer is rewritten until the grader passes it. Wire your input into the agent and the grader’s pass into your output.',
  iconId: 'assembly-revision-loop',
  category: CATEGORY.compose,
  keywords: ['loop', 'revise', 'revision', 'grader', 'evaluator', 'feedback', 'retry', 'critic'],
  fragment: {
    origin: AGENT_AT,
    nodes: [
      {
        id: 'loop-agent',
        type: AGENT_TYPE,
        position: AGENT_AT,
        size: { width: 300, height: 220 },
        // Required by `SerializedNode`: a fragment is the same shape a copy
        // produces, and a paste reparents by geometry after the drop anyway.
        parentId: null,
        title: 'Draft',
        data: {
          systemPrompt:
            'Answer the request directly and completely.\n\nWhen you are given feedback on a previous attempt, treat it as the specification: fix exactly what it names, keep what it did not object to, and do not start over.',
        },
      },
      {
        id: 'loop-grader',
        type: GRADER_TYPE,
        position: GRADER_AT,
        size: { width: 300, height: 220 },
        parentId: null,
        title: 'Review',
        data: {
          // A vague grader never passes, so the loop burns its whole attempt
          // budget and emits its best effort. Seeding real criteria is the
          // difference between a loop that improves an answer and one that
          // only costs model calls.
          criteria:
            '- The answer must address the request that was actually made.\n- Every factual claim must come from a tool result or be marked as uncertain — never invented.\n- Say what is wrong specifically enough that the next attempt can fix it.',
          rulesMode: 'extend',
          maxAttempts: '2',
        },
      },
    ],
    edges: [
      {
        source: { nodeId: 'loop-agent', portId: 'result' },
        target: { nodeId: 'loop-grader', portId: 'candidate' },
      },
      {
        // The edge the whole assembly exists for.
        source: { nodeId: 'loop-grader', portId: 'revise' },
        target: { nodeId: 'loop-agent', portId: 'feedback' },
      },
    ],
  },
};
