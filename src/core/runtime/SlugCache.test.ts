import { describe, expect, it, vi } from 'vitest';
import { invalidateSlug, SlugCache } from './SlugCache';

type State = { readonly status: 'ready' | 'failed'; readonly value?: string };

const ready = (value: string): State => ({ status: 'ready', value });
const failed: State = { status: 'failed' };
const keepReady = (state: State) => state.status === 'ready';

function makeCache(limit = 4) {
  return new SlugCache<State>('test', { keep: keepReady, limit });
}

describe('SlugCache coalescing', () => {
  it('shares one in-flight request between concurrent askers', async () => {
    // The reason these caches exist at all: a card re-renders on every drag,
    // and two mounts of the same package on one canvas would each fetch.
    const cache = makeCache();
    const load = vi.fn(async () => ready('doc'));
    const [a, b] = await Promise.all([cache.resolve('x', load), cache.resolve('x', load)]);
    expect(load).toHaveBeenCalledTimes(1);
    expect(a).toEqual(b);
  });

  it('answers synchronously once settled, for the first render after a remount', async () => {
    const cache = makeCache();
    expect(cache.settled('x')).toBeUndefined();
    await cache.resolve('x', async () => ready('doc'));
    expect(cache.settled('x')).toEqual(ready('doc'));
  });
});

describe('SlugCache eviction', () => {
  it('drops a value it was told not to keep, so a failure retries', async () => {
    // An unreachable runtime is not a fact about the document. This was
    // duplicated as a `CACHE.delete(slug)` inside all three loaders; it is
    // one predicate now.
    const cache = makeCache();
    const load = vi.fn(async () => failed);
    await cache.resolve('x', load);
    expect(cache.settled('x')).toBeUndefined();
    await cache.resolve('x', load);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('forgets one slug when that package changes underneath it', async () => {
    const cache = makeCache();
    await cache.resolve('x', async () => ready('first'));
    await cache.resolve('y', async () => ready('other'));
    cache.invalidate('x');
    expect(cache.settled('x')).toBeUndefined();
    expect(cache.settled('y')).toEqual(ready('other'));
    await cache.resolve('x', async () => ready('second'));
    expect(cache.settled('x')).toEqual(ready('second'));
  });

  it('reaches every cache from one catalogue event', async () => {
    // The three live in two files and must not drift: one event, one call.
    const a = makeCache();
    const b = makeCache();
    await a.resolve('x', async () => ready('a'));
    await b.resolve('x', async () => ready('b'));
    invalidateSlug('x');
    expect(a.settled('x')).toBeUndefined();
    expect(b.settled('x')).toBeUndefined();
  });

  it('holds no more settled slugs than its stated limit', async () => {
    const cache = makeCache(3);
    for (const slug of ['a', 'b', 'c', 'd', 'e']) {
      await cache.resolve(slug, async () => ready(slug));
    }
    expect(cache.size).toBe(3);
    expect(cache.settled('a')).toBeUndefined();
    expect(cache.settled('e')).toEqual(ready('e'));
  });

  it('evicts the least recently used, not the oldest', async () => {
    // A mount card asks on every render, so "recently asked about" is a far
    // better guess at "still on screen" than "recently fetched".
    const cache = makeCache(3);
    for (const slug of ['a', 'b', 'c']) await cache.resolve(slug, async () => ready(slug));
    await cache.resolve('a', async () => ready('a')); // a is now the freshest
    await cache.resolve('d', async () => ready('d'));
    expect(cache.settled('b')).toBeUndefined();
    expect(cache.settled('a')).toEqual(ready('a'));
  });

  it('never evicts a request still in flight', async () => {
    // Evicting one would not be wrong, only wasteful — the asker still gets
    // its answer, but a second asker starts a second request. A canvas with
    // more mounts than the limit is exactly when that matters most.
    const cache = makeCache(2);
    let release = () => {};
    const pending = new Promise<State>((resolve) => {
      release = () => resolve(ready('slow'));
    });
    const slow = cache.resolve('slow', () => pending);
    for (const slug of ['a', 'b', 'c']) await cache.resolve(slug, async () => ready(slug));

    const second = cache.resolve('slow', async () => ready('should not be asked'));
    release();
    expect(await slow).toEqual(ready('slow'));
    expect(await second).toEqual(ready('slow'));
  });
});
