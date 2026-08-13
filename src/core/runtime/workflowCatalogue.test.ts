import { describe, expect, it, vi } from 'vitest';
import { Ok, type Result } from '@core/kernel/Result';
import { WorkflowCatalogue, type WorkflowChoice } from './workflowCatalogue';

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
const row = (slug: string, name: string) => ({ slug, name });

const clientReturning = (...pages: (readonly { slug: string; name: string }[])[]) => {
  let call = 0;
  const watchers: (() => void)[] = [];
  return {
    list: vi.fn(async (): Promise<Result<readonly WorkflowChoice[], string>> =>
      Ok(pages[Math.min(call++, pages.length - 1)] ?? []),
    ),
    watchCatalogue: (onChange: () => void) => {
      watchers.push(onChange);
      return () => {};
    },
    fire: () => watchers.forEach((w) => w()),
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
});
