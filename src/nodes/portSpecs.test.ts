import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
import { TABULAR_NODES } from './tools/TabularDataNode';
import { WORKSHOP_NODES } from './tools/CodeWorkshopNode';
import {
  PORT_SPEC_ARTIFACT_PATH,
  PORT_SPEC_GENERATE_COMMAND,
  PORT_SPEC_SCHEMA_VERSION,
  allNodeDefinitions,
  buildPortSpecArtifact,
  serializePortSpecArtifact,
} from './portSpecs';

const repoRoot = resolve(import.meta.dirname, '../..');

/**
 * The port table Python used to hand-maintain, transcribed once so a test can
 * prove nothing was lost in the move to generation.
 *
 * Frozen on purpose: this is the *old* contract, not a second declaration of
 * the current one. The assertion is one-directional — the generated catalogue
 * must be a superset — so a port added in TypeScript never has to be added
 * here, and this list only ever shrinks if a node type is genuinely retired.
 */
const HAND_WRITTEN_TABLE: Record<string, Record<string, [string, 'in' | 'out']>> = {
  'input.text': { text: ['text', 'out'] },
  'input.markdown': { skill: ['skill', 'out'] },
  'agent.llm': {
    prompt: ['text', 'in'],
    skill: ['skill', 'in'],
    tools: ['tool', 'in'],
    feedback: ['feedback', 'in'],
    result: ['result', 'out'],
  },
  'output.formatted': { result: ['result', 'in'] },
  'route.grader': {
    candidate: ['result', 'in'],
    pass: ['result', 'out'],
    revise: ['feedback', 'out'],
  },
  'route.classifier': { question: ['text', 'in'] },
  'orchestrate.supervisor': {
    instruction: ['text', 'in'],
    feedback: ['feedback', 'in'],
    workers: ['worker', 'out'],
  },
  'orchestrate.worker': {
    dispatch: ['worker', 'in'],
    skill: ['skill', 'in'],
    tools: ['tool', 'in'],
    result: ['result', 'out'],
  },
  'function.format_report': {
    candidate: ['result', 'in'],
    report: ['result', 'out'],
  },
  'human.approval': {
    candidate: ['result', 'in'],
    approved: ['result', 'out'],
    rejected: ['feedback', 'out'],
  },
};

describe('generated node/port catalogue', () => {
  const artifact = buildPortSpecArtifact();
  const byType = new Map(artifact.node_types.map((node) => [node.type, node]));

  it('matches the committed artifact byte for byte', () => {
    const committed = readFileSync(resolve(repoRoot, PORT_SPEC_ARTIFACT_PATH), 'utf8');
    const message =
      `${PORT_SPEC_ARTIFACT_PATH} is stale. The TypeScript node catalogue is ` +
      `authoritative, so regenerate it: ${PORT_SPEC_GENERATE_COMMAND}`;
    expect(serializePortSpecArtifact(artifact), message).toBe(committed);
  });

  it('declares the schema version Python asserts on', () => {
    expect(artifact.schema_version).toBe(PORT_SPEC_SCHEMA_VERSION);
  });

  it('covers every registered node type, app-scoped and workflow-scoped', () => {
    const generated = new Set(artifact.node_types.map((node) => node.type));
    for (const definition of allNodeDefinitions()) {
      expect(generated.has(definition.id), `missing ${definition.id}`).toBe(true);
    }
    // The workflow-scoped families are reached through an explicit list rather
    // than the registry, so name each one: a fourth family added without
    // touching `allNodeDefinitions` must fail here, not vanish quietly.
    for (const family of [CHINOOK_NODES, TABULAR_NODES, WORKSHOP_NODES]) {
      for (const entry of family) {
        expect(generated.has(entry.definition.id), `missing ${entry.definition.id}`).toBe(true);
      }
    }
  });

  it('is a superset of the port table Python used to hand-maintain', () => {
    for (const [nodeType, ports] of Object.entries(HAND_WRITTEN_TABLE)) {
      const node = byType.get(nodeType);
      expect(node, `node type ${nodeType} disappeared from the catalogue`).toBeDefined();
      for (const [portId, [type, direction]] of Object.entries(ports)) {
        const port = node!.ports.find((candidate) => candidate.id === portId);
        expect(port, `${nodeType}.${portId} disappeared`).toBeDefined();
        expect([port!.type, port!.direction], `${nodeType}.${portId}`).toEqual([type, direction]);
      }
    }
  });

  it('resolves every connection cap to a finite number or an explicit null', () => {
    for (const node of artifact.node_types) {
      for (const port of node.ports) {
        const cap = port.max_connections;
        expect(cap === null || Number.isInteger(cap), `${node.type}.${port.id}`).toBe(true);
      }
    }
  });

  it('discovers a router branch family by probing rather than by declaration', () => {
    const router = byType.get('route.classifier');
    // The default five branches must NOT appear as static ports — they are one
    // document's configuration, not the node type's contract.
    expect(router?.ports.map((port) => port.id)).toEqual(['question']);
    expect(router?.dynamic_ports).toEqual([
      {
        prefix: 'branch:',
        direction: 'out',
        type: 'text',
        max_connections: null,
        accepts: ['text'],
      },
    ]);
  });

  it('carries the port-type semantics a consumer needs to check a connection', () => {
    const result = artifact.port_types.find((type) => type.id === 'result');
    expect(result?.accepts).toEqual(['result', 'text']);
    const agentPrompt = byType.get('agent.llm')?.ports.find((port) => port.id === 'prompt');
    // Port-level widening is resolved into the artifact, so Python never has to
    // re-implement `ModelRegistry.canConnectTypes`.
    expect(agentPrompt?.accepts).toEqual(['result', 'text']);
  });

  it('gives the mountable composition nodes the ports MCP was reporting as empty', () => {
    for (const nodeType of ['workflow.subgraph', 'team.workflow']) {
      expect(byType.get(nodeType)?.ports.map((port) => port.id)).toEqual(['input', 'result']);
    }
  });
});
