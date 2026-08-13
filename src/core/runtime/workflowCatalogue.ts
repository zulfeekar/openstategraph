import type { ICatalogueEvents, IWorkflowFileClient } from './WorkflowFileClient';

/**
 * Which workflow slugs exist, answerable **synchronously**.
 *
 * A mount's slug was a free-text box: nothing populated it, nothing validated
 * it, and nothing told a developer what existed. A typo produced a mount that
 * resolved to nothing, and anybody who did not already know the catalogue by
 * heart could not discover it (production-ready ticket 05).
 *
 * The awkward part is the shape of the seam, not the list. A field's `options`
 * is a **synchronous** function — it is called during a render — while the
 * catalogue arrives over HTTP. So this holds the last answer and is refreshed
 * around the edges, exactly as `ProviderRegistry` does for the model picker:
 * the picker asks a question that is always cheap to answer, and something
 * else keeps the answer current.
 *
 * **Live, because a package made two minutes ago must be selectable.** The
 * backend already broadcasts catalogue changes over `GET /api/events`; this
 * subscribes rather than polling, so the list moves when the catalogue does.
 *
 * Deliberately holds slugs and names only. It is not a cache of documents —
 * `CompositionBody` already resolves a slug to its document for the card
 * census, and a second copy of that would be a second thing to invalidate.
 */
export interface WorkflowChoice {
  readonly slug: string;
  readonly name: string;
}

type Listener = () => void;

export class WorkflowCatalogue {
  private choices: readonly WorkflowChoice[] = [];
  private readonly listeners = new Set<Listener>();

  /** Every known workflow, sorted by name so the list does not jump about. */
  list(): readonly WorkflowChoice[] {
    return this.choices;
  }

  /**
   * Replaces the known list, notifying only when it actually changed.
   *
   * The comparison matters: a catalogue event fires for a *save*, which does
   * not change the slug set, and a needless notification re-renders every
   * mount card on the canvas.
   */
  set(choices: readonly WorkflowChoice[]): void {
    const next = [...choices].sort((a, b) => a.name.localeCompare(b.name));
    const same =
      next.length === this.choices.length &&
      next.every((choice, index) => {
        const current = this.choices[index];
        return current?.slug === choice.slug && current?.name === choice.name;
      });
    if (same) return;
    this.choices = next;
    for (const listener of this.listeners) listener();
  }

  onChange(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Keeps this current: one read now, then one per catalogue change.
   *
   * Returns an unsubscribe. Failures are swallowed — an editor that cannot
   * reach the backend still has to let a developer type a slug, and a picker
   * that throws during a render is worse than a picker with nothing in it.
   */
  syncFrom(client: IWorkflowFileClient & Partial<ICatalogueEvents>): () => void {
    const refresh = () => {
      void client
        .list()
        .then((result) => {
          if (result.ok) {
            this.set(result.value.map((row) => ({ slug: row.slug, name: row.name })));
          }
        })
        .catch(() => {
          /* keep the last good list */
        });
    };

    refresh();
    // `ICatalogueEvents` is a separate interface on purpose — a caller that
    // only loads documents must not have to declare a subscription it never
    // opens — so a client without it still gets the one read above.
    const watch = client.watchCatalogue;
    if (typeof watch !== 'function') return () => {};
    return watch.call(client, () => refresh());
  }
}

/**
 * The one catalogue the editor reads.
 *
 * A module singleton, matching `capabilityWarnings` in `app/pluginNodes`: a
 * node *definition* is data assembled at import time, so it cannot be handed a
 * dependency the way a React component can. The alternative — turning
 * `subgraphNode` into a `createSubgraphNode(catalogue)` factory the way the
 * agent takes a `ProviderRegistry` — was weighed and is the better shape if a
 * second consumer ever appears; one consumer did not justify threading it
 * through the registry, the palette and every test that names the definition.
 */
export const workflowCatalogue = new WorkflowCatalogue();
