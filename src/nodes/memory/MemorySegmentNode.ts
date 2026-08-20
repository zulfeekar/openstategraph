import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const MEMORY_SEGMENT_TYPE = 'memory.segment';

const FIELD_SEGMENT = 'segment';
const FIELD_RETENTION = 'retention';
const FIELD_SEGMENT_NOTE = 'segmentNote';

/** The default a placed tollbooth carries — mirrored in `memory_segment.py`. */
export const MEMORY_SEGMENT_DEFAULT_RETENTION = '20';

/**
 * Retention, as a text box can express `int | None`.
 *
 * Blank means unbounded. This is the same shape — and the same reasoning —
 * as `maxRetries` in `ModelRegistry.ts`: `FieldValue` has no numeric "unset",
 * a slider's default is a required number, and `Infinity` does not survive
 * `JSON.stringify` (it becomes `"null"`, with nothing reporting the loss).
 *
 * Zero is refused rather than accepted as a synonym for unbounded. A ledger
 * that keeps zero entries is a node whose entire card is untrue, and nobody
 * types `0` meaning "everything".
 */
const DIGITS = /^[0-9]+$/;

/**
 * The one place this field becomes a number, in the one grammar the ledger
 * also reads: trimmed, ASCII digits only, above zero, and no larger than a
 * value both languages hold exactly. Blank and unparseable are the same
 * answer — `null`, meaning unbounded.
 *
 * It was a coercion plus an integer check, which is a far wider grammar
 * than it looks: `20.0`, `1e3`, `+5` and `0x14` all pass it, so the card accepted
 * them and its subtitle promised *keeps the last 20 / 1000 / 5 / 20* while
 * `parse_retention` — `str.isdigit()` — read every one of them as unbounded
 * (`memory-hardening/10`). The card was the half making a promise, so the card
 * is the half that narrowed.
 *
 * The ceiling is the same reasoning as the blank: a bound must survive the
 * round trip and mean one thing in both languages. Python holds
 * `999999999999999999999` exactly; coercion gives `1e+21`, which is what the
 * card would have printed. Above `MAX_SAFE_INTEGER` no bound can be stated
 * without the two disagreeing about it, so none is.
 *
 * `retentionGrammar.cases.json` is the grammar as data, and it is read by this
 * file's tests and by `backend/tests/test_retention_grammar_contract.py`.
 */
export const parseRetention = (value: string): number | null => {
  const raw = value.trim();
  if (!DIGITS.test(raw)) return null;
  const n = Number.parseInt(raw, 10);
  return n > 0 && n <= Number.MAX_SAFE_INTEGER ? n : null;
};

export const validateRetention = (value: string): string | null =>
  value.trim() === '' || parseRetention(value) !== null
    ? null
    : 'Must be a positive whole number in digits, or blank for everything';

/**
 * What the machinery does, shown read-only beside the two things a developer
 * owns.
 *
 * Not a pre-filled editable box: that was the original `RouterNode` bug, and
 * the block this node injects is Context in the prompt-composition sense —
 * generated, never authored. What a developer needs is to *see* it.
 */
export const MEMORY_SEGMENT_LOCKED_NOTE =
  'Every crossing does three things, in this order: it furnishes what the ' +
  'segment already holds into what flows onward, appends what arrived, and ' +
  'passes it all on. The heading and the numbering of the injected block are ' +
  'the machinery’s. Nothing here calls a model, so a crossing costs no tokens. ' +
  'The ledger is keyed by the segment name and this workflow, so the same name ' +
  'at several positions is one ledger, and it survives a restart. A Guardrail ' +
  'placed after this node scrubs what flows onward, not what was already ' +
  'recorded.';

export class MemorySegmentNodeModel extends AbstractNodeModel {
  get segment(): string {
    return this.getText(FIELD_SEGMENT).trim();
  }

  /** The configured limit, or `null` for unbounded — never a magic number. */
  get retention(): number | null {
    return parseRetention(this.getText(FIELD_RETENTION));
  }

  /**
   * The card, and deliberately only what is true with no run behind it.
   *
   * **No entry count.** The ledger is in the Store, which is server-side, so a
   * card cannot know its size before a run without a round trip; and reading
   * the count back out of the node's rendered output would mirror the Python
   * renderer across the seam with nothing pinning the two together. The count
   * is furnished by the run, in the block this node injects.
   */
  override get subtitle(): string {
    if (!this.segment) return 'No name yet — nothing is recorded.';
    const limit = this.retention;
    return limit === null
      ? `${this.segment} · keeps everything`
      : `${this.segment} · keeps the last ${limit}`;
  }
}

/**
 * A tollbooth on a wire: what crosses is furnished, recorded and passed on.
 *
 * ## Why a node and not a second memory tool
 *
 * `save_memory` already exists and is bound to every agent when a store is
 * present. It is the half of memory the *model* decides to use. This is the
 * other half: a write that happens because the flow reached a position, which
 * is a guarantee a drawing can make and a prompt cannot. Building one
 * mechanism for both would have produced a drawn node whose position implied
 * something the model was free to ignore.
 *
 * ## The name is the ledger, not the node
 *
 * Two tollbooths carrying the same segment name in one workflow are one
 * ledger, read and appended at both positions. That is what makes a segment a
 * thing you place rather than a thing you own, and it is why the identity is
 * a field rather than the node id.
 *
 * ## Zero tokens, and why that stays true
 *
 * Nothing here transforms what it records — the upstream output goes in
 * verbatim. A card claiming zero cost while a model ran somewhere in the path
 * is the failure this design avoids by construction: `memory_segment.py`
 * imports nothing that can call one, and a test asserts it.
 *
 * Compiles to a real state-transforming graph node over the durable Store's
 * workflow scope (`compile/node_runtime.py`'s `_memory_segment`).
 */
export const memorySegmentNode: INodeDefinition = defineNode(
  {
    id: MEMORY_SEGMENT_TYPE,
    category: CATEGORY.memory,
    label: 'Memory segment',
    description:
      'Records what crosses it, and hands the segment’s earlier entries to whatever comes next.',
    iconId: 'node-memory-segment',
    accent: 'teal',
    keywords: [
      'memory',
      'remember',
      'segment',
      'history',
      'ledger',
      'recall',
      'context',
      'notes',
      'persist',
      'across runs',
    ],
    defaultSize: { width: 260, height: 150 },
    fields: [
      {
        // The identity of the ledger. On the card because a tollbooth whose
        // name you cannot see is indistinguishable from a different one.
        kind: 'text',
        key: FIELD_SEGMENT,
        label: 'Segment',
        hint: 'The same name at several positions is one ledger, shared across every run of this workflow.',
        placeholder: 'notes',
        // A working default rather than a blank, following the Grader's
        // prebuilt criteria and the Guardrail's two rules: a node dragged
        // out and wired up should already do the thing it says.
        defaultValue: 'notes',
        maxLength: 60,
      },
      {
        // `int | None`. Visible rather than constant, because an unbounded
        // ledger becomes a context-window failure three months later — at
        // which point the number nobody can see is the one that needs
        // changing.
        kind: 'text',
        key: FIELD_RETENTION,
        label: 'Keep the last',
        hint: 'Entries. Leave empty to keep everything — there is no number here that means unbounded.',
        placeholder: MEMORY_SEGMENT_DEFAULT_RETENTION,
        defaultValue: MEMORY_SEGMENT_DEFAULT_RETENTION,
        validate: validateRetention,
      },
      {
        kind: 'readonly',
        key: FIELD_SEGMENT_NOTE,
        label: 'What the machinery already does',
        defaultValue: MEMORY_SEGMENT_LOCKED_NOTE,
        onCard: false,
        group: 'Segment',
      },
    ],
    ports: [
      {
        id: 'crossing',
        direction: 'in',
        type: PORT.result,
        label: 'crossing',
        description: 'Whatever should be recorded on its way past.',
      },
      {
        id: 'onward',
        direction: 'out',
        type: PORT.result,
        label: 'onward',
        description:
          'What arrived, with the segment’s earlier entries furnished above it as context.',
      },
    ],
  },
  MemorySegmentNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Guardrail's and the Grader's.
 *
 * Registered rather than omitted because a `standard` node with no executor is
 * **silently skipped** by the preview engine. A skipped tollbooth is the worst
 * outcome available here: the preview would look successful, and a developer
 * would conclude the workflow remembered something it never recorded.
 */
export const memorySegmentExecutor: INodeExecutor = {
  id: MEMORY_SEGMENT_TYPE,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('The ledger lives in the durable Store, which the browser preview cannot reach.');
    return Promise.resolve(
      Err(
        'This Memory segment reads and appends the Python runtime’s durable Store. Use “Run” ' +
          'against the backend, or Chat, so what it records outlives the run.',
      ),
    );
  },
};
