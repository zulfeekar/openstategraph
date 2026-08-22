import { describe, expect, it } from 'vitest';
import {
  MEMORY_SEGMENT_TYPE,
  parseRetention,
  validateRetention,
  memorySegmentNode,
  memorySegmentExecutor,
  type MemorySegmentNodeModel,
} from './MemorySegmentNode';
import { CATEGORIES, CATEGORY, PORT } from '../vocabulary';
import { NODE_TYPE } from '../index';
import { defaultsFrom } from '@core/model/contracts/fields';
import { makeWorkbench } from '@core/testing/fixtures';
import retentionCases from './retentionGrammar.cases.json';
import { EXECUTION_OVERRIDE_KEYS } from '../../core/model/ModelRegistry';

/**
 * The tollbooth — install-experience ticket 17, built through
 * `skills/atom-forge` as its first live client.
 *
 * What these tests pin is the **seam**: the id string the Python builder is
 * keyed by, the two field keys its factory reads, the port types, and the
 * defaults. Everything the ledger *does* is asserted in Python
 * (`backend/tests/test_memory_segment.py`) where the Store is; asserting it
 * twice in two languages is the duplication this repository's DRY rule names.
 */
const field = (key: string) => memorySegmentNode.fields.find((f) => f.key === key);
const ports = (data = defaultsFrom(memorySegmentNode.fields)) => memorySegmentNode.ports(data);
const port = (id: string) => ports().find((p) => p.id === id);

const placed = () => {
  const workbench = makeWorkbench();
  workbench.controller.nodes.add(MEMORY_SEGMENT_TYPE, { x: 0, y: 0 });
  const node = workbench.model
    .nodes()
    .find((n) => n.type === MEMORY_SEGMENT_TYPE) as MemorySegmentNodeModel;
  return { workbench, node };
};

describe('the seam the Python builder is keyed by', () => {
  it('answers to the one id the compiler dispatches on', () => {
    expect(MEMORY_SEGMENT_TYPE).toBe('memory.segment');
    expect(NODE_TYPE.memorySegment).toBe(MEMORY_SEGMENT_TYPE);
  });

  it('declares exactly the two keys the factory reads', () => {
    // A `data` key no field declares reads `""` forever, silently — the
    // defect `test_data_key_contract.py` exists to make impossible. Asserted
    // in the other direction too, so a third *configurable* field cannot
    // arrive without somebody deciding what reads it. The two execution
    // overrides are the compiler's graph-assembly parameters, appended to
    // every standard node, and `segmentNote` is a read-only readout rather
    // than configuration.
    const own = memorySegmentNode.fields
      .map((f) => f.key)
      .filter((key) => ![...EXECUTION_OVERRIDE_KEYS, 'segmentNote'].includes(key));
    expect(own.sort()).toEqual(['retention', 'segment']);
  });

  it('never gives a port an id a field also uses', () => {
    // A port id and a field key are different namespaces; one name across
    // both reads as one thing and behaves as two.
    const keys = new Set(memorySegmentNode.fields.map((f) => f.key));
    for (const p of ports()) expect(keys.has(p.id)).toBe(false);
  });
});

describe('a tollbooth is transparent to the graph', () => {
  it('takes one result in and passes one result out', () => {
    expect(port('crossing')?.direction).toBe('in');
    expect(port('crossing')?.type).toBe(PORT.result);
    expect(port('onward')?.direction).toBe('out');
    expect(port('onward')?.type).toBe(PORT.result);
  });

  it('leaves cardinality to the port defaults, so nothing has to name infinity', () => {
    // In defaults to 1, out to unlimited. A descriptor stating `Infinity`
    // would not survive `JSON.stringify`, which turns it into `null` with
    // nothing reporting the loss.
    for (const p of ports()) expect(p.maxConnections).toBeUndefined();
  });

  it('declares no feedback port, so it cannot close a cycle', () => {
    expect(ports().some((p) => p.type === PORT.feedback)).toBe(false);
  });

  it('has one input and one output and nothing else', () => {
    // Same type in and out is what lets one segment name sit between several
    // node pairs without changing what flows.
    expect(
      ports()
        .map((p) => p.id)
        .sort(),
    ).toEqual(['crossing', 'onward']);
  });
});

describe('the two fields, and the one that must not be a number', () => {
  it('names the segment, because the name is the ledger', () => {
    expect(field('segment')?.kind).toBe('text');
    expect(field('segment')?.onCard).not.toBe(false);
  });

  it('ships a working default rather than a blank ledger', () => {
    expect(field('segment')?.defaultValue).toBe('notes');
    expect(field('retention')?.defaultValue).toBe('20');
  });

  it('expresses retention as int-or-empty, never as a slider', () => {
    // `int | None`, `None` meaning unbounded — honesty gate 3. A slider has a
    // required numeric default, so "unbounded" would have to be spelled as a
    // magic number, and `Infinity` does not survive JSON at all.
    expect(field('retention')?.kind).toBe('text');
  });

  it('says what an empty retention means, where the person typing it is looking', () => {
    const copy = `${field('retention')?.label ?? ''} ${field('retention')?.hint ?? ''}`;
    expect(copy.toLowerCase()).toMatch(/empty|blank/);
    expect(copy.toLowerCase()).toMatch(/unbounded|everything|no limit|forever/);
  });

  it('refuses a retention that is neither a positive whole number nor empty', () => {
    const validate = field('retention')?.validate as ((v: string) => string | null) | undefined;
    expect(validate).toBeDefined();
    expect(validate!('')).toBeNull();
    expect(validate!('20')).toBeNull();
    expect(validate!('0')).not.toBeNull();
    expect(validate!('-4')).not.toBeNull();
    expect(validate!('lots')).not.toBeNull();
  });

  it('offers no control over what it injects', () => {
    // The furnished block is a Context section — machinery. Shipping its
    // wording as an editable pre-filled field is the original RouterNode bug,
    // and there is deliberately nothing here to clear.
    const keys = memorySegmentNode.fields.map((f) => f.key);
    for (const forbidden of ['heading', 'template', 'contextPrefix', 'systemPrompt']) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it('shows the machinery read-only instead of leaving it to be guessed at', () => {
    expect(field('segmentNote')?.kind).toBe('readonly');
  });
});

describe('the card is true before anything has run', () => {
  it('reads the segment name and the retention off the document', () => {
    const { workbench, node } = placed();
    expect((workbench.model.node(node.id) as MemorySegmentNodeModel).subtitle).toContain('notes');
    expect((workbench.model.node(node.id) as MemorySegmentNodeModel).subtitle).toContain('20');
  });

  it('says it keeps everything when retention is empty', () => {
    const { workbench, node } = placed();
    workbench.controller.nodes.setField(node.id, 'retention', '');
    expect(
      (workbench.model.node(node.id) as MemorySegmentNodeModel).subtitle.toLowerCase(),
    ).toContain('everything');
  });

  it('says plainly that an unnamed segment records nothing', () => {
    // The empty state must not read as an error — that trains people to
    // ignore the card — but it must not read as working either.
    const { workbench, node } = placed();
    workbench.controller.nodes.setField(node.id, 'segment', '   ');
    const subtitle = (workbench.model.node(node.id) as MemorySegmentNodeModel).subtitle;
    expect(subtitle.toLowerCase()).toMatch(/no name|nothing/);
  });

  it('never claims a live entry count, which a card cannot know', () => {
    // The Store is server-side. A count on an unrun card would be a promise
    // the platform cannot keep; the run furnishes it instead.
    const { workbench, node } = placed();
    expect((workbench.model.node(node.id) as MemorySegmentNodeModel).subtitle).not.toMatch(
      /\d+ entr/,
    );
  });
});

describe('the catalogue registers it honestly', () => {
  it('is registered and reachable by id', () => {
    expect(makeWorkbench().registry.nodeTypes.get(MEMORY_SEGMENT_TYPE)).toBeDefined();
  });

  it('claims a molecule tier under a heading that is true of it', () => {
    // It composes — the ledger and the crossing become one thing going
    // onward — so it is not an atom; it brings no nodes, state or loop of its
    // own, so it is not an organism. It is filed away from `Reasoning &
    // control` because a tollbooth neither reasons nor decides, and that
    // label's honesty is what `vocabulary.test.ts` exists to protect.
    expect(memorySegmentNode.category).toBe(CATEGORY.memory);
    const section = CATEGORIES.find((c) => c.id === CATEGORY.memory);
    expect(section?.label).toContain('molecules');
    expect(section?.label).not.toContain('Reasoning');
  });

  it('is findable by the words someone with this problem would type', () => {
    const words = memorySegmentNode.keywords ?? [];
    for (const term of ['memory', 'remember', 'history', 'segment']) {
      expect(words).toContain(term);
    }
  });

  it('never calls itself a summary, which it does not produce', () => {
    // Zero tokens is the claim, and it is true only because nothing here
    // transforms what it records. Copy implying a summary would invite the
    // model call that makes the claim false.
    const copy = `${memorySegmentNode.label} ${memorySegmentNode.description}`.toLowerCase();
    expect(copy).not.toMatch(/summar|condens|distil/);
  });
});

describe('the browser preview refuses rather than pretending', () => {
  it('reports that the ledger lives in the Python runtime', async () => {
    // A `standard` node with no registered executor is silently skipped by
    // the preview engine, and a skipped tollbooth is a run that looks as
    // though it remembered.
    const outcome = await memorySegmentExecutor.execute({ log: () => {} } as never);
    expect(outcome.ok).toBe(false);
  });
});

/**
 * The other half of `backend/tests/test_retention_grammar_contract.py`.
 *
 * `memory-hardening/10`. Both files read the same table — one grammar, stated
 * once as data — so the card and the ledger cannot disagree about what a
 * retention limit is without one of the two suites going red on the same file.
 * Asserting a list of accepted spellings here alone would not have caught the
 * defect: the card was internally consistent and wrong.
 */
describe('the retention grammar the ledger also reads', () => {
  const table = retentionCases as {
    cases: { input: string; retention: number | null; why: string }[];
  };

  for (const { input, retention, why } of table.cases) {
    it(`reads ${JSON.stringify(input)} as ${retention === null ? 'unbounded' : retention} — ${why}`, () => {
      expect(parseRetention(input)).toBe(retention);
    });
  }

  it('refuses every non-blank input the ledger will not keep a bound for', () => {
    for (const { input, retention } of table.cases) {
      const blank = input.trim() === '';
      const error = validateRetention(input);
      expect(error === null).toBe(blank || retention !== null);
    }
  });

  it('never subtitles a bound the ledger would treat as unbounded', () => {
    const { workbench, node } = placed();
    for (const { input, retention } of table.cases) {
      workbench.controller.nodes.setField(node.id, 'segment', 'notes');
      workbench.controller.nodes.setField(node.id, 'retention', input);
      expect(node.subtitle).toBe(
        retention === null ? 'notes · keeps everything' : `notes · keeps the last ${retention}`,
      );
    }
  });
});
