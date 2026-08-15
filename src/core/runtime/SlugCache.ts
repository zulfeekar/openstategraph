/**
 * One answer per workflow slug, fetched once and forgotten on purpose.
 *
 * Three card bodies had grown the same map independently — a whole workflow
 * document per slug and a compiled Mermaid SVG per slug in `CompositionBody`,
 * a database schema per slug in `SqlSchemaBody`. The coalescing they exist for
 * is real and stays: a card re-renders on every drag, and two mounts of one
 * package on a canvas would otherwise each hit the backend continuously.
 *
 * What none of them had was a way out. An entry was deleted only when the
 * fetch *failed*; a success stayed for the life of the tab, and
 * `CompositionBody`'s own comment claimed failures were cached "only until the
 * next slug change" — an eviction that existed nowhere in either file. Three
 * copies of one idea in two files, each holding the heaviest payloads in the
 * app, and the mount/drill work that landed in the same window made visiting
 * many slugs in one session the ordinary way to use the product.
 *
 * So this is the idea, once, with the three ways an entry dies stated:
 *
 * 1. **It was never worth keeping.** `keep` decides — an unreachable runtime
 *    is not a fact about a document, so it must retry rather than stick.
 * 2. **The package changed.** `invalidateSlug` is called from the one live
 *    `/api/events` subscription the editor already holds, so a save through
 *    the editor drops exactly that slug. This is also a staleness fix: before
 *    it, drilling into a mount, editing it, saving and coming back showed the
 *    parent card the census of the document as it was on first sight.
 * 3. **Something newer needed the room.** `limit` is a stated ceiling, least
 *    recently *asked about* evicted first — a card asks on every render, so
 *    recency of asking tracks what is on screen far better than recency of
 *    fetching does.
 *
 * A hand-edit to `workflow.json` on disk emits no event (the backend's fan-out
 * covers writes through the API), so rule 2 does not cover it. Rule 3 does,
 * eventually, and a reload always does. That limit is inherited from
 * `watchCatalogue` and documented there.
 */

export interface SlugCacheOptions<T> {
  /** Whether a settled value is worth holding at all. */
  readonly keep: (value: T) => boolean;
  /**
   * How many settled slugs to hold. A canvas shows a handful of distinct
   * mounts; the default leaves generous room above that while keeping the
   * ceiling a number someone chose rather than a number nobody wrote down.
   */
  readonly limit?: number;
}

interface Entry<T> {
  readonly inFlight: Promise<T>;
  settled?: T;
  done: boolean;
}

const DEFAULT_LIMIT = 24;

/**
 * Every live cache, so one catalogue event reaches all of them.
 *
 * Never unregistered, and that is not an oversight: the three callers are
 * module singletons that live as long as the tab, exactly like the maps they
 * replaced. A cache with a lifecycle would need one here too.
 */
const CACHES = new Set<{ invalidate: (slug: string) => void; clear: () => void }>();

/** Drops one slug from every cache. Called when that package changed. */
export function invalidateSlug(slug: string): void {
  for (const cache of CACHES) cache.invalidate(slug);
}

/** Drops everything from every cache. For a wholesale change of backend. */
export function clearSlugCaches(): void {
  for (const cache of CACHES) cache.clear();
}

export class SlugCache<T> {
  /** Insertion order is the LRU order; a hit re-inserts. */
  private readonly entries = new Map<string, Entry<T>>();
  private readonly limit: number;

  /** @param label names the cache in a debugger; it has no behaviour. */
  constructor(
    readonly label: string,
    private readonly options: SlugCacheOptions<T>,
  ) {
    this.limit = options.limit ?? DEFAULT_LIMIT;
    CACHES.add(this);
  }

  /** The shared promise for this slug, starting `load` only if none exists. */
  resolve(slug: string, load: () => Promise<T>): Promise<T> {
    const existing = this.entries.get(slug);
    if (existing) {
      this.touch(slug, existing);
      return existing.inFlight;
    }

    const inFlight = load();
    const entry: Entry<T> = { inFlight, done: false };
    this.entries.set(slug, entry);
    void inFlight.then(
      (settled) => this.settle(slug, entry, settled),
      () => {
        // A rejected loader is a failure like any other, and holding a
        // rejected promise would re-throw at every later asker.
        this.entries.delete(slug);
      },
    );
    this.evict();
    return inFlight;
  }

  /** The settled value, for the first render after a card remounts. */
  settled(slug: string): T | undefined {
    return this.entries.get(slug)?.settled;
  }

  invalidate(slug: string): void {
    this.entries.delete(slug);
  }

  clear(): void {
    this.entries.clear();
  }

  /** Entries held, in flight or settled. */
  get size(): number {
    return this.entries.size;
  }

  private settle(slug: string, entry: Entry<T>, value: T): void {
    entry.done = true;
    if (!this.options.keep(value)) {
      // Only if this entry is still the one under that slug — an invalidation
      // during the flight must not be undone by the flight landing.
      if (this.entries.get(slug) === entry) this.entries.delete(slug);
      return;
    }
    entry.settled = value;
    this.evict();
  }

  private touch(slug: string, entry: Entry<T>): void {
    this.entries.delete(slug);
    this.entries.set(slug, entry);
  }

  private evict(): void {
    if (this.entries.size <= this.limit) return;
    for (const [slug, entry] of this.entries) {
      if (this.entries.size <= this.limit) return;
      // Never a request still in flight: evicting one costs a duplicate
      // fetch, and a canvas with more mounts than the limit is exactly when
      // the coalescing is worth the most.
      if (!entry.done) continue;
      this.entries.delete(slug);
    }
  }
}
