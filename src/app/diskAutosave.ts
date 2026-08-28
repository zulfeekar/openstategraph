import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import type { MountContext } from '@core/model/MountContext';
import { isInstance } from '@core/model/MountAddress';
import { getOpenAddress } from './openAddress';
import { clearOpenSlug, getOpenSlug } from './openWorkflow';
import {
  carryDraftToFreshKey,
  currentDraftId,
  discardDraftAfterDelete,
  type DraftRestoreReport,
} from './workflowDrafts';
import { CURRENT_SLUG_KEY, forgetKnownSavedAt } from './workflowFileWatch';
import { writeHostPackage } from './hostPackageWrite';

/**
 * Whether an edit should be written to `workflows/<slug>/` right now.
 *
 * The owner's expectation, stated three times: *"when a workflow is created,
 * edited, modified, as a developer I would expect to see the immediate result
 * on the workflow folder or package inside the codebase."* It did not — the
 * browser autosaved to `localStorage` and only an explicit **Save** ever
 * touched disk, which `docs/decisions/gap-register.md` UX-04 already called a
 * stopgap "until the Python backend owns persistence".
 *
 * Two cases are deliberately excluded, and both are about *not having
 * somewhere honest to write*:
 *
 * - **No slug yet.** A brand-new workflow has no directory: the backend mints
 *   the slug on first save, because a client that guesses one silently
 *   overwrites a package of the same name (`docs/api.md`). So a new canvas
 *   still needs one deliberate Save, and everything after it is automatic.
 * - **A mount instance is open.** What is on screen is a *derived* document —
 *   the package plus this mount's overrides — and saving it back to the
 *   package would burn those overrides into the shared definition and hit
 *   every other mount.
 *
 * The second exclusion is still right and used to be the whole answer, which
 * made it wrong by omission: while an instance was open **nothing** was
 * written, and the override the inspector had already badged `overridden`
 * lived only in a retained JavaScript object that `Back` threw away
 * (organisms-first-class ticket 44). `writeOpenMountHostToDisk` below is the
 * other half — the host, never the package.
 */
export function diskAutosaveTarget(storage: Pick<Storage, 'getItem'>): string | null {
  const slug = (storage.getItem(CURRENT_SLUG_KEY) ?? '').trim();
  if (!slug) return null;

  const address = getOpenAddress();
  if (address && isInstance(address)) return null;

  return slug;
}

export type DiskAutosaveOutcome =
  | { readonly kind: 'saved' }
  | { readonly kind: 'skipped' }
  | { readonly kind: 'unchanged' }
  | { readonly kind: 'failed'; readonly reason: string };

/**
 * The document we believe `workflows/<slug>/workflow.json` currently holds.
 *
 * Autosave fires on `controller.onChange`, and **a load fires that too** — so
 * without this, merely *opening* a workflow rewrote its file. The document was
 * identical and only `savedAt` moved, which is worse than it sounds: browsing
 * three packages left three modified files in `git status`, and a `git diff`
 * that is noise stops being read.
 *
 * Keyed by slug because a tab opens many workflows in turn, and per-slug is
 * what makes "did *this* file change" answerable without a round trip to ask.
 */
const lastWritten = new Map<string, string>();

/**
 * `JSON.stringify` with keys in a fixed order.
 *
 * Plain `stringify` compares *insertion* order, and the serializer does not
 * promise one: a node rebuilt from a different code path emits the same fields
 * in a different sequence. The observed cost of getting this wrong was not a
 * missed optimisation but a **write loop** — every comparison reported a change,
 * every autosave wrote, each write moved `savedAt`, and the editor rewrote an
 * unchanged package every few seconds for as long as it stayed open.
 */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, inner: unknown) => {
    if (inner === null || typeof inner !== 'object' || Array.isArray(inner)) return inner;
    const entries = Object.entries(inner as Record<string, unknown>);
    entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return Object.fromEntries(entries);
  });
}

/**
 * The part of a document a *write* should be triggered by.
 *
 * Everything is written — this only decides what counts as a change worth
 * writing for. One field is excluded, and it is the difference between a
 * working feature and a broken one:
 *
 * **`size` is measured, not authored.** `JointGraphAdapter.applyGeometry`
 * writes card geometry back from a `ResizeObserver` on the rendered React
 * card. Nobody types it — the card reports how tall it ended up. Left in the
 * comparison, an idle editor rewrote
 * `workflows/chinook-assistant/workflow.json` every few seconds forever: the
 * Get Table Schema card alternates between 118px and 200px as its schema list
 * settles, each measurement counted as an edit, and each write moved
 * `savedAt`. That oscillation is a canvas defect in its own right and is
 * recorded as one — but a measurement must not be able to dirty a file even
 * after it is fixed.
 *
 * `position` stays in: dragging a node *is* an edit, and one a developer
 * expects to survive a reload.
 *
 * **Kept even though the model now enforces the same rule.** Since
 * `production-ready` 69 a measured size cannot reach `SerializedNode` at all
 * — `AbstractNodeModel` serialises the *authored* size and keeps the rendered
 * one to itself — so this strip is a second lock on a door already shut. It
 * stays because an idle editor rewriting a package on a loop is the worst
 * failure this file has produced, and one enforcement point is one bug away
 * from producing it again.
 *
 * **But it strips only the sizes that are measured** (`production-ready` 70).
 * A container's frame is the one card nobody measures: its size comes from the
 * resize grip or from `Arrange` refitting it, both gestures a person made and
 * expects to survive a reload. Stripping every node's `size` made a frame
 * resize the one edit no autosave was worth — dragged on screen, `mtime` never
 * moved, and only pressing Save wrote it. `serializer.sizeIsMeasured` answers
 * per type, and answers `true` for a type this build cannot resolve, so an
 * unknown node keeps the old behaviour.
 *
 * The second lock therefore still covers every card that reports its own
 * height, which is the case that produced the loop. What it no longer covers
 * is a frame — bounded, because a frame's height is not content-driven and so
 * has nothing to oscillate between.
 *
 * `name` and the serializer are both needed on every call because the two
 * sides of the comparison are built by different callers: whichever form a
 * document arrives in, it must be reduced by the same rules.
 */
function comparable(
  name: string,
  document: unknown,
  serializer: Pick<WorkflowSerializer, 'sizeIsMeasured'>,
): string {
  const { nodes, ...rest } = document as { nodes?: readonly Record<string, unknown>[] };
  return canonical({
    name,
    ...rest,
    nodes: (nodes ?? []).map((node) => {
      if (!serializer.sizeIsMeasured(String(node['type'] ?? ''))) return node;
      const { size: _size, ...rest } = node;
      return rest;
    }),
  });
}

/**
 * Record what the file on disk holds, so opening it is not an edit.
 *
 * **Canonicalised on the way in, and that is the whole of ticket 27.** The
 * document handed here is the file's *authored* form; what autosave later
 * compares it against is the model's *canonical* form. They describe the same
 * workflow in different bytes — nodes in authoring order versus a stable sort,
 * `parentId` omitted versus always present, `data` carrying what somebody set
 * versus every schema default materialised — so comparing them raw reports a
 * difference on every document the editor did not itself write.
 *
 * Until this call canonicalised, that is exactly what happened: opening
 * `workflows/concierge/workflow.json` wrote it straight back with 256 changed
 * lines and a fresh `savedAt`, and a field-by-field comparison found **zero
 * keys lost and zero values altered** — the whole diff was reordering,
 * `parentId: null`, and 51 materialised defaults.
 *
 * This function's previous contract called that "one normalising write" and
 * argued the comparison converges: the first open writes the settled form, and
 * every open after that matches. It converges in one working copy and nowhere
 * else. A package under version control is committed in its authored form, so
 * the convergence resets with every checkout — every developer, opening any
 * shipped package, dirtied it. (It also rested on a claim that was never true:
 * defaults are merged by `AbstractNodeModel`'s constructor, synchronously,
 * during `importJSON` — not "shortly after it returns".)
 *
 * `canonicalise` rather than the caller's own model on purpose. The model is
 * only right on the path that just imported this document; `ensureDiskBaseline`
 * has a file and no model at all, and a signature that let either caller supply
 * an un-normalised baseline would let this defect back in silently.
 *
 * Called *before* any draft is restored: a restored draft is a genuine
 * difference from the file, and is exactly what should reach it.
 */
export function rememberDiskDocument(
  slug: string,
  name: string,
  document: unknown,
  serializer: Pick<WorkflowSerializer, 'canonicalise' | 'sizeIsMeasured'>,
): void {
  lastWritten.set(slug, comparable(name, serializer.canonicalise(document), serializer));
}

/**
 * Establish a baseline for a slug the load path did not open.
 *
 * There is a second legitimate way a document for a slug reaches the canvas.
 * On a reload of the workflow already open in this tab, `resolveOpenRequest`
 * deliberately does **not** re-fetch — it restores this browser's draft for
 * that slug instead — so nothing ever tells autosave what is on disk, and the
 * strict rule above would leave the tab silently never saving again.
 *
 * Asking the backend is the honest answer, and it is one request per page:
 * this seeds from the file, so a restored draft that genuinely differs is
 * written on the next edit, and one that matches is not written at all.
 *
 * Does nothing when a baseline already exists, and — importantly — nothing at
 * all when the fetch fails. A failed read must not become a blind write.
 */
/**
 * The slug a page load may hand disk autosave, after a restore attempt.
 *
 * `production-ready` 71. This exists as a function taking a
 * **`DraftRestoreReport`** rather than as an `if` on a boolean, because the
 * boolean is exactly what went wrong: the caller had two of them in scope —
 * "we intended to restore" and "a document arrived" — and passed the first.
 * A type the plan cannot satisfy makes that a compile error.
 *
 * `null` means *no baseline*, which `writeOpenWorkflowToDisk` reads as
 * **never write this package** — the correct answer for a canvas holding a
 * document that did not come from it.
 */
export function baselineSlugAfterRestore(
  report: DraftRestoreReport,
  openSlug: string | null,
): string | null {
  if (!report.restored) return null;
  return openSlug !== null && openSlug !== '' ? openSlug : null;
}

export async function ensureDiskBaseline(
  slug: string,
  client: Pick<IWorkflowFileClient, 'load'>,
  serializer: Pick<WorkflowSerializer, 'canonicalise' | 'sizeIsMeasured'>,
): Promise<void> {
  if (lastWritten.has(slug)) return;
  const disk = await client.load(slug);
  if (!disk.ok) return;
  const document = disk.value as { name?: string };
  if (lastWritten.has(slug)) return; // a load may have landed while we waited
  // Canonicalised for the same reason `rememberDiskDocument` is: what came back
  // is the file's authored form, and what it will be compared against is the
  // model's. See that function for what comparing the two raw cost.
  lastWritten.set(
    slug,
    comparable(document.name ?? '', serializer.canonicalise(disk.value), serializer),
  );
}

/** Drop a slug's baseline — for tests, and for a package that was deleted. */
export function forgetDiskDocument(slug: string): void {
  lastWritten.delete(slug);
}

/**
 * Stop writing to a package that no longer exists, and let the document go on.
 *
 * **launch-readiness 147, a data-loss blocker.** The file watch already told
 * this tab its workflow had been deleted, within five seconds, in a toast that
 * named the right cause — and then nothing happened. The baseline stayed, so
 * one keystroke fired the writer, `PUT` re-created the directory at a free
 * slug, and the package came back holding `workflow.json` and `AGENTS.md`
 * while `tools/`, `functions/`, `tests/`, `skills/`, `middlewares/` and
 * `data/` — the user's own Python — stayed deleted. The tab looked like it
 * had saved successfully, because it had.
 *
 * The two calls are two different things and both are needed:
 *
 * - **`forgetDiskDocument`** is the disarm. `writeOpenWorkflowToDisk` reads a
 *   missing baseline as *never write this package*, which is already its rule
 *   for a document that did not come from this slug — and a document whose
 *   slug no longer names anything is exactly that.
 * - **`clearOpenSlug`** is the path forward, and it is why this is not just a
 *   disarm. A slug is minted at first save and frozen, because a slug that
 *   moves renames a directory; so a document whose package is gone cannot have
 *   that identity back, and the honest offer is a **new** package. Releasing
 *   the slug is what makes the next Save call `create` and be handed a fresh
 *   one, exactly as it does for a canvas that was never saved.
 *
 * **The document itself is untouched.** Dropping it would be this ticket's
 * data loss with the arrow reversed, and it is the one thing the user still
 * has. It keeps autosaving to the browser under the freshly minted draft key
 * `clearOpenSlug` announces (`followOpenSubjectWithDraftKey`).
 *
 * `forgetKnownSavedAt` goes with them so nothing is left claiming to know when
 * a file that does not exist was last written — and so a package later created
 * at the same slug is baselined afresh rather than compared against a corpse.
 *
 * Lives here, beside the writer it disarms, rather than in the watch that
 * calls it: the watch's job is to decide, and this is what the decision means.
 *
 * ## The draft goes with the tab — `launch-readiness` 153
 *
 * Releasing the slug re-keys autosave to a fresh `wf-<timestamp>`, and autosave
 * writes nothing until the next edit. So between the delete and that edit the
 * document lived **only in memory**: the `slug-<slug>` draft was no longer this
 * tab's and the new key held nothing, and a reload landed on a blank canvas
 * while the work sat in `localStorage` under a name nobody would ask for again.
 * Observed live. `carryDraftToFreshKey` moves it onto the new key, which makes
 * "who owns this draft now" one statement instead of two half-answers, and
 * deletes nothing.
 *
 * ## Why the cause is a parameter and not a default
 *
 * The two callers want opposite things with the draft and only they know which
 * is which, so neither may be guessed:
 *
 * - **`deleted-elsewhere`** — the file watch, acting on somebody else's delete.
 *   The user did not ask for this and their unsaved edits are still on screen,
 *   so the draft is **carried**.
 * - **`deleted-here`** — the Workflows panel, acting on this tab's own Delete.
 *   `148` already settled that: this tab's own draft goes, because the user
 *   asked for it; another live tab's is kept and the user is told.
 *
 * The discard moved *in here* rather than staying a second call beside it, so
 * a third caller cannot get the order wrong — which is exactly what the second
 * call site had wrong (`launch-readiness` 169): it asked "is this draft this
 * tab's?" after the release had already re-keyed the tab, so the answer was
 * always no and the panel's own delete kept the orphan `95` exists to remove
 * while telling the user another tab was editing it.
 */
export type DeleteCause = 'deleted-here' | 'deleted-elsewhere';

/** What became of this browser's draft of the package. */
export type AbandonedDraft =
  /** Moved onto the fresh key this tab was re-keyed to (`deleted-elsewhere`). */
  | 'carried'
  /** Removed: the user asked for this delete, in this tab (`deleted-here`). */
  | 'discarded'
  /** Left alone because another live tab is editing it (`148`). */
  | 'kept-for-another-tab'
  /** There was nothing under the slug's key, or it was not this tab's to move. */
  | 'untouched';

export interface AbandonOutcome {
  readonly draft: AbandonedDraft;
}

export function abandonDeletedWorkflow(slug: string, cause: DeleteCause): AbandonOutcome {
  forgetDiskDocument(slug);
  forgetKnownSavedAt(slug);

  // Read **before** the release, because releasing the slug re-keys this tab
  // and afterwards the question "was this tab writing that draft" can no longer
  // be asked. Getting this order wrong is `launch-readiness` 169.
  const before = currentDraftId();
  if (getOpenSlug() === slug) clearOpenSlug();

  if (cause === 'deleted-here') {
    const decision = discardDraftAfterDelete(slug, undefined, before);
    return { draft: decision.discarded ? 'discarded' : 'kept-for-another-tab' };
  }
  const carry = carryDraftToFreshKey(slug, before, currentDraftId());
  return { draft: carry.carried ? 'carried' : 'untouched' };
}

/**
 * Write the open document to its package, and keep the file watch quiet.
 *
 * **Attributing the write is not bookkeeping, it is what makes this possible
 * at all.** `useWorkflowFileWatch` polls the open slug and warns when the file
 * moved underneath the editor — which, once the editor writes on every edit,
 * is *every edit*. Without attribution, autosave would raise a notice per
 * keystroke complaining about itself.
 *
 * The attribution is a *forget*, not a record, because `PUT` answers with the
 * document and not the stamp it just wrote. Dropping the baseline makes the
 * watcher's next poll return `baseline` — which adopts the new value silently,
 * exactly as it does the first time it sees a slug — instead of
 * `notify-changed`. That is one HTTP call rather than the read-back a record
 * would need, and it leans on behaviour the watcher already had rather than
 * on a new contract field.
 */
export async function writeOpenWorkflowToDisk(
  client: Pick<IWorkflowFileClient, 'save'>,
  model: WorkflowModel,
  serializer: WorkflowSerializer,
  storage: Pick<Storage, 'getItem'>,
): Promise<DiskAutosaveOutcome> {
  const slug = diskAutosaveTarget(storage);
  if (!slug) return { kind: 'skipped' };

  // **Never write a package this page has not opened.** The baseline is
  // recorded by the load path, so its absence means the document in memory did
  // not come from this slug — and `getOpenSlug()` cannot tell the difference,
  // because it reads `sessionStorage`, which survives a reload.
  //
  // That gap is a race with teeth. On a deep link the autosave listener is
  // live from mount, while the document arrives over the network some time
  // later; in between, the model holds the seeded demo (or a restored draft)
  // and the open slug already names the target package. A load slower than the
  // autosave debounce would therefore write the *demo* into somebody's
  // workflow. Requiring the baseline closes that window, and it is the same
  // condition that stops a reload from rewriting a file nobody edited.
  const prev = lastWritten.get(slug);
  if (prev === undefined) return { kind: 'skipped' };

  const document = serializer.serialize(model);
  const payload = comparable(model.name, document, serializer);
  if (prev === payload) return { kind: 'unchanged' };

  const result = await client.save(slug, model.name, document);
  if (!result.ok) return { kind: 'failed', reason: result.error };

  lastWritten.set(slug, payload);
  forgetKnownSavedAt(slug);
  return { kind: 'saved' };
}

/**
 * What we believe `workflows/<root>/workflow.json` holds while a mount of it
 * is open.
 *
 * Its own map rather than a second meaning for `lastWritten`, because the two
 * hold different *forms* of a document. `lastWritten` holds the serializer's
 * canonical form of a model; this holds the host document exactly as the
 * backend served it and `MountContext` then mutates it in place. Comparing one
 * against the other would report a difference on every tick and write the host
 * file forever, which is the failure `comparable` is documented at length to
 * prevent.
 */
const lastHostWritten = new Map<string, string>();

/**
 * Record the host as loaded, so an override is the first thing that changes it.
 *
 * Called by the drill-in load path, beside the `savedAt` baselines it already
 * records. Without it `writeOpenMountHostToDisk` refuses every write — the
 * same "never write a package this page has not opened" rule the class path
 * follows, and for the same reason: the host document is written **whole**,
 * so a blind write reverts whatever it did not see.
 */
export function rememberMountHostDocument(root: string, document: unknown): void {
  lastHostWritten.set(root, canonical(document));
}

/** Drop a host's baseline — on leaving an instance, and for tests. */
export function forgetMountHostDocument(root: string): void {
  lastHostWritten.delete(root);
}

/**
 * Write the open mount's **host** package — the document its override lives in.
 *
 * The instance's own state is `data.overrides` on the host's mount node, so
 * this is the one file an edit inside a drill-in has any business touching.
 * The package the mount points at is not written here and must never be:
 * mount-by-reference is what makes two mounts of one package able to differ,
 * and the ticket that produced this function reported the package half as
 * already correct.
 *
 * **Compare-and-set, unlike the class path, and deliberately.**
 * `writeOpenWorkflowToDisk` writes a document this tab is the sole author of,
 * and the file watch is following that slug so a change underneath is noticed.
 * Neither is true here: `mounts.rootDocument` is a whole retained document
 * that goes stale from the moment the drill-in begins, and the watch follows
 * the *class* while an instance is open, so nothing else would notice the host
 * moving. `WorkflowManager.handleSave` already guarded its explicit save this
 * way; an automatic save writes the same bytes far more often and silently, so
 * it needs the guard more rather than less.
 */
export async function writeOpenMountHostToDisk(
  client: Pick<IWorkflowFileClient, 'save' | 'summary'>,
  mounts: Pick<MountContext, 'address' | 'rootDocument'> | null,
): Promise<DiskAutosaveOutcome> {
  if (!mounts) return { kind: 'skipped' };

  const root = mounts.address.root;
  const prev = lastHostWritten.get(root);
  if (prev === undefined) return { kind: 'skipped' };

  const payload = canonical(mounts.rootDocument);
  if (prev === payload) return { kind: 'unchanged' };

  // **One seam, not one convention** (`production-ready` 102). The
  // compare-and-set on the parent's `saved_at`, the write, the draft supersede
  // that 101 was filed for, and the adoption of our own write as the next
  // baseline are one protocol, and this writer used to spell it out itself
  // alongside a second hand-written copy in the Save mount button. Getting
  // different halves of it right at two sites is what 101 did, and what it
  // said it had not fixed.
  const outcome = await writeHostPackage(client, mounts);
  if (outcome.kind === 'refused') return { kind: 'failed', reason: outcome.reason };
  if (outcome.kind === 'failed') return { kind: 'failed', reason: outcome.error };

  lastHostWritten.set(root, payload);
  return { kind: 'saved' };
}
