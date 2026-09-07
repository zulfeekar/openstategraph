import type { RunLane, TimelineStep } from '../ask/timeline';

/**
 * What the selected step **asked**, and what it **produced**.
 *
 * `memory-and-replay` 59 — the half of the prototype's detail pane that 58
 * shipped without, and said so at the time: *"`ActivityRow.output` is one
 * opaque string and the fold does not keep it, so the per-family readings the
 * prototype showed would be invented here."*
 *
 * # Where the reading happens, which is the thing 59 asked to be decided
 *
 * **In the fold, and this module words it.** 59 listed four existing readers
 * of a run's output — `traceTree`, `decisionRows`, `graderVerdictLine`,
 * `toolResults` — and asked which is the seam before a seventh is written.
 * None of them is: the first renders the string as prose and asks nothing of
 * it, and the other three read the **terminal record** (`RunResult.decisions`,
 * `routes`, `verdict`), which is a different object arriving at a different
 * time and keyed by node rather than by bar.
 *
 * So nothing is parsed here. `TimelineStep.payload` carries the three values
 * the run put on this bar's own frames, and this module decides what to *call*
 * them for the kind of bar it is, and what to say when there is nothing. That
 * is the whole of the per-family difference, and it needed no parser — which
 * is why 59's fear of *"a set of parsers"* did not have to be paid.
 *
 * # Why there is no per-canvas-family branch
 *
 * 59's table is by canvas node family — router, supervisor, worker, grader,
 * mount, subagent, output node. **The fold does not know those words and must
 * not learn them**: a bar's identity here is `StepKind` (what it did) and its
 * lane (who dispatched it), both derived from frames, and a node's *family* is
 * a property of the document, which a run does not carry and which can have
 * been edited since. Branching on a label parsed out of a node id is the
 * second-source-of-truth this pane exists to avoid.
 *
 * What the table actually asked for survives the translation, because the
 * families it names map onto the two facts the run does report:
 *
 * | 59's family | what it wanted | what says it here |
 * | --- | --- | --- |
 * | worker, subagent | its subtask · its result | the **lane**'s `instruction`, and the bar's own output |
 * | grader | the verdict **and the reason** | `payload.check` + `payload.reason`, on a `refusal` bar |
 * | mount | the package and the task · the child's nested outputs | the mount bar's output, worded as another document's |
 * | router, supervisor, output node | routes · subtasks · the published answer | the bar's own output — each of these *is* what that node wrote to `outputs` |
 *
 * The one thing not translated is a router's **full** match list, and it is
 * left out deliberately rather than forgotten: `routes` is keyed by node and
 * merged across the run, so a router that ran twice has one row, and hanging
 * it on a particular bar would be a claim the record cannot support. It is
 * already published where it *is* true — beside the answer, by `decisionRows`,
 * about the run as a whole.
 *
 * # The audience boundary
 *
 * Nothing is decided here, and that is the point. `output` is the server's
 * own `outputs[node]` / `worker_results[taskId]` — both `CUSTOMER_VISIBLE`
 * channels — passed through `_redact_for(audience)` **before it is put on the
 * wire**, and a spawn's `instruction` likewise. So a payload that reached this
 * tab is a payload this reader was entitled to, and re-deciding it on the
 * client would be the fourth convention `api/audience.py` exists to replace.
 * (The editor asks as `developer` in any case; that is a fact about this
 * caller, not the boundary, and this module does not rely on it.)
 */
export interface PayloadHalf {
  readonly heading: 'Asked' | 'Produced';
  /**
   * What the run recorded, verbatim. **`null`, never `''`** — the same rule
   * `launch-readiness` 108 fixed for a duration, one field over: a step that
   * answered with nothing and a step nobody recorded an answer for are two
   * facts, and a blank box says neither.
   */
  readonly text: string | null;
  /**
   * What this half is, in words — and when `text` is `null`, **why it is
   * empty**. Always present, which is the structural form of `52`'s rule: a
   * pane that would show an empty box has to say why instead.
   */
  readonly caption: string;
}

/**
 * The two halves of the selected bar's payload, in the prototype's order.
 *
 * Pure, so every sentence below is asserted rather than eyeballed.
 */
export function askedAndProduced(
  lane: RunLane,
  step: TimelineStep,
): readonly [PayloadHalf, PayloadHalf] {
  return [asked(lane), produced(step)];
}

function asked(lane: RunLane): PayloadHalf {
  if (lane.instruction !== null) {
    return {
      heading: 'Asked',
      text: lane.instruction,
      caption: `The task the run handed this ${childWord(lane.kind)}, as it wrote it down.`,
    };
  }
  return {
    heading: 'Asked',
    text: null,
    // Stated as a property of the recording, not of the step. A node was of
    // course asked something; the run did not record it, and those are the
    // two different sentences this codebase keeps having to separate.
    caption:
      'The run records what a step was asked only for a step it spawned. A node’s own ' +
      'prompt is composed inside the runtime and never reaches this stream.',
  };
}

/** What to call a child of this lane's kind — never "worker" for all three. */
function childWord(kind: RunLane['kind']): string {
  if (kind === 'subagent') return 'subagent';
  if (kind === 'async') return 'background worker';
  return 'worker';
}

function produced(step: TimelineStep): PayloadHalf {
  const { output, check, reason } = step.payload;
  if (step.kind === 'refusal' && check !== null) {
    // The verdict *and* the reason — 59 named that pairing for the grader
    // specifically, and `graderVerdictLine` already established that a verdict
    // with no sentence is still worth saying while a sentence with no verdict
    // is not. `check` is the subject, so it goes in the caption and the
    // model's own words stay in the quotation.
    return {
      heading: 'Produced',
      text: reason,
      caption:
        reason === null
          ? `A refusal. The “${check}” check rejected this without a model call, and ` +
            'the run wrote no sentence for it.'
          : `A refusal. The “${check}” check rejected this without a model call:`,
    };
  }
  if (output === null) {
    return {
      heading: 'Produced',
      text: null,
      caption:
        'The run recorded no output for this step. An input, a join and a node that only ' +
        'moved state report nothing here — that is the step being quiet, not the recording ' +
        'losing it.',
    };
  }
  return {
    heading: 'Produced',
    text: output,
    caption:
      step.kind === 'mount'
        ? 'What the mounted workflow returned — another document’s answer, folded into this ' +
          'step.'
        : 'What this step wrote, on this lap. A later visit to the same node is a bar of its ' +
          'own and carries its own.',
  };
}
