import type { ClipboardFragment } from '@controller/ClipboardService';
import { GRADER_TYPE } from '../routing/GraderNode';
import { CATEGORY } from '../vocabulary';

// The agent node is factory-built (`createAgentNode`, so it can carry the
// shared model picker), so its id comes from the one table that names every
// type rather than from a second literal here.
const AGENT_TYPE = 'agent.llm';

/**
 * A wired assembly you drag onto the canvas you are already working in.
 *
 * **Not a node type**, and that is the whole point. A `Loop` node would compile
 * to nothing new — recorded in the organism-taxonomy research, in the `loop`
 * template's ticket, and in `templates/index.json` — because a loop is a
 * *cycle in the graph*, not a box around one. What drops here is ordinary
 * nodes and ordinary edges; afterwards the document is indistinguishable from
 * one drawn by hand, which is what keeps `workflow.json` portable.
 *
 * **Not a template, either.** A template produces a whole new document and
 * stops existing (`--template loop`, the editor's *Start from* picker). This
 * adds to a document that already exists. Ticket 01 shipped the first and its
 * own notes claimed the second; ticket 21 is the correction.
 *
 * The tier is **organism** — an assembly of molecules. Ticket 14 established
 * that organisms are the only tier obtainable two ways, *drawn or dragged*,
 * and dragging one had only ever meant mounting a package. This is the other
 * half of that rule.
 */
export interface IAssemblyDefinition {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly iconId: string;
  /** Which palette section it appears in. */
  readonly category: string;
  readonly keywords: readonly string[];
  /**
   * The nodes and edges to insert, in the clipboard's own fragment shape.
   *
   * Deliberately the same type a copy produces: inserting an assembly *is* a
   * paste of a canned fragment, so it inherits id remapping, edge rewiring,
   * instance caps and the single undoable command rather than growing a
   * second mechanism beside them.
   */
  readonly fragment: ClipboardFragment;
}

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

/**
 * The assemblies the palette offers.
 *
 * One entry, deliberately. A general "insert a wired assembly" mechanism with
 * fan-out + join and router + branches to follow was considered and declined:
 * the second and third entries are speculative until somebody asks for them,
 * and `CLAUDE.md` is explicit about not paying for an extension point before
 * there is a second case. It is a list so that adding one is a data change.
 */
export const ASSEMBLIES: readonly IAssemblyDefinition[] = [revisionLoopAssembly];

/** The assembly a palette drag names, or `null` for an unknown id. */
export function assemblyById(id: string): IAssemblyDefinition | null {
  return ASSEMBLIES.find((assembly) => assembly.id === id) ?? null;
}
