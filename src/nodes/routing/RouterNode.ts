import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { NodeData } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { IPortDescriptor } from '@core/model/contracts/ports';
import type {
  ExecutionContext,
  INodeExecutor,
  PortOutputs,
} from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const ROUTER_TYPE = 'route.classifier';

const FIELD_RULES = 'rules';
const FIELD_BRANCHES = 'branches';
const FIELD_FALLBACK = 'fallback';
const FIELD_TIER = 'tier';

/**
 * How many branches a card can show before it stops being readable.
 *
 * A cap rather than a scroll: a router with twenty destinations is a design
 * problem the editor should surface, not hide behind a scrollbar.
 */
export const MAX_BRANCHES = 12;

const DEFAULT_BRANCHES = ['dataquery', 'info', 'help', 'greeting', 'off_topic'].join('\n');

const slug = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'branch';

/**
 * The branch names a router is configured with.
 *
 * Newline-separated text for now. A repeatable-group field kind is the right
 * home for this and belongs to ticket 20 — inventing one inside a prototype
 * would settle that design by accident. The parsing rules below are the ones
 * that stop a half-typed list from producing a broken node.
 */
export function branchesOf(data: Readonly<NodeData>): string[] {
  const raw = typeof data[FIELD_BRANCHES] === 'string' ? (data[FIELD_BRANCHES] as string) : '';
  const seen = new Set<string>();
  const names: string[] = [];

  for (const line of raw.split('\n')) {
    const name = line.trim();
    if (name === '') continue;
    // Dedupe on the slug, not the name: two names that slugify alike would
    // collide as port ids, and a node cannot have two ports with one id.
    const key = slug(name);
    if (seen.has(key)) continue;
    seen.add(key);
    names.push(name);
    if (names.length >= MAX_BRANCHES) break;
  }

  // Never zero outputs. A router with none is unwireable and reads as broken;
  // one default output is something the user can rename.
  return names.length > 0 ? names : ['default'];
}

/** Locked. Not a field, so it cannot be cleared or contradicted. */
export const ROUTER_PREAMBLE =
  'You are a router. Your only job is to decide which single branch a message ' +
  'belongs to. You never answer the message itself.';

/** Locked, and rendered **last** so developer rules cannot override it. */
export const ROUTER_OUTPUT_CONTRACT =
  'Reply with exactly one branch name from the list above. No punctuation, no ' +
  'explanation, no quotes — the branch name alone.';

export class RouterNodeModel extends AbstractNodeModel {
  /** The one part the developer writes. */
  get rules(): string {
    return this.getText(FIELD_RULES);
  }

  /**
   * The whole prompt, assembled.
   *
   * Mirrors `BaseRouter.system_prompt()` in Python, and the ordering is the
   * substance: preamble, then the branch list, then the developer's rules, then
   * the output contract **last**. Later instructions win ties, so a rule such as
   * "explain your reasoning" must not be able to come after the contract or
   * every classification would fail to parse.
   *
   * Exposed so the inspector can show the locked sections read-only beside the
   * editable one — a developer writing rules needs to see what the machinery
   * already says, or they duplicate and contradict it.
   */
  get systemPrompt(): string {
    const listed = this.branches
      .map((name) => (name === this.fallback ? `- ${name}  (used when nothing else matches)` : `- ${name}`))
      .join('\n');
    const rules = this.rules.trim();
    return [
      ROUTER_PREAMBLE,
      `Branches:\n${listed}`,
      ...(rules ? [`Rules:\n${rules}`] : []),
      ROUTER_OUTPUT_CONTRACT,
    ].join('\n\n');
  }

  get branches(): readonly string[] {
    return branchesOf(this.data);
  }

  get fallback(): string {
    return this.getText(FIELD_FALLBACK);
  }
}

/**
 * Classifies its input and sends it down exactly one branch.
 *
 * The first **role preset** (ticket 28). Role is the node type because it decides
 * ports and compile target; the *tier* — which factory builds the underlying loop
 * — is a field, because it changes neither. Making both node types would give a
 * palette of role x tier.
 *
 * Compiles to `add_conditional_edges(source, path, path_map)`. The branch list is
 * what produces the **complete declared destination set** ticket 03 requires:
 * without it every renderer has to assume the router might reach any node, and
 * draws it connected to everything.
 *
 * **Known sharp edge:** a port id is derived from its branch name, so *renaming*
 * a branch changes the id and the edge attached to it is dropped — the serializer
 * warns and discards links to ports that no longer exist. Stable ids that survive
 * a rename need the repeatable-group field (ticket 20), where each branch can
 * carry its own generated id alongside its label.
 */
export const routerNode: INodeDefinition = defineNode(
  {
    id: ROUTER_TYPE,
    category: CATEGORY.agent,
    label: 'Router',
    description: 'Classifies the input and sends it down one branch.',
    iconId: 'node-router',
    accent: 'violet',
    keywords: ['route', 'classify', 'branch', 'switch', 'intent', 'supervisor'],
    defaultSize: { width: 268, height: 210 },
    fields: [
      {
        kind: 'textarea',
        key: FIELD_RULES,
        label: 'Routing rules',
        // Rules *only*. The preamble and the output contract are locked on the
        // base and are not fields, because a developer who cleared them would
        // get a router whose answer cannot be parsed.
        placeholder: 'If it mentions revenue or tables → dataquery. A hello → greeting.',
        defaultValue: '',
        minRows: 3,
      },
      {
        kind: 'textarea',
        key: FIELD_BRANCHES,
        label: 'Branches',
        placeholder: 'One branch per line',
        defaultValue: DEFAULT_BRANCHES,
        minRows: 3,
        // Each line becomes an output port, so this field is what shapes the node.
        validate: (value) =>
          value.trim().length === 0 ? 'Add at least one branch' : null,
      },
      {
        kind: 'text',
        key: FIELD_FALLBACK,
        label: 'Fallback branch',
        placeholder: 'Used when nothing matches',
        defaultValue: 'off_topic',
        onCard: false,
      },
      {
        kind: 'select',
        key: FIELD_TIER,
        label: 'Runtime',
        defaultValue: 'react',
        onCard: false,
        options: [
          { value: 'react', label: 'Agent · create_agent' },
          { value: 'deep', label: 'Deep agent · create_deep_agent' },
          { value: 'custom', label: 'Custom · hand-written node' },
        ],
      },
    ],
    // Dynamic ports. No new mechanism — `ports` has always been a function of
    // node data; this is the first node type to actually need it.
    ports: (data: Readonly<NodeData>): IPortDescriptor[] => {
      const fallback = typeof data[FIELD_FALLBACK] === 'string' ? data[FIELD_FALLBACK] : '';
      const branches = branchesOf(data);

      const inputs: IPortDescriptor[] = [
        {
          id: 'question',
          direction: 'in',
          type: PORT.text,
          label: 'question',
          description: 'The text to classify.',
        },
      ];

      // Declaration order is preserved, because the order the user typed the
      // branches in is the order they expect to see them down the card.
      const outputs = branches.map((name): IPortDescriptor => {
        const isFallback = fallback.trim() !== '' && slug(fallback) === slug(name);
        return {
          id: `branch:${slug(name)}`,
          direction: 'out',
          type: PORT.text,
          label: name,
          description: isFallback
            ? 'Fallback — taken when no other branch matches.'
            : `Taken when the input classifies as "${name}".`,
        };
      });

      // Guard against a slug collision producing duplicate ids, which would
      // silently drop a port rather than fail loudly.
      const ids = new Set<string>();
      const unique = outputs.map((port) => {
        if (!ids.has(port.id)) {
          ids.add(port.id);
          return port;
        }
        let suffix = 2;
        while (ids.has(`${port.id}-${suffix}`)) suffix += 1;
        const id = `${port.id}-${suffix}`;
        ids.add(id);
        return { ...port, id };
      });

      return [...inputs, ...unique];
    },
  },
  RouterNodeModel,
);


/**
 * Browser-preview executor — deliberately refuses to run.
 *
 * A router compiles to `add_conditional_edges` in the **Python** runtime, and
 * ticket 07 bars the browser from executing a workflow. So there is nothing
 * honest for this to do.
 *
 * It exists rather than being omitted because a `standard` node with no
 * registered executor is **silently skipped** by the preview engine — the run
 * would appear to succeed while the routing never happened. Failing with a clear
 * message is strictly better than a quiet wrong answer.
 *
 * Two things it deliberately does *not* do: classify using the browser's mock
 * provider, which would fake a routing decision the real runtime makes
 * differently; and duplicate the Python classification logic, which would put
 * the same knowledge in two places. It is expected to be deleted along with
 * `core/execution` when the FastAPI runtime takes over.
 */
export const routerExecutor: INodeExecutor = {
  id: routerNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('Routing is evaluated by the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Router compiles to a LangGraph conditional edge and runs in the Python ' +
          'runtime. Use “Run” against the backend to evaluate it.',
      ),
    );
  },
};
