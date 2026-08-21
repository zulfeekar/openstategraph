/**
 * Discovered function nodes — `export-and-eject/01`.
 *
 * A workflow package's `functions/` folder is discovered by the backend
 * (`capability_discovery.discover_functions`) by importing it and taking every
 * top-level, non-underscore callable; `GET /api/workflows/{slug}/capabilities`
 * has reported them under `functions` since ticket 18. The runtime has bound
 * them for just as long — `NodeRuntime._discovered_function` runs
 * `fn(text) -> str` over the node's upstream text. Only the editor was
 * missing, so the answer to *"can I write plain Python business logic that
 * sits between two nodes?"* was **yes at runtime, no on the canvas**: the only
 * way to get one running was to hand-edit `workflow.json`.
 *
 * This is the tools-side machinery pointed at functions, deliberately and
 * exactly: `createDiscoveredFunctionNode` is to `discover_functions` what
 * `createDiscoveredToolNode` is to `discover_tools`, and both are minted and
 * withdrawn by the one `registerDiscoveredCapabilities` call, so "what this
 * package ships" stays a single answer rather than two that can disagree.
 *
 * **The node type is not the capability id, and that is the load-bearing
 * difference from tools.** A discovered tool's id *is* its node type
 * (`<slug>/tools.QueryTool`). A function's is not: the compiler dispatches on
 * a `function.` prefix (`NodeRuntime.builder_for`) and
 * `discover_function_callables` keys its registry `function.<name>`, so a
 * document typed `<slug>/functions.shout` would compile to `_passthrough` and
 * report an unresolved binding. The slug-qualified id stays what the backend
 * *reports*; `function.<name>` is what a document *names*. Consequences worth
 * knowing rather than rediscovering:
 *
 * - The type id is not slug-qualified, so two packages' identically named
 *   functions share one type id. Harmless here, because these types are
 *   workflow-scoped: only the open package's are ever registered, and opening
 *   another replaces them. It is a real constraint on the runtime, not one
 *   this file could fix.
 * - `function.format_report` is a *built-in* of the same shape. It is
 *   hand-authored (`orchestrate/FormatReportNode.ts`), registered globally,
 *   and `registerDiscoveredCapabilities` declines to overwrite it — the same
 *   hand-authored-wins rule discovery already applies to tools, and the same
 *   rule the compiler applies at the other end, where the explicit builder
 *   table is consulted before the `function.` convention.
 *
 * **No field schema, v1, stated rather than implied.** The compiled step reads
 * nothing from `data`; every input is the upstream text. A control on the card
 * would be one the runtime cannot see, which is exactly the "picker the
 * compiler ignores" the backend contract test already refuses elsewhere. The
 * signature and docstring become the card's subtitle instead — visible, and
 * incapable of lying about what gets passed.
 *
 * **The browser preview cannot run one.** The implementation is Python on the
 * backend. The executor says so rather than inventing a result, the same
 * honesty `DiscoveredToolNode` practises.
 */

import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import type { FunctionCapability } from '@core/runtime/WorkflowFileClient';
import { CATEGORY, PORT } from '../vocabulary';

/** A discovered function's node type carries no configuration of its own. */
export class DiscoveredFunctionNodeModel extends AbstractNodeModel {}

/** One discovered function's node type plus the executor that fronts it. */
export interface DiscoveredFunctionNode {
  readonly definition: INodeDefinition;
  readonly executor: INodeExecutor;
}

/**
 * The node type id a document names for this function — `function.<name>`.
 *
 * Separate from `createDiscoveredFunctionNode` because the registration seam
 * needs the id before it needs the card: it asks whether a hand-authored node
 * type already covers this function before minting a generic one.
 */
export function discoveredFunctionNodeType(capability: FunctionCapability): string {
  return `function.${capability.name}`;
}

/** Builds a node type from one discovered function capability. */
export function createDiscoveredFunctionNode(
  capability: FunctionCapability,
): DiscoveredFunctionNode {
  const id = discoveredFunctionNodeType(capability);
  const summary = capability.docstring.split('\n')[0]?.trim() ?? '';

  const definition = defineNode(
    {
      id,
      // The same section `function.format_report` sits in: a function is a
      // deterministic graph step, and the palette already teaches that those
      // live beside the agents they feed rather than among the tools an agent
      // calls. (Its `scope: 'workflow'` lifts it into "This workflow" anyway;
      // the category is what it would fall back to.)
      category: CATEGORY.agent,
      scope: 'workflow',
      label: capability.name,
      // The signature is always shown, docstring or not. It is the contract —
      // `(text: str) -> str` — and a card that showed only a sentence a
      // developer wrote could describe a function that takes something else.
      description: summary === '' ? capability.signature : `${summary} — ${capability.signature}`,
      iconId: 'node-format-report',
      accent: 'green',
      keywords: ['function', 'python', 'transform', capability.name],
      defaultSize: { width: 260, height: 140 },
      fields: [],
      ports: [
        {
          id: 'text',
          direction: 'in',
          type: PORT.result,
          label: 'text',
          required: true,
          // One link, the port default, and stated because the contract is the
          // reason: `_upstream_text` reads one upstream node's output, so a
          // second edge would silently be a coin toss rather than a fan-in.
          maxConnections: 1,
          description: 'The text this function transforms.',
        },
        {
          id: 'result',
          direction: 'out',
          type: PORT.result,
          label: 'result',
          maxConnections: null,
          description: 'What the function returned.',
        },
      ],
    },
    DiscoveredFunctionNodeModel,
  );

  const executor: INodeExecutor = {
    id,
    execute(_ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
      return Promise.resolve(
        Err(
          `"${capability.name}" is Python in this package's functions/ folder — it only runs on ` +
            'the backend. Use Chat or the backend run, not the canvas preview.',
        ),
      );
    },
  };

  return { definition, executor };
}
