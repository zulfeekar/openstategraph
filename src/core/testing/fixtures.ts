import { Workbench } from '@app/Workbench';
import { EdgeModel } from '@core/model/EdgeModel';
import { resetIds } from '@core/kernel/id';
import { AbstractNodeModel as AbstractNodeModelBase } from '@core/model/AbstractNodeModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeData } from '@core/model/contracts/fields';
import type { Point } from '@core/kernel/geometry';

/**
 * Test fixtures.
 *
 * Builds a real `Workbench` rather than mocks — the whole point of the
 * composition root is that the object graph can be stood up in isolation, so
 * tests exercise the actual wiring (registries, validators, command stack)
 * instead of a parallel fiction that can drift from it.
 *
 * Note `new Workbench()` and *not* `createWorkbench()`: the latter also calls
 * `applyLayoutTokens()`, which writes CSS custom properties to
 * `document.documentElement`. Tests run in a `node` environment with no DOM,
 * and that split is deliberate — it is why the DOM side effect lives in the
 * factory rather than the constructor.
 */
export function makeWorkbench(): Workbench {
  // Ids are minted from module-level counters, so without this a test's
  // expectations would depend on how many nodes earlier tests created.
  resetIds();
  return new Workbench();
}

export interface AddNodeOptions {
  readonly at?: Point;
  readonly data?: Partial<NodeData>;
}

/**
 * Adds a node directly to the model, bypassing the command stack.
 *
 * Use this for *arranging* a test. Anything asserting on undo/redo must go
 * through the controller instead, or the history under test is not the
 * history the app produces.
 */
export function addNode(
  workbench: Workbench,
  typeId: string,
  options: AddNodeOptions = {},
): AbstractNodeModel {
  const definition = workbench.registry.nodeTypes.require(typeId);
  const node = definition.create({
    position: options.at ?? { x: 0, y: 0 },
    ...(options.data ? { data: options.data } : {}),
  }) as AbstractNodeModel;
  workbench.model.addNode(node);
  return node;
}

/** Connects two ports directly, bypassing validation and the command stack. */
export function connect(
  workbench: Workbench,
  source: AbstractNodeModel,
  sourcePort: string,
  target: AbstractNodeModel,
  targetPort: string,
): EdgeModel {
  const edge = new EdgeModel({
    source: { nodeId: source.id, portId: sourcePort },
    target: { nodeId: target.id, portId: targetPort },
  });
  workbench.model.addEdge(edge);
  return edge;
}

export const LOOPABLE_TYPE = 'test.passthrough';

/**
 * Registers a synthetic node type with a symmetric `text` in and `text` out.
 *
 * Needed because **no cycle is expressible with the shipped catalogue**: the
 * only input that accepts a `result` belongs to the output node, which has no
 * output port. So `acyclicRule` cannot be reached through the real node types,
 * and testing it via them is impossible rather than merely awkward.
 *
 * A unit test should exercise the rule, not the catalogue's ability to express
 * a cycle — those are different claims. This type isolates the rule.
 *
 * (That the rule is currently unreachable in production is itself a finding:
 * see ticket 09, where cycles become required for grader loop-back.)
 */
export function registerLoopableType(workbench: Workbench): void {
  workbench.registry.nodeTypes.register({
    id: LOOPABLE_TYPE,
    kind: 'standard',
    category: 'inputs',
    label: 'Passthrough',
    description: 'Test-only node with symmetric text ports.',
    iconId: 'node-text-input',
    accent: 'neutral',
    fields: [],
    defaultSize: { width: 200, height: 80 },
    ports: () => [
      { id: 'in', direction: 'in', type: 'text', label: 'in' },
      { id: 'out', direction: 'out', type: 'text', label: 'out' },
    ],
    create: (init) => {
      const definition = workbench.registry.nodeTypes.require(LOOPABLE_TYPE);
      return new PassthroughNode(definition, init);
    },
  });
}

/** Concrete model for the synthetic test type. */
class PassthroughNode extends AbstractNodeModelBase {}

/** The catalogue's type ids, so tests don't hardcode strings. */
export const TYPE = {
  textInput: 'input.text',
  markdownFile: 'input.markdown',
  agent: 'agent.llm',
  redditSearch: 'tool.reddit-search',
  output: 'output.formatted',
  group: 'annotate.group',
  note: 'annotate.note',
  router: 'route.classifier',
  grader: 'route.grader',
  orchestrator: 'orchestrate.supervisor',
  worker: 'orchestrate.worker',
  formatReport: 'function.format_report',
} as const;
