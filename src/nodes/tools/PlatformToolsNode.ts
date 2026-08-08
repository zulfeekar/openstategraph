import { Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { AbstractToolNodeModel, defineToolNode } from './AbstractToolNode';

/**
 * The platform + web tool families — generic-tier vocabulary (ticket 67).
 *
 * These implement nothing in the browser: their Python halves
 * (`backend/dyflow/prebuilt_platform.py`, `prebuilt_web.py`) are read-only by
 * construction and run behind the runtime. The TS definitions exist so the
 * documents that bind them — the concierge above all — survive the editor:
 * `WorkflowSerializer.fromJSON` silently drops nodes whose type isn't
 * registered, and a re-save would then destroy them permanently (the exact
 * load-order hazard `workflowScoped.ts` documents). Generic tier, global
 * registration: every workflow may bind a read-only platform or web tool.
 */
class PlatformToolNodeModel extends AbstractToolNodeModel {}

function backendOnlyExecutor(id: string, label: string): INodeExecutor {
  return {
    id,
    execute(_ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
      return Promise.resolve(
        Err(`${label} runs on the backend — use Chat to exercise it.`),
      );
    },
  };
}

function backendTool(spec: {
  id: string;
  label: string;
  description: string;
  keywords: readonly string[];
}): { definition: INodeDefinition; executor: INodeExecutor } {
  return {
    definition: defineToolNode(
      {
        id: spec.id,
        label: spec.label,
        description: spec.description,
        iconId: 'node-tool',
        accent: 'neutral',
        keywords: [...spec.keywords, 'read-only', 'prebuilt'],
        defaultSize: { width: 252, height: 120 },
        fields: [],
      },
      PlatformToolNodeModel,
    ),
    executor: backendOnlyExecutor(spec.id, spec.label),
  };
}

export const PLATFORM_TOOL_NODES = [
  backendTool({
    id: 'tool.platform-list-workflows',
    label: 'List Workflows',
    description: 'Lists every workflow on this platform (read-only).',
    keywords: ['platform', 'introspection', 'catalogue'],
  }),
  backendTool({
    id: 'tool.platform-describe-workflow',
    label: 'Describe Workflow',
    description: 'One workflow’s docs and structure (read-only).',
    keywords: ['platform', 'introspection', 'docs'],
  }),
  backendTool({
    id: 'tool.platform-ls',
    label: 'Repo ls',
    description: 'Lists a repository directory (read-only, jailed).',
    keywords: ['platform', 'ls', 'files'],
  }),
  backendTool({
    id: 'tool.platform-read-file',
    label: 'Repo Read File',
    description: 'Reads one repository text file (read-only, jailed, capped).',
    keywords: ['platform', 'cat', 'read'],
  }),
  backendTool({
    id: 'tool.platform-grep',
    label: 'Repo Grep',
    description: 'Searches repository text (read-only, jailed, capped).',
    keywords: ['platform', 'grep', 'search'],
  }),
  backendTool({
    id: 'tool.web-search',
    label: 'Web Search',
    description: 'Keyless web search (DuckDuckGo); pair with Web Fetch.',
    keywords: ['web', 'search', 'online', 'internet'],
  }),
  backendTool({
    id: 'tool.web-fetch',
    label: 'Web Fetch',
    description: 'Reads one public web page as text (SSRF-guarded).',
    keywords: ['web', 'fetch', 'url', 'online'],
  }),
];
