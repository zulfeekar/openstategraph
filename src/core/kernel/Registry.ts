import { EventBus } from './EventBus';
import type { Unsubscribe } from './Disposable';

/** Anything a registry can hold: it must be able to name itself. */
export interface IIdentifiable {
  readonly id: string;
}

interface RegistryEvents<T> extends Record<string, unknown> {
  registered: { entry: T };
  unregistered: { id: string };
}

/**
 * A keyed collection with change notification.
 *
 * This is the seam that makes the app extensible without editing it: node
 * types, port types, LLM providers, node executors and canvas features are
 * all registries. Adding a capability is a `register` call from a plugin
 * module — the engine never learns the concrete type.
 *
 * (This list named "export formats" too, and no such registry is among the
 * instantiations in this codebase. An example in a docstring is a claim about
 * the tree, and this one could not be grepped.)
 *
 * Registration order is preserved, because it drives the order things
 * appear in the palette and in select menus.
 */
export class Registry<T extends IIdentifiable> {
  private readonly entries = new Map<string, T>();
  private readonly bus = new EventBus<RegistryEvents<T>>();

  constructor(private readonly name: string) {}

  register(entry: T): this {
    if (this.entries.has(entry.id)) {
      throw new Error(`[${this.name}] "${entry.id}" is already registered`);
    }
    this.entries.set(entry.id, entry);
    this.bus.emit('registered', { entry });
    return this;
  }

  registerAll(entries: Iterable<T>): this {
    for (const entry of entries) this.register(entry);
    return this;
  }

  /** Replaces an existing entry, or registers it if absent. */
  upsert(entry: T): this {
    this.entries.set(entry.id, entry);
    this.bus.emit('registered', { entry });
    return this;
  }

  unregister(id: string): boolean {
    const removed = this.entries.delete(id);
    if (removed) this.bus.emit('unregistered', { id });
    return removed;
  }

  get(id: string): T | undefined {
    return this.entries.get(id);
  }

  /**
   * Like `get`, but throws. Use where a missing entry means a programming
   * error (a serialized graph referencing an unregistered node type is a
   * data error and should use `get` plus a graceful fallback instead).
   */
  require(id: string): T {
    const entry = this.entries.get(id);
    if (!entry) {
      const known = [...this.entries.keys()].join(', ') || 'none';
      throw new Error(`[${this.name}] unknown id "${id}". Registered: ${known}`);
    }
    return entry;
  }

  has(id: string): boolean {
    return this.entries.has(id);
  }

  list(): readonly T[] {
    return [...this.entries.values()];
  }

  filter(predicate: (entry: T) => boolean): readonly T[] {
    return this.list().filter(predicate);
  }

  /** Groups entries by a derived key, preserving registration order. */
  groupBy<K extends string>(key: (entry: T) => K): Map<K, T[]> {
    const groups = new Map<K, T[]>();
    for (const entry of this.entries.values()) {
      const group = key(entry);
      const bucket = groups.get(group);
      if (bucket) bucket.push(entry);
      else groups.set(group, [entry]);
    }
    return groups;
  }

  get size(): number {
    return this.entries.size;
  }

  onChange(handler: () => void): Unsubscribe {
    const offAdd = this.bus.on('registered', handler);
    const offRemove = this.bus.on('unregistered', handler);
    return () => {
      offAdd();
      offRemove();
    };
  }
}
