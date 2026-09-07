import type { IDisposable, Unsubscribe } from './Disposable';

/** Map of event name → payload type. Bus instances are typed by one of these. */
export type EventMap = Record<string, unknown>;

export interface IEventBus<M extends EventMap> {
  on<K extends keyof M & string>(type: K, handler: (payload: M[K]) => void): Unsubscribe;
  once<K extends keyof M & string>(type: K, handler: (payload: M[K]) => void): Unsubscribe;
  /** Fires for every event; used by the undo stack and devtools logging. */
  onAny(handler: <K extends keyof M & string>(type: K, payload: M[K]) => void): Unsubscribe;
  emit<K extends keyof M & string>(type: K, payload: M[K]): void;
}

/**
 * A small synchronous typed event bus.
 *
 * Synchronous on purpose: the canvas adapter has to observe a model change
 * and update the paper within the same task, or a drag would visibly lag a
 * frame behind the pointer.
 *
 * Handlers added during a dispatch are not called for that dispatch, and
 * handlers removed during it are not called either — the set is snapshotted
 * per emit. That keeps re-entrant graph edits (a listener that adds a node)
 * predictable instead of order-dependent.
 */
export class EventBus<M extends EventMap> implements IEventBus<M>, IDisposable {
  private readonly handlers = new Map<string, Set<(payload: unknown) => void>>();
  private readonly anyHandlers = new Set<(type: string, payload: unknown) => void>();
  private suspended = 0;
  private readonly queue: { type: string; payload: unknown }[] = [];

  on<K extends keyof M & string>(type: K, handler: (payload: M[K]) => void): Unsubscribe {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    const erased = handler as (payload: unknown) => void;
    set.add(erased);
    return () => {
      set?.delete(erased);
      if (set?.size === 0) this.handlers.delete(type);
    };
  }

  once<K extends keyof M & string>(type: K, handler: (payload: M[K]) => void): Unsubscribe {
    const off = this.on(type, (payload) => {
      off();
      handler(payload);
    });
    return off;
  }

  onAny(handler: <K extends keyof M & string>(type: K, payload: M[K]) => void): Unsubscribe {
    const erased = handler as (type: string, payload: unknown) => void;
    this.anyHandlers.add(erased);
    return () => this.anyHandlers.delete(erased);
  }

  emit<K extends keyof M & string>(type: K, payload: M[K]): void {
    if (this.suspended > 0) {
      this.queue.push({ type, payload });
      return;
    }
    this.dispatch(type, payload);
  }

  /**
   * Coalesces the events produced by `fn` and flushes them afterwards.
   *
   * Used around composite mutations (paste, auto-layout, import) so the
   * canvas re-renders once instead of once per node.
   */
  batch<T>(fn: () => T): T {
    this.suspended += 1;
    try {
      return fn();
    } finally {
      this.suspended -= 1;
      if (this.suspended === 0) this.flush();
    }
  }

  private flush(): void {
    // Drain by index: a handler may enqueue further events, and those
    // belong in the same flush rather than a later microtask.
    while (this.queue.length > 0) {
      const event = this.queue.shift();
      if (event) this.dispatch(event.type, event.payload);
    }
  }

  private dispatch(type: string, payload: unknown): void {
    const set = this.handlers.get(type);
    if (set) {
      for (const handler of [...set]) {
        try {
          handler(payload);
        } catch (error) {
          console.error(`[openstategraph] handler for "${type}" threw`, error);
        }
      }
    }
    for (const handler of [...this.anyHandlers]) {
      try {
        handler(type, payload);
      } catch (error) {
        console.error('[openstategraph] wildcard handler threw', error);
      }
    }
  }

  dispose(): void {
    this.handlers.clear();
    this.anyHandlers.clear();
    this.queue.length = 0;
  }
}
