import { describe, expect, it } from 'vitest';
import { parseMountAddress } from './MountAddress';
import { MountContext } from './MountContext';

/**
 * Adversarial stress tests for the instance-edit seam (QA pass, 2026-08-13).
 *
 * Tests that FAIL are findings, deliberately left failing — production source
 * was not modified to make them pass. Failing tests carry a FINDING comment
 * and use `it.fails` so the suite stays green while the defect stays recorded:
 * fixing the defect makes `it.fails` fail, forcing the marker's removal.
 */

function rootDocument(overrides?: unknown): Record<string, unknown> {
  const data: Record<string, unknown> = { workflow: 'chinook-assistant' };
  if (overrides !== undefined) data['overrides'] = overrides;
  return {
    version: 2,
    name: 'concierge',
    nodes: [
      { id: 'wf-music', type: 'workflow.subgraph', data },
      { id: 'wf-other', type: 'workflow.subgraph', data: { workflow: 'chinook-assistant' } },
    ],
    edges: [],
  };
}

const context = (raw: string, document: Record<string, unknown>) =>
  new MountContext(parseMountAddress(raw)!, document);

function blobOf(document: Record<string, unknown>, mountId: string): unknown {
  const nodes = document['nodes'] as { id: string; data: Record<string, unknown> }[];
  const raw = nodes.find((node) => node.id === mountId)?.data['overrides'];
  return typeof raw === 'string' ? JSON.parse(raw) : raw;
}

describe('escaping and round-trips', () => {
  it('round-trips values that need JSON escaping', () => {
    const document = rootDocument();
    const ctx = context('concierge/wf-music', document);
    const value = 'she said "hi\\n" — ünïcode 𝔘    </script>';
    ctx.writeOverride('agent-sql', 'rules', value);
    expect(ctx.readOverride('agent-sql', 'rules')).toBe(value);
    // and through the committed string spelling, as the backend will read it
    const reparsed = blobOf(document, 'wf-music') as Record<string, Record<string, unknown>>;
    expect(reparsed['agent-sql']?.['rules']).toBe(value);
  });

  it('write then clear restores the document byte-for-byte', () => {
    const document = rootDocument();
    const before = JSON.stringify(document);
    const ctx = context('concierge/wf-music', document);
    ctx.writeOverride('agent-sql', 'rules', 'temp');
    ctx.clearOverride('agent-sql', 'rules');
    expect(JSON.stringify(document)).toBe(before);
  });

  it('a deep write then clear also restores byte-for-byte', () => {
    const document = rootDocument();
    const before = JSON.stringify(document);
    const ctx = context('concierge/wf-music/wf-inner/wf-deep', document);
    ctx.writeOverride('leaf', 'rules', 'temp');
    ctx.clearOverride('leaf', 'rules');
    expect(JSON.stringify(document)).toBe(before);
  });
});

describe('hostile blobs already on the mount node', () => {
  it('refuses to write over a malformed overrides string rather than deleting it', () => {
    const document = rootDocument('{not json');
    const ctx = context('concierge/wf-music', document);
    expect(() => ctx.writeOverride('agent-sql', 'rules', 'x')).toThrow(/not valid JSON/);
    // the malformed text is still there — nothing was silently discarded
    const nodes = document['nodes'] as { id: string; data: Record<string, unknown> }[];
    expect(nodes[0]!.data['overrides']).toBe('{not json');
  });

  // FINDING (CONFIRMED): a nested `overrides` value that is a JSON *string*
  // — the exact spelling `commit()` itself writes at the top level, and one
  // `apply_mount_overrides` accepts at every level — is not `isJson`, so
  // `descend(create: true)` replaces it with `{}` and the previously stored
  // grandchild overrides are silently discarded by an unrelated write.
  // FIXED 2026-08-13. Was `it.fails`: `descend` tested `isJson` alone, so a
  // string-spelled nested `overrides` was replaced with `{}` on any deep write.
  it(
    'a deep write preserves nested overrides stored in their string spelling',
    () => {
      const nested = JSON.stringify({ grader1: { threshold: 9 } });
      const document = rootDocument({ 'wf-inner': { overrides: nested } });
      const ctx = context('concierge/wf-music/wf-inner', document);
      ctx.writeOverride('agent-x', 'rules', 'new');
      const blob = blobOf(document, 'wf-music') as Record<string, Record<string, unknown>>;
      const inner = blob['wf-inner']?.['overrides'] as Record<string, unknown>;
      expect(inner['grader1']).toEqual({ threshold: 9 });
      expect(inner['agent-x']).toEqual({ rules: 'new' });
    },
  );

  it('a malformed nested overrides string is refused, not replaced', () => {
    // Rewritten when the defect was fixed. It used to pin the loss — the
    // string-spelled blob clobbered, `grader1` gone silently. It now pins the
    // other half of the rule `blob()` already followed at the top level:
    // unparseable JSON someone hand-edited is refused, because starting from
    // `{}` would delete their work without telling them.
    const document = rootDocument({ 'wf-inner': { overrides: '{not json' } });
    const ctx = context('concierge/wf-music/wf-inner', document);
    expect(() => ctx.writeOverride('agent-x', 'rules', 'new')).toThrow(/not valid JSON/);
    // And the text they wrote is still there to fix.
    const blob = blobOf(document, 'wf-music') as Record<string, Record<string, unknown>>;
    expect(blob['wf-inner']?.['overrides']).toBe('{not json');
  });

  it('a read sees a string-spelled nested override too', () => {
    // The same defect on the read path, which the finding did not name: an
    // inspector asking "is this overridden?" got `undefined` and would have
    // shown a field as inherited while the document overrode it.
    const nested = JSON.stringify({ grader1: { threshold: 9 } });
    const document = rootDocument({ 'wf-inner': { overrides: nested } });
    const ctx = context('concierge/wf-music/wf-inner', document);
    expect(ctx.readOverride('grader1', 'threshold')).toBe(9);
  });

  it('object-spelled nested overrides survive a deep write', () => {
    const document = rootDocument({ 'wf-inner': { overrides: { grader1: { threshold: 9 } } } });
    const ctx = context('concierge/wf-music/wf-inner', document);
    ctx.writeOverride('agent-x', 'rules', 'new');
    const blob = blobOf(document, 'wf-music') as Record<string, Record<string, unknown>>;
    const inner = blob['wf-inner']?.['overrides'] as Record<string, unknown>;
    expect(inner['grader1']).toEqual({ threshold: 9 });
  });

  it('an overrides blob that is an array reads as empty rather than crashing', () => {
    const document = rootDocument(['not', 'a', 'blob']);
    const ctx = context('concierge/wf-music', document);
    expect(ctx.readOverride('agent-sql', 'rules')).toBeUndefined();
  });
});

describe('stale documents under an open instance', () => {
  it('a write to a mount the root no longer has fails loudly, not silently', () => {
    const document = rootDocument();
    const ctx = context('concierge/wf-music', document);
    (document['nodes'] as unknown[]).splice(0, 1); // wf-music deleted underneath
    expect(() => ctx.writeOverride('agent-sql', 'rules', 'x')).toThrow(/no longer has/);
  });

  it('sibling instances stay independent under interleaved writes', () => {
    const document = rootDocument();
    const music = context('concierge/wf-music', document);
    const other = context('concierge/wf-other', document);
    music.writeOverride('agent-sql', 'rules', 'music');
    other.writeOverride('agent-sql', 'rules', 'other');
    music.writeOverride('agent-sql', 'temperature', 0.1);
    expect(music.readOverride('agent-sql', 'rules')).toBe('music');
    expect(other.readOverride('agent-sql', 'rules')).toBe('other');
    expect(other.readOverride('agent-sql', 'temperature')).toBeUndefined();
  });
});

describe('address hostility the parser must keep refusing', () => {
  it.each([
    'concierge//wf-music',
    'concierge/../other',
    'concierge/.',
    '/wf-music',
    'concierge/wf music',
    'CONCIERGE/wf-music',
    'concierge/wf-music/',
    'con cierge',
    '-leading/wf-music',
  ])('refuses %j', (raw) => {
    expect(parseMountAddress(raw)).toBeNull();
  });

  it('accepts a 50-level chain — depth is bounded by the backend cycle check, not here', () => {
    const raw = 'root/' + Array.from({ length: 50 }, (_, i) => `m${i}`).join('/');
    const address = parseMountAddress(raw);
    expect(address?.mountPath).toHaveLength(50);
  });
});
