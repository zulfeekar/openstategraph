import { describe, expect, it, vi } from 'vitest';
import type { SaveFailure, SaveReceipt } from '@core/runtime/WorkflowFileClient';
import { Ok, Err, type Result } from '@core/kernel/Result';
import type { MountUsage } from '@core/runtime/WorkflowFileClient';
import {
  confirmationMessage,
  pushFieldMessage,
  pushFieldToPackage,
  type IPushToPackageClient,
} from './pushFieldToPackage';

/**
 * `production-ready` ticket 17 — "push to package".
 *
 * These tests are at the layer the ticket's own requirements live: the
 * confirmation copy (never "save", names the instance count), the shadowing
 * warning, and that the write lands on the package's own document rather than
 * whatever is on screen. A test that only checked "the client's `save` was
 * called" would stay green if the fix wrote the wrong document or skipped the
 * confirmation — so each requirement gets its own assertion on the actual
 * words or the actual document mutated.
 */

const USAGE = (overrides: Partial<MountUsage> = {}): MountUsage => ({
  count: 3,
  shadowedHosts: [],
  ...overrides,
});

function recordingClient(overrides: Partial<IPushToPackageClient> = {}) {
  const calls: { save?: { slug: string; name: string; document: unknown } } = {};
  const client: IPushToPackageClient = {
    mountUsage: async (): Promise<Result<MountUsage, string>> => Ok(USAGE()),
    load: async (): Promise<Result<unknown, string>> =>
      Ok({
        name: 'Child',
        nodes: [{ id: 'agent-sql', type: 'agent.llm', data: { rules: 'old package rules' } }],
      }),
    save: async (
      slug: string,
      name: string,
      document: unknown,
    ): Promise<Result<SaveReceipt, SaveFailure>> => {
      calls.save = { slug, name, document };
      return Ok({ digest: 'sha-written' });
    },
    ...overrides,
  };
  return { client, calls };
}

describe('confirmationMessage', () => {
  it('never says "save" — it is a materially different act from an override', () => {
    const message = confirmationMessage('chinook-assistant', USAGE({ count: 2 }));
    expect(message.toLowerCase()).not.toContain('save');
  });

  it('names how many instances change', () => {
    const message = confirmationMessage('chinook-assistant', USAGE({ count: 5 }));
    expect(message).toContain('5 mounts');
  });

  it('says nothing about shadowing when nothing is shadowed', () => {
    const message = confirmationMessage('chinook-assistant', USAGE({ shadowedHosts: [] }));
    expect(message.toLowerCase()).not.toContain('shadow');
    expect(message.toLowerCase()).not.toContain('keep its own value');
  });

  it('warns which instances will not see the correction', () => {
    const message = confirmationMessage(
      'chinook-assistant',
      USAGE({ count: 3, shadowedHosts: ['front-desk'] }),
    );
    expect(message).toContain('front-desk');
    expect(message.toLowerCase()).toContain('will not reach');
  });
});

describe('pushFieldToPackage', () => {
  it('asks before writing anything', async () => {
    const { client, calls } = recordingClient();
    const confirm = vi.fn().mockReturnValue(false);
    const outcome = await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'agent-sql',
      key: 'rules',
      value: 'new rules',
      confirm,
    });
    expect(confirm).toHaveBeenCalledOnce();
    expect(outcome.kind).toBe('cancelled');
    expect(calls.save).toBeUndefined();
  });

  it('writes the new value onto the package document at the named node', async () => {
    const { client, calls } = recordingClient();
    const outcome = await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'agent-sql',
      key: 'rules',
      value: 'new rules',
      confirm: () => true,
    });
    expect(outcome.kind).toBe('pushed');
    expect(calls.save?.slug).toBe('child');
    const nodes = (
      calls.save?.document as { nodes: Array<{ id: string; data: Record<string, unknown> }> }
    ).nodes;
    const written = nodes.find((n) => n.id === 'agent-sql');
    expect(written?.data.rules).toBe('new rules');
  });

  it('fetches the package fresh rather than reusing a caller-supplied document', async () => {
    // If this fetched the merged document already on screen instead of the
    // package's own bytes, an unrelated field this instance overrides would
    // be burned into the shared package as a side effect — exactly the
    // defect `docs/decisions/mount-overrides.md` rejects fork-on-configure
    // for avoiding. `load` is the only source of the document; asserting it
    // was called is what pins that.
    const load = vi
      .fn()
      .mockResolvedValue(
        Ok({ name: 'Child', nodes: [{ id: 'agent-sql', type: 'agent.llm', data: {} }] }),
      );
    const { client } = recordingClient({ load });
    await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'agent-sql',
      key: 'rules',
      value: 'x',
      confirm: () => true,
    });
    expect(load).toHaveBeenCalledWith('child');
  });

  it('refuses when the named node no longer exists in the package', async () => {
    const { client, calls } = recordingClient({
      load: async () => Ok({ name: 'Child', nodes: [] }),
    });
    const outcome = await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'gone',
      key: 'rules',
      value: 'x',
      confirm: () => true,
    });
    expect(outcome.kind).toBe('refused');
    expect(calls.save).toBeUndefined();
  });

  it('excludes the source mount from the shadowing warning — it always shows up shadowed, but is cleared by the caller', async () => {
    // The mount this push is being made *from* still carries its own
    // override right up until the moment the push runs, so `mountUsage`
    // reports it as shadowed. Without `excludeHost`, the confirmation would
    // wrongly claim the source mount "will not see the correction" — the
    // exact opposite of what happens once the caller clears its override.
    const { client } = recordingClient({
      mountUsage: async () =>
        Ok(USAGE({ count: 2, shadowedHosts: ['front-desk', 'other-parent'] })),
    });
    const confirm = vi.fn().mockReturnValue(true);
    const outcome = await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'agent-sql',
      key: 'rules',
      value: 'x',
      excludeHost: 'front-desk',
      confirm,
    });
    expect(confirm.mock.calls[0]?.[0]).not.toContain('front-desk');
    expect(confirm.mock.calls[0]?.[0]).toContain('other-parent');
    expect(outcome).toMatchObject({ shadowedHosts: ['other-parent'] });
  });

  it('reports the mount count and shadowed hosts on success', async () => {
    const { client } = recordingClient({
      mountUsage: async () => Ok(USAGE({ count: 4, shadowedHosts: ['front-desk'] })),
    });
    const outcome = await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'agent-sql',
      key: 'rules',
      value: 'x',
      confirm: () => true,
    });
    expect(outcome).toMatchObject({ kind: 'pushed', count: 4, shadowedHosts: ['front-desk'] });
  });

  it('refuses without writing when the usage check itself fails', async () => {
    const { client, calls } = recordingClient({
      mountUsage: async (): Promise<Result<MountUsage, string>> => Err('network down'),
    });
    const outcome = await pushFieldToPackage(client, {
      slug: 'child',
      childNodeId: 'agent-sql',
      key: 'rules',
      value: 'x',
      confirm: () => true,
    });
    expect(outcome.kind).toBe('refused');
    expect(calls.save).toBeUndefined();
  });
});

describe('pushFieldMessage', () => {
  it('points at the package tests after a successful push', () => {
    const message = pushFieldMessage({
      kind: 'pushed',
      slug: 'child',
      count: 2,
      shadowedHosts: [],
    });
    expect(message).toContain('workflows/child/tests');
  });

  it('says which mounts kept their own value when something was shadowed', () => {
    const message = pushFieldMessage({
      kind: 'pushed',
      slug: 'child',
      count: 3,
      shadowedHosts: ['front-desk'],
    });
    expect(message?.toLowerCase()).toContain('kept its own override');
  });

  it('is silent on cancellation', () => {
    expect(pushFieldMessage({ kind: 'cancelled' })).toBeNull();
  });
});
