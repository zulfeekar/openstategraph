/**
 * Anything that installs listeners, timers or DOM nodes must be able to
 * take them all back down again. Canvas features, controllers and running
 * executions all implement this so the app has exactly one teardown idiom.
 */
export interface IDisposable {
  dispose(): void;
}

export type Unsubscribe = () => void;

/**
 * Collects disposables and tears them down in reverse order — the same
 * order a stack of `try/finally` blocks would unwind in, which matters
 * when a later subscription depends on an earlier one still existing.
 */
export class DisposableStore implements IDisposable {
  private readonly items: IDisposable[] = [];
  private disposed = false;

  /** Adds a disposable and returns it, so calls can be inlined. */
  add<T extends IDisposable>(item: T): T {
    if (this.disposed) {
      // Adding to a disposed store almost always means a lifecycle bug;
      // dispose immediately rather than leak silently.
      item.dispose();
      return item;
    }
    this.items.push(item);
    return item;
  }

  /** Adapts a bare unsubscribe function into the store. */
  addFn(fn: Unsubscribe): void {
    this.add({ dispose: fn });
  }

  /** Adds a DOM listener that is removed on dispose. */
  addListener<K extends keyof WindowEventMap>(
    target: Window,
    type: K,
    listener: (event: WindowEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ): void;
  addListener<K extends keyof DocumentEventMap>(
    target: Document,
    type: K,
    listener: (event: DocumentEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ): void;
  addListener<K extends keyof HTMLElementEventMap>(
    target: HTMLElement,
    type: K,
    listener: (event: HTMLElementEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ): void;
  addListener(
    target: EventTarget,
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: AddEventListenerOptions,
  ): void {
    target.addEventListener(type, listener, options);
    this.addFn(() => target.removeEventListener(type, listener, options));
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (let i = this.items.length - 1; i >= 0; i -= 1) {
      try {
        this.items[i]?.dispose();
      } catch (error) {
        // One broken teardown must not orphan the rest.
        console.error('[dyflow] dispose failed', error);
      }
    }
    this.items.length = 0;
  }
}
