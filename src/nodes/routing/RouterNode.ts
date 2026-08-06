import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { FieldValue, NodeData } from '@core/model/contracts/fields';
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

/** One branch entry with a stable id that survives renames. */
export interface BranchEntry {
  /** Stable, generated-once id — survives renames. */
  id: string;
  /** The visible branch name — can be renamed freely. */
  name: string;
  [key: string]: FieldValue;
}

const DEFAULT_BRANCHES: BranchEntry[] = [
  { id: 'b1', name: 'dataquery' },
  { id: 'b2', name: 'info' },
  { id: 'b3', name: 'help' },
  { id: 'b4', name: 'greeting' },
  { id: 'b5', name: 'off_topic' },
];

const slug = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    // Underscores are preserved, not collapsed into hyphens: this suffix is
    // not cosmetic — the backend compiler recovers the literal branch label
    // by stripping the `branch:` prefix off this exact port id
    // (`workflow_compiler.py`: `src.get("portId", "").removeprefix("branch:")`)
    // and matches it against the router's own classification output, which
    // echoes a branch name verbatim (e.g. "off_topic", "general_knowledge").
    // Found live: a real saved document (the intent-routed demo) has edges
    // pointing at `branch:off_topic`, but this function used to produce
    // `branch:off-topic` for the same branch — a mismatch invisible until
    // the document was loaded, at which point `fromJSON` silently dropped
    // both underscore-named branches' edges as pointing to "a port that no
    // longer exists" (its own honest warning, but for the wrong reason: the
    // port never actually moved, this function just stopped agreeing with
    // itself). Re-saving from the editor in that state would have made the
    // loss permanent.
    .replace(/[^a-z0-9_]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'branch';

/**
 * The branch entries a router is configured with.
 *
 * Each entry has a stable `id` that survives renames — edges reference the
 * id, not the name, so renaming a branch no longer drops its edge.
 *
 * Backward compatible: if `branches` is a newline-separated string (v1 format),
 * it is migrated to the array format with generated stable ids.
 */
export function branchesOf(data: Readonly<NodeData>): BranchEntry[] {
  const raw = data[FIELD_BRANCHES];

  // Migration: old format was newline-separated text
  if (typeof raw === 'string') {
    const seen = new Set<string>();
    const result: BranchEntry[] = [];
    for (const line of raw.split('\n')) {
      const name = line.trim();
      if (name === '') continue;
      const id = slug(name);
      if (seen.has(id)) continue;
      seen.add(id);
      result.push({ id, name });
      if (result.length >= MAX_BRANCHES) break;
    }
    return result.length > 0 ? result : [{ id: 'default', name: 'default' }];
  }

  if (!Array.isArray(raw)) return DEFAULT_BRANCHES;

  const entries = raw as Array<Record<string, unknown>>;
  const seen = new Set<string>();
  const result: BranchEntry[] = [];

  for (const entry of entries) {
    const id = typeof entry.id === 'string' ? entry.id : null;
    const name = typeof entry.name === 'string' ? entry.name : '';
    if (!id || !name) continue;
    // Dedupe on id: if two entries somehow got the same id, keep the first.
    if (seen.has(id)) continue;
    seen.add(id);
    result.push({ id, name });
    if (result.length >= MAX_BRANCHES) break;
  }

  // Never zero outputs. A router with none is unwireable and reads as broken.
  return result.length > 0 ? result : [{ id: 'default', name: 'default' }];
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
      .map((entry) => (entry.name === this.fallback ? `- ${entry.name}  (used when nothing else matches)` : `- ${entry.name}`))
      .join('\n');
    const rules = this.rules.trim();
    return [
      ROUTER_PREAMBLE,
      `Branches:\n${listed}`,
      ...(rules ? [`Rules:\n${rules}`] : []),
      ROUTER_OUTPUT_CONTRACT,
    ].join('\n\n');
  }

  get branches(): readonly BranchEntry[] {
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
 * **Stable branch ids:** each branch has a generated-once `id` that survives
 * renames — edges reference `branch:${id}`, so renaming a branch no longer
 * drops its edge (ticket 20 fix).
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
        kind: 'repeatable-group',
        key: FIELD_BRANCHES,
        label: 'Branches',
        defaultValue: DEFAULT_BRANCHES,
        addLabel: 'Add branch',
        maxRows: MAX_BRANCHES,
        fields: [
          {
            kind: 'text',
            key: 'name',
            label: 'Branch name',
            placeholder: 'e.g. dataquery',
            defaultValue: '',
            validate: (value) => (value.trim() ? null : 'Name required'),
          },
        ],
        // Each entry becomes an output port, so this field is what shapes the node.
        validate: (value) => {
          if (!Array.isArray(value) || value.length === 0) return 'Add at least one branch';
          return null;
        },
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
      // Port id uses the stable `id` field, not the slugified name.
      const outputs = branches.map((entry): IPortDescriptor => {
        const isFallback = fallback.trim() !== '' && slug(fallback) === slug(entry.name);
        return {
          id: `branch:${entry.id}`,
          direction: 'out',
          type: PORT.text,
          label: entry.name,
          description: isFallback
            ? 'Fallback — taken when no other branch matches.'
            : `Taken when the input classifies as "${entry.name}".`,
        };
      });

      return [...inputs, ...outputs];
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
