import type { CatalogueChange, ICatalogueEvents, IWorkflowFileClient } from './WorkflowFileClient';

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
 * Deliberately holds what a picker prints and nothing else. It is not a cache
 * of documents — `CompositionBody` already resolves a slug to its document for
 * the card census, and a second copy of that would be a second thing to
 * invalidate.
 */
export interface WorkflowChoice {
  readonly slug: string;
  readonly name: string;
  /**
   * Whether a **customer** surface advertises this package — the row's own
   * `hidden` flag, carried through rather than dropped (ticket 57).
   *
   * The third field, and it earns the place the way the other two do: it is
   * printed. `GET /api/workflows?surface=editor` returns hidden packages
   * deliberately — `concierge` mounts `workflow-architect`, so filtering them
   * would make a shipped composition undrawable — and sets the flag "so the UI
   * can mark one rather than pretend it is not there". Both consumers of this
   * list are that UI: the Packages palette and the mount combobox. Until
   * ticket 57 neither read it, so `concierge` and `workflow-architect` looked
   * exactly like a package a developer can put in front of customers.
   *
   * Not a cache of the document, and not the whole `WorkflowSummary` either:
   * `published` is deliberately absent, because publishing is an *action*
   * surface (`WorkflowManager` owns it) and a picker that printed a lifecycle
   * badge it could not change would invite a click that goes nowhere.
   */
  readonly hidden: boolean;
}

/**
 * The word every picker prints on a hidden package's row, and the sentence
 * behind it.
 *
 * One constant rather than two literals, because two surfaces mark the same
 * rows and are deliberately consistent with each other — the Packages palette
 * (`view/palette/Palette.tsx`) and the mount combobox
 * (`nodes/compose/SubgraphNode.ts`). Two spellings would agree on the day they
 * were written and drift on the first reword, which is the failure this
 * codebase keeps finding in prose.
 *
 * A user-facing string in `core/` for the same reason `mountCycleRefusal`'s
 * sentence is one: the rule and its words are the same knowledge, and a
 * surface that re-words the verdict is a surface that can contradict it.
 */
export const HIDDEN_PACKAGE_MARK = 'Hidden';

/**
 * Why, in one sentence — shown where a surface has room for one. A native
 * `<datalist>` option has no tooltip, so the combobox prints the mark alone;
 * the palette hangs this off the mark itself, keyboard-reachable.
 *
 * **Plain words, deliberately.** This read *"no customer surface advertises
 * this package: it stays out of the /chat picker even when published"* until
 * the owner asked what it meant — four pieces of internal vocabulary
 * (*customer surface*, *advertises*, *the /chat picker*, *the shipped
 * gateway*) in a sentence whose whole job is to explain a word somebody did
 * not recognise. An explanation that needs an explanation has not been given.
 */
export const HIDDEN_PACKAGE_NOTE =
  'Hidden — people using the chat app never see this workflow in their list, even after you publish it. It is a building block: other workflows mount it, rather than a person picking it.';

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
        // Every printed field, `hidden` included: editing `hidden: true` into
        // a package's `workflow.json` moves no slug, and a comparison blind to
        // it would leave the mark off every card and row until something else
        // happened to change the list.
        return (
          current?.slug === choice.slug &&
          current?.name === choice.name &&
          current?.hidden === choice.hidden
        );
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
   *
   * `onChange` forwards the raw change to the caller before the refresh. This
   * object cares only about the slug *list*, but the event carries which slug
   * moved, and the editor holds exactly one `/api/events` subscription on
   * purpose (`workflowFileWatch.ts`) — so anything else that needs to know a
   * package changed is handed it here rather than opening a second one.
   */
  syncFrom(
    client: IWorkflowFileClient & Partial<ICatalogueEvents>,
    onChange?: (change: CatalogueChange) => void,
  ): () => void {
    const refresh = () => {
      void client
        .list()
        .then((result) => {
          if (result.ok) {
            this.set(
              result.value.map((row) => ({
                slug: row.slug,
                name: row.name,
                hidden: row.hidden,
              })),
            );
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
    return watch.call(client, (change) => {
      onChange?.(change);
      refresh();
    });
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
