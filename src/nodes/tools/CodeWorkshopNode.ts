/**
 * Code Workshop tool nodes — the sandboxed coding loop (ticket 43).
 *
 * Seven tools: reset the jailed workspace, list/read/write files inside it,
 * run the fixed pytest command, diff against the baseline, and package the
 * change as a dry-run PR. The Python implementations
 * (`workflows/code-workshop/tools/workshop.py`) own the safety rails — the
 * jail, git isolation, the fixed test runner, the dry-run default; these
 * definitions only give the canvas cards and schemas.
 *
 * Local preview cannot execute any of them (they exist only behind the
 * backend), so every `invokeTool` here follows `DiscoveredToolNode`'s
 * honesty rule: say so plainly rather than fabricate a result.
 */

import { Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import { AbstractToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';

const backendOnly = (name: string) => (): Promise<Result<string, string>> =>
  Promise.resolve(
    Err(`"${name}" only runs on the backend — use Chat, not the canvas Run button.`),
  );

function workshopTool(spec: ToolSpec): IToolExecutor {
  return {
    describeTool: () => spec,
    invokeTool: backendOnly(spec.name),
  };
}

class WorkshopToolNodeModel extends AbstractToolNodeModel {}

/* ================================================================== *
 * Reset Workspace
 * ================================================================== */

export const resetWorkspaceNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-reset',
    label: 'Reset Workspace',
    description:
      'Creates a fresh sandboxed copy of the fixture project with an isolated git baseline. The coder calls this first.',
    iconId: 'node-discovered-tool',
    accent: 'blue',
    keywords: ['workshop', 'sandbox', 'reset', 'workspace', 'git'],
    defaultSize: { width: 252, height: 160 },
    fields: [],
  },
  WorkshopToolNodeModel,
);

export const resetWorkspaceExecutor: INodeExecutor = createToolExecutor(
  resetWorkspaceNode.id,
  workshopTool({
    name: 'workshop_reset_workspace',
    description:
      'Create a fresh, sandboxed copy of the project with its own isolated git repository and committed baseline. Call this first; calling it again discards every change.',
    parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
  }),
);

/* ================================================================== *
 * List Files
 * ================================================================== */

export const listWorkspaceFilesNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-list-files',
    label: 'List Workspace Files',
    description: 'Lists files inside the sandboxed workspace.',
    iconId: 'node-discovered-tool',
    accent: 'blue',
    keywords: ['workshop', 'files', 'list', 'sandbox'],
    defaultSize: { width: 252, height: 160 },
    fields: [],
  },
  WorkshopToolNodeModel,
);

export const listWorkspaceFilesExecutor: INodeExecutor = createToolExecutor(
  listWorkspaceFilesNode.id,
  workshopTool({
    name: 'workshop_list_files',
    description: 'List the files in the sandboxed workspace (optionally one subdirectory).',
    parameters: {
      type: 'object',
      properties: {
        directory: {
          type: 'string',
          description: 'Directory to list, relative to the workspace root (default: root).',
          default: '.',
        },
      },
      required: [],
      additionalProperties: false,
    },
  }),
);

/* ================================================================== *
 * Read File
 * ================================================================== */

export const readWorkspaceFileNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-read-file',
    label: 'Read Workspace File',
    description: 'Reads one file from the sandboxed workspace (path-jailed).',
    iconId: 'node-discovered-tool',
    accent: 'blue',
    keywords: ['workshop', 'read', 'file', 'sandbox'],
    defaultSize: { width: 252, height: 160 },
    fields: [],
  },
  WorkshopToolNodeModel,
);

export const readWorkspaceFileExecutor: INodeExecutor = createToolExecutor(
  readWorkspaceFileNode.id,
  workshopTool({
    name: 'workshop_read_file',
    description: 'Read a file from the sandboxed workspace.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File to read, relative to the workspace root.' },
      },
      required: ['path'],
      additionalProperties: false,
    },
  }),
);

/* ================================================================== *
 * Write File
 * ================================================================== */

export const writeWorkspaceFileNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-write-file',
    label: 'Write Workspace File',
    description:
      'Writes (creates or fully replaces) one file in the sandboxed workspace. Escapes of the jail are refused.',
    iconId: 'node-discovered-tool',
    accent: 'orange',
    keywords: ['workshop', 'write', 'edit', 'file', 'sandbox'],
    defaultSize: { width: 252, height: 160 },
    fields: [],
  },
  WorkshopToolNodeModel,
);

export const writeWorkspaceFileExecutor: INodeExecutor = createToolExecutor(
  writeWorkspaceFileNode.id,
  workshopTool({
    name: 'workshop_write_file',
    description:
      'Write (create or fully replace) a file in the sandboxed workspace. Always write the complete file contents.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File to write, relative to the workspace root.' },
        content: { type: 'string', description: 'The complete new contents of the file.' },
      },
      required: ['path', 'content'],
      additionalProperties: false,
    },
  }),
);

/* ================================================================== *
 * Run Tests
 * ================================================================== */

export const runWorkspaceTestsNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-run-tests',
    label: 'Run Tests',
    description:
      'Runs the workspace test suite with a fixed pytest command — the only process the coder can start. Uses the shared "Timeout" field for the pytest budget.',
    iconId: 'node-discovered-tool',
    accent: 'green',
    keywords: ['workshop', 'pytest', 'tests', 'run', 'sandbox'],
    defaultSize: { width: 252, height: 180 },
    // No fields of its own: the registry's shared `timeoutSeconds` field is
    // exactly the pytest budget the backend's `configure()` reads.
    fields: [],
  },
  WorkshopToolNodeModel,
);

export const runWorkspaceTestsExecutor: INodeExecutor = createToolExecutor(
  runWorkspaceTestsNode.id,
  workshopTool({
    name: 'workshop_run_tests',
    description:
      'Run the workspace test suite with pytest and return the report. The command is fixed; there is no way to run anything else.',
    parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
  }),
);

/* ================================================================== *
 * Diff
 * ================================================================== */

export const workspaceDiffNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-diff',
    label: 'Workspace Diff',
    description: 'Shows the unified diff of every workspace change since the baseline commit.',
    iconId: 'node-discovered-tool',
    accent: 'violet',
    keywords: ['workshop', 'diff', 'git', 'changes', 'sandbox'],
    defaultSize: { width: 252, height: 160 },
    fields: [],
  },
  WorkshopToolNodeModel,
);

export const workspaceDiffExecutor: INodeExecutor = createToolExecutor(
  workspaceDiffNode.id,
  workshopTool({
    name: 'workshop_diff',
    description:
      'Show the unified diff of every change made in the workspace since the baseline commit, including new files.',
    parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
  }),
);

/* ================================================================== *
 * Create PR (dry-run by default)
 * ================================================================== */

const FIELD_USE_GH = 'useGh';

export class CreatePrNodeModel extends AbstractToolNodeModel {
  /** Explicit opt-in to actually invoking `gh pr create`. Default: dry run. */
  get useGh(): boolean {
    return this.getFlag(FIELD_USE_GH, false);
  }
}

export const createPrNode: INodeDefinition = defineToolNode(
  {
    id: 'tool.workshop-create-pr',
    label: 'Create PR',
    description:
      'Packages the workspace change as a .patch + PR body in the output directory. Dry-run unless "Invoke gh" is explicitly enabled — and the graph gates this behind human approval regardless.',
    iconId: 'node-discovered-tool',
    accent: 'red',
    keywords: ['workshop', 'pr', 'pull request', 'patch', 'gh', 'dry-run'],
    defaultSize: { width: 252, height: 180 },
    fields: [
      {
        kind: 'toggle',
        key: FIELD_USE_GH,
        label: 'Invoke gh (opt-in)',
        defaultValue: false,
      },
    ],
  },
  CreatePrNodeModel,
);

export const createPrExecutor: INodeExecutor = createToolExecutor(
  createPrNode.id,
  workshopTool({
    name: 'workshop_create_pr',
    description:
      'Package the workspace changes as a pull request: writes a .patch file and a PR body to the workflow output directory. Dry-run by default; a real gh PR requires the node’s explicit opt-in.',
    parameters: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'Pull request title, one line.' },
        body: {
          type: 'string',
          description: 'Pull request body in Markdown: what changed, why, and how it was tested.',
        },
      },
      required: ['title', 'body'],
      additionalProperties: false,
    },
  }),
);

/* ================================================================== *
 * Export all workshop nodes
 * ================================================================== */

export const WORKSHOP_NODES = [
  { definition: resetWorkspaceNode, executor: resetWorkspaceExecutor },
  { definition: listWorkspaceFilesNode, executor: listWorkspaceFilesExecutor },
  { definition: readWorkspaceFileNode, executor: readWorkspaceFileExecutor },
  { definition: writeWorkspaceFileNode, executor: writeWorkspaceFileExecutor },
  { definition: runWorkspaceTestsNode, executor: runWorkspaceTestsExecutor },
  { definition: workspaceDiffNode, executor: workspaceDiffExecutor },
  { definition: createPrNode, executor: createPrExecutor },
];
