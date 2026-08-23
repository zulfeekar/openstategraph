import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
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
    // than the registry, so name each one: a second family added without
    // touching `allNodeDefinitions` must fail here, not vanish quietly.
    for (const family of [CHINOOK_NODES]) {
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
    // `skill` is static and declared once for all five prompted types;
    // `feedback` is static too (`workflow-gallery` 48 — a `revise` edge
    // re-dispatches to whichever branch this router last chose); only the
    // branch outputs vary with the document.
    expect(router?.ports.map((port) => port.id)).toEqual(['question', 'skill', 'feedback']);
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

  it('emits every data key a node type can write, defaults included', () => {
    // The editor half of `backend/tests/test_data_key_contract.py`: a factory
    // reading a key absent from this list is reading something no card, no
    // inspector and no document can write, which raises nothing and yields ""
    // forever. Three of those shipped before the contract existed.
    const supervisor = byType.get('orchestrate.supervisor');
    expect(supervisor?.field_keys).toContain('rules');
    expect(supervisor?.field_keys).toContain('rulesMode');
    // Sorted, and derived from `defaultsFrom` — so a `file` field's content
    // key is included, which is a key the backend legitimately reads.
    const markdown = byType.get('input.markdown');
    expect(markdown?.field_keys).toContain('content');
    expect(markdown?.field_keys).toEqual([...(markdown?.field_keys ?? [])].sort());
  });

  it('names the legacy keys a document may carry that no field declares', () => {
    // Two entries, and each is a migration fallback rather than a second
    // control: `criteriaMode` is the Grader's older spelling of `rulesMode`
    // (`docs/decisions/skill-layer.md`), `instructions` the Skill node's
    // first spelling of its body key (ticket 28). This list is the only
    // sanctioned way to exempt a key from the data-key contract, so it being
    // short is the point.
    expect(artifact.legacy_data_keys).toEqual(['criteriaMode', 'instructions']);
    for (const node of artifact.node_types) {
      for (const legacy of artifact.legacy_data_keys) {
        expect(node.field_keys, `${node.type} re-declares a legacy key`).not.toContain(legacy);
      }
    }
  });

  it('gives the mountable composition node the ports MCP was reporting as empty', () => {
    // Was a loop over two ids. `team.workflow` collapsed into this one at
    // schema v3 (ticket 16); the ports are unchanged, which is most of why the
    // two were never really different node types.
    expect(byType.get('workflow.subgraph')?.ports.map((port) => port.id)).toEqual([
      'input',
      'result',
    ]);
    expect(byType.has('team.workflow')).toBe(false);
  });
});

describe('the two sides of the port-spec version', () => {
  /**
   * `PORT_SPEC_SCHEMA_VERSION` here and `SCHEMA_VERSION` in
   * `compile/node_catalogue.py` are documented as "bumped in lockstep" — by
   * **comment only**. No test bound them, so the lockstep was a promise
   * (reviews-2026-08-14 ticket 08).
   *
   * The generated artifact is the thing both sides actually read, so it is
   * what they are pinned through.
   */
  it('matches the version stamped into the generated catalogue', async () => {
    const { readFileSync } = await import('node:fs');
    const { fileURLToPath } = await import('node:url');
    const artifact = JSON.parse(
      readFileSync(
        fileURLToPath(
          new URL('../../backend/openstategraph/compile/port_specs.json', import.meta.url),
        ),
        'utf8',
      ),
    ) as { schema_version?: number };

    expect(artifact.schema_version).toBe(PORT_SPEC_SCHEMA_VERSION);
  });

  it('matches the version the Python reader requires', async () => {
    const { readFileSync } = await import('node:fs');
    const { fileURLToPath } = await import('node:url');
    const python = readFileSync(
      fileURLToPath(
        new URL('../../backend/openstategraph/compile/node_catalogue.py', import.meta.url),
      ),
      'utf8',
    );
    const declared = /^SCHEMA_VERSION\s*=\s*(\d+)/m.exec(python);

    expect(declared?.[1], 'node_catalogue.py must declare SCHEMA_VERSION').toBeDefined();
    expect(Number(declared?.[1])).toBe(PORT_SPEC_SCHEMA_VERSION);
  });
});
