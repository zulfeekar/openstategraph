import { describe, expect, it, vi } from 'vitest';
import { Ok, type Result } from '@core/kernel/Result';
import { WorkflowCatalogue, type WorkflowChoice } from './workflowCatalogue';
import type { CatalogueChange } from './WorkflowFileClient';

/**
 * production-ready ticket 05.
 *
 * A mount's slug was a free-text box: nothing populated it, nothing validated
 * it, and nothing told a developer what existed. A typo produced a mount that
 * resolved to nothing, and the catalogue was discoverable only by already
 * knowing it.
 *
 * The awkward part is the *shape* of the seam. A field's `options` is called
 * during a render and must answer synchronously; the catalogue arrives over
 * HTTP. So this holds the last answer, and is refreshed around the edges —
 * the same arrangement `ProviderRegistry` has with the model picker.
 */
const row = (slug: string, name: string, hidden = false) => ({ slug, name, hidden });

const clientReturning = (
  ...pages: (readonly { slug: string; name: string; hidden: boolean }[])[]
) => {
  let call = 0;
  const watchers: ((change: CatalogueChange) => void)[] = [];
  return {
    list: vi.fn(async (): Promise<Result<readonly WorkflowChoice[], string>> =>
      Ok(pages[Math.min(call++, pages.length - 1)] ?? []),
    ),
    watchCatalogue: (onChange: (change: CatalogueChange) => void) => {
      watchers.push(onChange);
      return () => {};
    },
    fire: (slug = 'a') =>
      watchers.forEach((w) => w({ reason: 'saved', slug, surfaceVisible: true })),
  };
};

describe('the workflow catalogue', () => {
  it('answers synchronously, because a render cannot await', () => {
    const catalogue = new WorkflowCatalogue();
    expect(catalogue.list()).toEqual([]);
  });

  it('sorts by name, so the list does not jump about between reads', () => {
    const catalogue = new WorkflowCatalogue();
    catalogue.set([row('z', 'Zebra'), row('a', 'Aardvark')]);
    expect(catalogue.list().map((c) => c.slug)).toEqual(['a', 'z']);
  });

  it('notifies when the set really changed', () => {
    const catalogue = new WorkflowCatalogue();
    const listener = vi.fn();
    catalogue.onChange(listener);

    catalogue.set([row('a', 'A')]);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('stays quiet when it did not', () => {
    // A catalogue event fires for a *save*, which does not change the slug
    // set — and a needless notification re-renders every mount on the canvas.
    const catalogue = new WorkflowCatalogue();
    catalogue.set([row('a', 'A')]);
    const listener = vi.fn();
    catalogue.onChange(listener);

    catalogue.set([row('a', 'A')]);
    expect(listener).not.toHaveBeenCalled();
  });

  it('stops notifying once unsubscribed', () => {
    const catalogue = new WorkflowCatalogue();
    const listener = vi.fn();
    catalogue.onChange(listener)();
    catalogue.set([row('a', 'A')]);
    expect(listener).not.toHaveBeenCalled();
  });

  it('reads once on sync, so a picker is populated before anything changes', async () => {
    const catalogue = new WorkflowCatalogue();
    const client = clientReturning([row('chinook-assistant', 'Chinook Assistant')]);

    catalogue.syncFrom(client as never);
    await vi.waitFor(() => expect(catalogue.list()).toHaveLength(1));
    expect(catalogue.list()[0]?.slug).toBe('chinook-assistant');
  });

  it('re-reads when the catalogue changes, so a package made two minutes ago is selectable', async () => {
    // The ticket's requirement, and the reason this subscribes to
    // `/api/events` rather than polling.
    const catalogue = new WorkflowCatalogue();
    const client = clientReturning([row('a', 'A')], [row('a', 'A'), row('b', 'B')]);

    catalogue.syncFrom(client as never);
    await vi.waitFor(() => expect(catalogue.list()).toHaveLength(1));

    client.fire();
    await vi.waitFor(() => expect(catalogue.list()).toHaveLength(2));
  });

  it('survives a client that cannot subscribe', async () => {
    // `ICatalogueEvents` is deliberately a separate interface, so a client
    // that only reads documents is a legal one — it still gets the first read.
    const catalogue = new WorkflowCatalogue();
    const stop = catalogue.syncFrom({ list: async () => Ok([row('a', 'A')]) } as never);

    await vi.waitFor(() => expect(catalogue.list()).toHaveLength(1));
    expect(() => stop()).not.toThrow();
  });

  it('keeps the last good list when a read fails', async () => {
    // An editor that cannot reach the backend must still let a developer type
    // a slug; a picker that throws during a render is worse than an empty one.
    const catalogue = new WorkflowCatalogue();
    catalogue.set([row('a', 'A')]);
    catalogue.syncFrom({
      list: async () => {
        throw new Error('offline');
      },
    } as never);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(catalogue.list()).toHaveLength(1);
  });

  describe('whether a customer surface advertises the package', () => {
    /**
     * production-ready ticket 57. `surface=editor` returns hidden packages
     * (`concierge`, `workflow-architect`) deliberately — `concierge` mounts
     * `workflow-architect`, so filtering them would make a shipped composition
     * undrawable — and every row carries `hidden` "so the UI can mark one
     * rather than pretend it is not there".
     *
     * Nothing marked. Both consumers that show a package to a developer read
     * this object, so the flag has to survive the trip through it: the
     * Packages palette (`view/palette/packageRows.ts`) and the mount combobox
     * (`nodes/compose/SubgraphNode.ts`) get their rows from `list()` and from
     * nowhere else.
     */
    it('survives the trip, because both pickers mark the row with it', async () => {
      const catalogue = new WorkflowCatalogue();
      const client = clientReturning([
        row('chinook-assistant', 'Chinook Assistant'),
        row('workflow-architect', 'Workflow Architect', true),
      ]);

      catalogue.syncFrom(client as never);
      await vi.waitFor(() => expect(catalogue.list()).toHaveLength(2));
      expect(catalogue.list().map((choice) => [choice.slug, choice.hidden])).toEqual([
        ['chinook-assistant', false],
        ['workflow-architect', true],
      ]);
    });

    it('notifies when only it changed, so a mark can appear without the slug set moving', () => {
      // The quiet-when-unchanged rule compares the rows, and `hidden` is now
      // one of the things a row says. Editing `hidden: true` into a package's
      // `workflow.json` moves no slug — so a comparison that ignored the flag
      // would leave every mount card and every palette row showing the old
      // answer until something else happened to change the list.
      const catalogue = new WorkflowCatalogue();
      catalogue.set([row('concierge', 'Concierge')]);
      const listener = vi.fn();
      catalogue.onChange(listener);

      catalogue.set([row('concierge', 'Concierge', true)]);
      expect(listener).toHaveBeenCalledTimes(1);
      expect(catalogue.list()[0]?.hidden).toBe(true);
    });
  });

  it('forwards the change itself, so one subscription serves more than this list', async () => {
    // The event names the slug that moved; this object cares only about the
    // slug *set*. The per-slug card caches need the name, and the editor
    // deliberately holds exactly one `/api/events` subscription — so the
    // change is handed on rather than a second one being opened.
    const catalogue = new WorkflowCatalogue();
    const client = clientReturning([row('a', 'A')]);
    const seen: string[] = [];

    catalogue.syncFrom(client as never, (change) => seen.push(change.slug));
    await vi.waitFor(() => expect(catalogue.list()).toHaveLength(1));

    client.fire('chinook-assistant');
    expect(seen).toEqual(['chinook-assistant']);
  });
});
