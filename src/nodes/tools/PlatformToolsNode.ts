import { Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { FieldSchema } from '@core/model/contracts/fields';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { ToolNodeModel, defineToolNode } from './AbstractToolNode';

/**
 * The platform + web tool families — generic-tier vocabulary (ticket 67).
 *
 * These implement nothing in the browser: their Python halves
 * (`backend/openstategraph/prebuilt_platform.py`, `prebuilt_web.py`) are read-only by
 * construction and run behind the runtime. The TS definitions exist so the
 * documents that bind them — the concierge above all — survive the editor:
 * `WorkflowSerializer.fromJSON` silently drops nodes whose type isn't
 * registered, and a re-save would then destroy them permanently (the exact
 * load-order hazard `workflowScoped.ts` documents). Generic tier, global
 * registration: every workflow may bind a read-only platform or web tool.
 */

function backendOnlyExecutor(id: string, label: string): INodeExecutor {
  return {
    id,
    execute(_ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
      return Promise.resolve(Err(`${label} runs on the backend — use Chat to exercise it.`));
    },
  };
}

function backendTool(spec: {
  id: string;
  label: string;
  description: string;
  keywords: readonly string[];
  fields?: readonly FieldSchema[];
  maxInstances?: number;
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
        fields: spec.fields ?? [],
        ...(spec.maxInstances != null ? { maxInstances: spec.maxInstances } : {}),
      },
      ToolNodeModel,
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
  backendTool({
    id: 'tool.youtube-transcript',
    label: 'YouTube Transcript',
    description: 'Reads one YouTube video’s captions as plain text (keyless, no timestamps).',
    keywords: ['youtube', 'video', 'transcript', 'captions', 'subtitles'],
    // Beside Web Fetch because it is the same promise — keyless, read-only —
    // but it cannot *be* Web Fetch: the only route that returns caption text
    // is a JSON POST to InnerTube's player endpoint followed by a GET of the
    // URL that answer issues, and a POST body is not a `url` argument
    // (`backend/openstategraph/prebuilt_youtube.py` records the probes).
    fields: [
      {
        key: 'language',
        label: 'Language',
        kind: 'text',
        defaultValue: 'en',
        placeholder: 'en',
        hint: 'Preferred caption language. Falls back to the same language family, then to whatever exists.',
      },
      {
        key: 'allowAutoCaptions',
        label: 'Auto captions',
        kind: 'toggle',
        defaultValue: true,
        description: 'Accept machine-generated (ASR) captions when no authored ones exist.',
      },
      {
        key: 'maxChars',
        label: 'Max characters',
        kind: 'slider',
        min: 1000,
        max: 20000,
        step: 1000,
        defaultValue: 8000,
        onCard: false,
        format: (value) => `${value}`,
      },
    ],
  }),
  backendTool({
    id: 'tool.knowledge-lookup',
    label: 'Knowledge',
    description:
      'The workflow’s second brain: agents look up per-topic procedural knowledge (table meanings, column semantics, JOIN rules) on demand — never stuffed into the prompt. “Build second brain” on the card writes the docs at build time; a run only ever reads them.',
    keywords: ['knowledge', 'brain', 'wiki', 'procedural', 'second brain', 'lookup', 'memory'],
    // One per workflow, and `maxInstances` already counts the right thing:
    // `model.countOfType` is over the open document, one document is one
    // package, one package has one `knowledge/` directory. A second atom
    // would be a second card claiming the same single store — a lie about
    // cardinality, and two "Build second brain" buttons racing one another
    // over the same files. A mounted child is a *different* document with a
    // different model, so a root and a team may each hold one; that is the
    // designed shape, not a collision (docs/decisions/knowledge-architecture.md).
    maxInstances: 1,
  }),
  backendTool({
    id: 'tool.email-send',
    label: 'Email Send',
    description:
      'Sends a report to the address configured here — the model writes subject and body, never the recipient. Dry-run (.eml to workflows/_outbox) unless SMTP is configured.',
    keywords: ['email', 'send', 'report', 'delivery', 'smtp'],
    fields: [
      {
        key: 'to',
        label: 'Recipient',
        kind: 'text',
        defaultValue: '',
        placeholder: 'reports@example.com',
        hint: 'The fixed destination. Agents cannot re-address the mail.',
      },
    ],
  }),
];
