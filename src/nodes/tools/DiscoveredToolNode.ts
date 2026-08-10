/**
 * Discovered tool nodes — ticket 18's node-type-discovery half.
 *
 * A workflow's `tools/` folder is discovered by the backend
 * (`capability_discovery.py`) by importing it and finding `BaseTool`
 * subclasses; `GET /api/workflows/{slug}/capabilities` is the wire
 * contract. Until this file, nothing on the frontend ever called that
 * endpoint — a discovered tool never appeared anywhere a developer could
 * use it. This turns one `ToolCapability` into a real, connectable node
 * type, generically: no hand-authored TS file per tool, unlike
 * `ChinookDatabaseNode.ts` (which predates this and stays as the nicer,
 * purpose-built alternative for that one workflow).
 *
 * **What this deliberately does not attempt** (see ticket 18's own "left
 * open" list): a hot-reload push (`uvicorn --reload` plus a fresh
 * `WorkflowManager.handleLoad` is today's answer, same as the ticket's own
 * resolution), and true dynamic *node-class* discovery (`Final*` classes
 * outside the tool ladder becoming new node kinds, not just tool
 * capabilities). This is the narrower, already-fully-specified slice: a
 * `BaseTool` subclass becomes a `tool`-bus-connectable card.
 *
 * **Local preview cannot invoke a discovered tool.** Its Python
 * implementation only exists on the backend; there is no way to run it
 * from the browser. `invokeTool` says so plainly rather than fabricating a
 * result — the same honesty `ChinookDatabaseNode`'s local preview already
 * practices for schema lookups it cannot verify against a real database.
 */

import { Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ToolCapability } from '@core/runtime/WorkflowFileClient';
import { AbstractToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

/** One discovered tool's node type plus the executor that fronts it. */
export interface DiscoveredToolNode {
  readonly definition: INodeDefinition;
  readonly executor: ReturnType<typeof createToolExecutor>;
}

class DiscoveredToolNodeModel extends AbstractToolNodeModel {}

/**
 * Builds a node type from one discovered capability.
 *
 * The capability's own qualified id (`<slug>/tools.<ClassName>`, already
 * collision-proof across workflows per ticket 18's resolution) is reused
 * directly as the node type id — a discovered tool's identity already is
 * the stable identity this needs, so minting a second one would just be
 * another thing that could drift out of sync with the first.
 */
export function createDiscoveredToolNode(capability: ToolCapability): DiscoveredToolNode {
  const definition = defineToolNode(
    {
      id: capability.id,
      scope: 'workflow',
      label: capability.name,
      description: capability.description,
      iconId: 'node-discovered-tool',
      accent: 'neutral',
      keywords: ['discovered', 'tool'],
      defaultSize: { width: 260, height: 140 },
    },
    DiscoveredToolNodeModel as never,
  );

  const executor = createToolExecutor(capability.id, {
    describeTool: () => ({
      name: capability.name,
      description: capability.description,
      parameters: capability.argsSchema as never,
    }),
    invokeTool: () =>
      Promise.resolve(
        Err(
          `"${capability.name}" only runs on the backend — use Chat, not the canvas Run button, to call a discovered tool.`,
        ) as Result<string, string>,
      ),
  });

  return { definition, executor };
}
