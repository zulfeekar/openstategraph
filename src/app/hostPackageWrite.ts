import type { Result } from '@core/kernel/Result';
import type { MountAddress } from '@core/model/MountAddress';
import {
  saveFailureMessage,
  type SaveFailure,
  type SaveReceipt,
  type WorkflowSummary,
} from '@core/runtime/WorkflowFileClient';
import {
  getKnownDigest,
  getKnownSavedAt,
  recordKnownDigest,
  recordKnownVersion,
} from '@app/workflowFileWatch';
import { supersedeDraftAfterHostWrite } from '@app/workflowDrafts';

/**
 * **The one seam every write of a host package passes through**
 * (`production-ready` 102).
 *
 * A *host package* is the parent of an open mount: a drill-in edits the child
 * on screen, but the overrides live on the parent, so the file that moves is
 * one the editor is not showing. Two writers do that — the drill-in's autosave
 * (`diskAutosave.writeOpenMountHostToDisk`) and the **Save mount** button
 * (`view/workflow/saveWorkflow`'s instance branch) — and until this module
 * they each re-implemented the same three-step protocol by hand:
 *
 * 1. **Compare-and-set** on the parent's `saved_at`. The file watch follows
 *    the *class* while an instance is open, so nothing else notices the parent
 *    moving, and both writers write a whole retained document.
 * 2. **Write.**
 * 3. **Supersede this browser's draft of the parent** — the step
 *    `production-ready` 101 was filed for. A draft is this browser's unsaved
 *    edits to a package; it stops being that the instant this same browser
 *    writes that package's file from somewhere else. Left standing, Back
 *    restores it over the fresh file and autosave writes the document *whole*,
 *    turning an absence in memory into a deletion on disk.
 * 4. **Adopt our own write as the next baseline**, so step 1 does not accuse
 *    this tab of being somebody else from the second write onwards.
 *
 * 101 fixed step 3 at both call sites and said plainly what it had not
 * achieved: *a third future host writer would compile and reintroduce the
 * deletion.* It would — measured, not assumed. A third writer added to `src/`
 * left all 2495 vitest tests green.
 *
 * ## Why the argument is a mount, and not a root plus a document
 *
 * Ticket 71's shape: make the mistake a type error rather than a convention.
 * The two facts a host write must agree on are *which package* and *which
 * bytes*, and they arrive from one object — the `MountContext`. So this takes
 * the address and the mount, derives the slug, the name and the document from
 * them, and there is no parameter through which a caller can hand it a
 * document belonging to some other package.
 *
 * ## What this cannot do, and what covers the gap
 *
 * No signature can stop a fourth writer calling `client.save(root, …)`
 * directly and skipping this module — the client is reachable from anywhere.
 * That last mile is `aThirdHostWriterCannotForget.test.ts`, which reads `src/`
 * and goes red when a host document reaches a `save` call anywhere but here.
 */

/** Everything a host write needs from the runtime, and nothing else. */
export interface IHostPackageClient {
  summary(slug: string): Promise<Result<WorkflowSummary | null, string>>;
  save(
    slug: string,
    name: string,
    document: unknown,
    baseDigest?: string,
  ): Promise<Result<SaveReceipt, SaveFailure>>;
}

/**
 * The mount whose parent is being written. `Pick`ed from `MountContext` rather
 * than imported whole so `view/`'s narrower structural shape satisfies it.
 */
export interface HostWriteSubject {
  readonly address: Pick<MountAddress, 'root'>;
  readonly rootDocument: Record<string, unknown>;
}

/**
 * What happened, named — never a bare boolean. `refused` carries the sentence
 * a surface says, because both callers used to spell that sentence out
 * themselves and two spellings of one refusal is how they drift.
 *
 * `refused` and `failed` are separate for a reason that is not decoration:
 * `refused` carries finished prose this module owns — the conflict sentence —
 * while `failed` carries the *client's* words, which each surface introduces
 * in its own voice ("Could not save: …" on a button the user just pressed,
 * bare in an autosave nobody asked for).
 */
export type HostWriteOutcome =
  | { readonly kind: 'written'; readonly root: string }
  | { readonly kind: 'refused'; readonly reason: string }
  | { readonly kind: 'failed'; readonly error: string };

export async function writeHostPackage(
  client: IHostPackageClient,
  subject: HostWriteSubject,
): Promise<HostWriteOutcome> {
  const root = subject.address.root;

  const current = await client.summary(root);
  const baseline = getKnownSavedAt(root);
  if (current.ok && current.value?.savedAt && baseline && current.value.savedAt !== baseline) {
    return {
      kind: 'refused',
      reason: `"${root}" changed since this mount was opened. Reopen it to pick up the change, then edit again.`,
    };
  }

  const name = (subject.rootDocument['name'] as string) || root;
  // The `savedAt` check above is this module's own; the digest is the
  // backend's, and both are sent (`osg-agent-experience/45`). They fail on
  // different things and neither subsumes the other: `savedAt` moves only when
  // this editor's own store writes the envelope, so a coding agent editing the
  // parent's `workflow.json` by hand passes it untouched — and that is exactly
  // the writer this ticket exists for. A refusal from either is the same
  // `refused`, in one sentence, because a surface has one thing to say.
  const written = await client.save(root, name, subject.rootDocument, getKnownDigest(root));
  if (!written.ok) {
    if (written.error.kind === 'conflict') {
      return { kind: 'refused', reason: written.error.reason };
    }
    return { kind: 'failed', error: saveFailureMessage(written.error) };
  }

  // Only after a write that actually landed. A refused or failed write leaves
  // the file where it was, so the draft is still this browser's unsaved work
  // and deleting it would be the data loss 101 fixed, wearing the other face.
  supersedeDraftAfterHostWrite(root);

  const row = await client.summary(root);
  recordKnownVersion(root, row.ok ? row.value : null);
  // After the row, because the receipt describes the bytes this call wrote
  // while the row is a second read anybody could have overtaken.
  recordKnownDigest(root, written.value.digest);
  return { kind: 'written', root };
}
