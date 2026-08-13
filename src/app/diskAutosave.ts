import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { isInstance } from '@core/model/MountAddress';
import { getOpenAddress } from './openAddress';
import { CURRENT_SLUG_KEY, forgetKnownSavedAt } from './workflowFileWatch';

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
 *   every other mount. `WorkflowManager.handleSave` handles that case by
 *   writing the **parent**, with a compare-and-set on its `savedAt`; doing
 *   that silently on every keystroke is not the same trade.
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
 * card. Nobody types it and nobody drags it — the card reports how tall it
 * ended up. Left in the comparison, an idle editor rewrote
 * `workflows/chinook-assistant/workflow.json` every few seconds forever: the
 * Get Table Schema card alternates between 118px and 200px as its schema list
 * settles, each measurement counted as an edit, and each write moved
 * `savedAt`. That oscillation is a canvas defect in its own right and is
 * recorded as one — but a measurement must not be able to dirty a file even
 * after it is fixed.
 *
 * `position` stays in: dragging a node *is* an edit, and one a developer
 * expects to survive a reload.
 */
function comparable(name: string, document: unknown): string {
  const { nodes, ...rest } = document as { nodes?: readonly Record<string, unknown>[] };
  return canonical({
    name,
    ...rest,
    nodes: (nodes ?? []).map(({ size: _size, ...node }) => node),
  });
}

/**
 * Record what a freshly-loaded document looked like, so opening it is not an
 * edit.
 *
 * Seeded from the **round-tripped** form — `serializer.serialize(model)` after
 * the import, not the raw file — because the two are not byte-identical: the
 * file omits defaulted fields and the model materialises them. Comparing
 * against the raw file would therefore report a change on every load and
 * defeat the point. The consequence is one normalising write the first time
 * each package is opened after this shipped, and none afterwards.
 *
 * Called *before* any draft is restored: a restored draft is a genuine
 * difference from the file, and is exactly what should reach disk.
 */
export function rememberDiskDocument(
  slug: string,
  model: WorkflowModel,
  serializer: WorkflowSerializer,
): void {
  lastWritten.set(slug, comparable(model.name, serializer.serialize(model)));
}

/** Drop a slug's baseline — for tests, and for a package that was deleted. */
export function forgetDiskDocument(slug: string): void {
  lastWritten.delete(slug);
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

  const document = serializer.serialize(model);
  const payload = comparable(model.name, document);
  if (lastWritten.get(slug) === payload) return { kind: 'unchanged' };

  const result = await client.save(slug, model.name, document);
  if (!result.ok) return { kind: 'failed', reason: result.error };

  lastWritten.set(slug, payload);
  forgetKnownSavedAt(slug);
  return { kind: 'saved' };
}
