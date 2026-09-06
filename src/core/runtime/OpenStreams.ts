/**
 * The streams one surface has open, and the promise that closing the surface
 * closes them.
 *
 * `RuntimeClient.streamFrom` already does the right thing with an
 * `AbortSignal`: it cancels the reader on abort and on mid-stream error, and
 * correctly does not cancel a drained one. What was missing was one layer up
 * — **who owns the handle, and what happens to it when that owner goes away**.
 * The Ask panel kept its controllers in a bare `Map` in a `useRef`, called
 * `abort()` from exactly one place (the Stop button), and had an unmount
 * effect that reported *not running* without aborting anything. Closing the
 * panel mid-run therefore left the `fetch` open and the reader writing into a
 * dead component, while the toolbar retired the only button that could have
 * stopped it (install-experience ticket 07).
 *
 * A `Map` cannot hold that guarantee, because a `Map` has no idea anyone owns
 * it. An object can, and the guarantee is then one call rather than a rule
 * every future effect has to remember.
 *
 * **Held above the panel, not inside it** (`AppShell`), and this is the part
 * that took a second look. The obvious fix — abort in the panel's unmount
 * cleanup — is the one the panel's own comment had already recorded as
 * *tried and reverted*: React's development StrictMode mounts effects twice,
 * and the toolbar's Run opens the panel *and* starts a run from a mount
 * effect, so an abort-on-cleanup killed the very run the mount had started
 * ("Stopped by you" before a single node reported). An effect cleanup cannot
 * tell a close from a remount. A **gesture** can, and closing the panel is a
 * gesture. So the owner is the shell, the abort hangs off the toggle, and the
 * panel's unmount goes back to reporting rather than deciding.
 *
 * Deliberately in `core/`: it is framework-free — an `AbortController` and a
 * `Map` — and being framework-free is what makes this testable at all in this
 * repository, whose test environment is `node` with no DOM. A React component
 * cannot be mounted and unmounted here; this object can be aborted.
 *
 * Three rules, none of which a call site should have to know:
 *
 * - **`begin` twice under one id** replaces the first and aborts it. One turn
 *   has one stream; an orphaned controller is the failure this exists to
 *   prevent, so it must not be the price of a mistake.
 * - **`settle` is the `finally` half.** A stream that ended on its own is not
 *   something to abort later, and a stale entry makes a later Stop appear to
 *   act while doing nothing.
 * - **`abortAll` is reusable, not terminal.** The panel is a toggle: the same
 *   owner serves the next time it opens, and an object that could only ever
 *   be shut once would have to be rebuilt on a boolean.
 */
export class OpenStreams {
  private readonly open = new Map<string, AbortController>();

  /** How many streams are still open. */
  get size(): number {
    return this.open.size;
  }

  /** Whether anything is still running — the truthful form of the report the
   * panel's unmount used to make regardless. */
  get hasOpenStream(): boolean {
    return this.open.size > 0;
  }

  /**
   * Start a stream under `id` and get the signal to pass to the client.
   *
   * The caller never sees the controller, so it cannot hold one past the
   * owner's life or forget to register it — the two ways this went wrong.
   */
  begin(id: string): AbortSignal {
    const controller = new AbortController();
    this.open.get(id)?.abort();
    this.open.set(id, controller);
    return controller.signal;
  }

  /** This stream ended on its own; there is nothing left to abort. Safe on an
   * id that was never begun, because its caller is a `finally`. */
  settle(id: string): void {
    this.open.delete(id);
  }

  /** Stop one stream. `false` when there was nothing to stop — which is what
   * lets a caller tell "I stopped it" from "it had already ended". */
  abort(id: string): boolean {
    const controller = this.open.get(id);
    if (!controller) return false;
    this.open.delete(id);
    controller.abort();
    return true;
  }

  /** Stop everything still open — the surface that was showing them is going
   * away. Idempotent, and the object is usable again afterwards. */
  abortAll(): void {
    for (const controller of this.open.values()) controller.abort();
    this.open.clear();
  }
}
