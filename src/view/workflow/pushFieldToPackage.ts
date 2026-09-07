import type { Result } from '@core/kernel/Result';
import {
  saveFailureMessage,
  type SaveFailure,
  type SaveReceipt,
} from '@core/runtime/WorkflowFileClient';
import type { MountUsage } from '@core/runtime/WorkflowFileClient';

/**
 * "Push to package" — the Figma "push override to main component" move,
 * `production-ready` ticket 17.
 *
 * An override corrects one instance. This corrects the **package** every
 * mount of it shares — a materially different act, which is why it is never
 * called "save": that word is already spent on the instance-scoped write
 * `view/workflow/saveWorkflow.ts` performs when a mount is open, and reusing
 * it here would be the Team-outcome-field defect again — a surface implying
 * one scope while acting on another.
 *
 * Two things must be true before a byte moves, both required by the ticket's
 * own "Watch for" and pinned by the tests beside this file:
 *
 * 1. **Confirmed, naming how many instances change.** `mountUsage` answers
 *    that count from the whole workspace, not just the mount on screen, so
 *    the confirmation is not a guess.
 * 2. **Shadowing is said out loud.** A mount that already overrides this
 *    exact field will keep running its own value — the push reaches the
 *    package, not that instance — and a caller who is not told will read the
 *    unmoved sibling as evidence the push silently failed.
 *
 * ## Resolves to the end of the chain, by construction
 *
 * `slug` here is never the mount's *root* (`concierge`) — it is the class the
 * currently-displayed instance is of, which is exactly what `getOpenSlug()`
 * holds while an instance is open (`app/openAddress.ts`'s own docstring: "the
 * class slug of whatever is on screen"). A mount several levels deep
 * (`concierge/wf-music/wf-inner`) already resolved that chain to load the
 * document on screen, so this function receives the answer rather than
 * re-deriving it — there is no parent-vs-package ambiguity left to get wrong
 * here.
 *
 * ## What this does not do
 *
 * It does not touch the instance's own override — a caller that wants the
 * override cleared after a successful push (so the badge does not keep
 * claiming a divergence that no longer exists) calls
 * `controller.nodes.clearOverride` itself, through the same command every
 * other override edit goes through. Composing the two is the view layer's
 * job; this module owns only the network write and the two facts a
 * confirmation must carry.
 */

/** Everything a push needs from the runtime, and nothing else. */
export interface IPushToPackageClient {
  load(slug: string): Promise<Result<unknown, string>>;
  /**
   * Unguarded on purpose (`osg-agent-experience/45`): this writer *loads the
   * package immediately above*, edits that document and writes it straight
   * back, so the version it holds is the one it just read. There is no stale
   * in-memory copy here for a file to have moved out from under.
   */
  save(slug: string, name: string, document: unknown): Promise<Result<SaveReceipt, SaveFailure>>;
  mountUsage(slug: string, childNodeId: string, key: string): Promise<Result<MountUsage, string>>;
}

export interface PushFieldToPackageInput {
  /** The package at the end of the mount chain — never the mount's root. */
  readonly slug: string;
  readonly childNodeId: string;
  readonly key: string;
  /** This instance's current value for the field — what becomes the default. */
  readonly value: unknown;
  /**
   * The host document of the mount this push was started from
   * (`getOpenAddress()?.root`), so it can be dropped from the shadowing
   * warning.
   *
   * The mount that is the *source* of the value being pushed necessarily
   * carries its own override right up until this push runs — that override
   * is the value in `value` — so `mountUsage` always reports it as shadowed.
   * Left in, the warning would claim its own source mount "will not see the
   * correction," which is backwards: the caller clears that mount's override
   * as the other half of this act (see the module docstring), so it always
   * ends up on the new value. Omit to warn about every shadowed host,
   * including the source — only correct for a caller that will not clear it.
   */
  readonly excludeHost?: string;
  /** How this surface asks a yes/no question — see `saveWorkflow.ts`'s `confirm`. */
  readonly confirm: (message: string) => boolean;
}

export type PushFieldOutcome =
  | {
      readonly kind: 'pushed';
      readonly slug: string;
      readonly count: number;
      readonly shadowedHosts: readonly string[];
    }
  | { readonly kind: 'cancelled' }
  | { readonly kind: 'refused'; readonly message: string };

/**
 * How many instances would change, and which will not — the sentence a
 * confirmation shows *before* a person commits, per the ticket's "Confirm
 * before writing, and name how many instances change."
 *
 * Exported on its own so the confirmation copy is one function a test can
 * pin without driving the network write that follows it.
 */
export function confirmationMessage(slug: string, usage: MountUsage): string {
  const instances = usage.count === 1 ? '1 mount' : `${usage.count} mounts`;
  const lines = [
    `Push this value to the "${slug}" package? This changes the package itself — every mount of it that does not already override this field will run the new value.`,
    `Affects ${instances} across your workflows.`,
  ];
  if (usage.shadowedHosts.length > 0) {
    const hosts = usage.shadowedHosts.join(', ');
    const noun = usage.shadowedHosts.length === 1 ? 'already overrides' : 'already override';
    lines.push(
      `${usage.shadowedHosts.length === 1 ? 'One mount' : `${usage.shadowedHosts.length} mounts`} ` +
        `(${hosts}) ${noun} this field and will keep its own value — this will not reach ${
          usage.shadowedHosts.length === 1 ? 'it' : 'them'
        }.`,
    );
  }
  return lines.join('\n\n');
}

export async function pushFieldToPackage(
  client: IPushToPackageClient,
  input: PushFieldToPackageInput,
): Promise<PushFieldOutcome> {
  const { slug, childNodeId, key, value, excludeHost, confirm } = input;

  const usageResult = await client.mountUsage(slug, childNodeId, key);
  if (!usageResult.ok) {
    return {
      kind: 'refused',
      message: `Could not check who mounts "${slug}": ${usageResult.error}`,
    };
  }
  // See `excludeHost`'s own doc: the source mount always shows up here, and
  // it is about to stop being shadowed by the other half of this act.
  const usage: MountUsage = {
    ...usageResult.value,
    shadowedHosts: usageResult.value.shadowedHosts.filter((host) => host !== excludeHost),
  };

  if (!confirm(confirmationMessage(slug, usage))) {
    return { kind: 'cancelled' };
  }

  // Fetched fresh rather than reusing whatever the caller already has in
  // memory — the document on screen is the *effective* (merged) document,
  // never the package's own bytes, and writing that back would burn every
  // other mount's overrides into the shared definition.
  const loaded = await client.load(slug);
  if (!loaded.ok) {
    return { kind: 'refused', message: `Could not load "${slug}": ${loaded.error}` };
  }
  const document = loaded.value as { name?: unknown; nodes?: unknown };
  const nodes = Array.isArray(document.nodes) ? document.nodes : [];
  const target = nodes.find(
    (node): node is { id: unknown; data?: Record<string, unknown> } =>
      typeof node === 'object' && node !== null && (node as { id?: unknown }).id === childNodeId,
  );
  if (!target) {
    return {
      kind: 'refused',
      message: `"${slug}" no longer has a node "${childNodeId}" — nothing to push to.`,
    };
  }
  target.data ??= {};
  target.data[key] = value;

  const name = typeof document.name === 'string' && document.name ? document.name : slug;
  const written = await client.save(slug, name, document);
  if (!written.ok) {
    return {
      kind: 'refused',
      message: `Could not save "${slug}": ${saveFailureMessage(written.error)}`,
    };
  }

  return { kind: 'pushed', slug, count: usage.count, shadowedHosts: usage.shadowedHosts };
}

/**
 * What a surface says after the write — including the pointer to the
 * package's own tests, per the ticket's fourth requirement: a package-level
 * change is exactly when `<package>/tests/` should run, and silently
 * skipping that turns a write-through into a change with no check attached.
 */
export function pushFieldMessage(outcome: PushFieldOutcome): string | null {
  switch (outcome.kind) {
    case 'pushed': {
      const instances = outcome.count === 1 ? '1 mount' : `${outcome.count} mounts`;
      const shadow =
        outcome.shadowedHosts.length > 0
          ? ` ${outcome.shadowedHosts.length === 1 ? 'One of them' : `${outcome.shadowedHosts.length} of them`} kept its own override and did not change.`
          : '';
      return (
        `Pushed to the "${outcome.slug}" package (${instances} affected).${shadow} ` +
        `Run "${outcome.slug}"'s own tests (workflows/${outcome.slug}/tests) to check the change.`
      );
    }
    case 'refused':
      return outcome.message;
    case 'cancelled':
      return null;
  }
}
