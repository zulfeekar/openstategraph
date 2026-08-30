import type { RunLane } from '../ask/timeline';

/**
 * The replay transport: a playhead over a run that has already happened.
 *
 * `memory-and-replay` 52. **Replay is a profiler, not a re-run** — the map's
 * own words, *"reading history, not spending money re-executing it."* Nothing
 * here calls a model, opens a stream or touches a checkpoint; it moves a
 * number between `0` and the recording's own `totalMs` and lets the chart
 * decide what has been reached.
 *
 * That distinction has to be written down because **LangGraph uses the word
 * for the other thing**. Confirmed on the `docs-langchain` MCP server,
 * 2026-08-29 (`/oss/python/langgraph/use-time-travel`): its *replay*
 * re-executes nodes, fires the LLM calls again, and produces a *different*
 * run. So its time travel gives this feature nothing for free, and a reader
 * arriving from those docs must not find the word meaning two things here.
 * `CLAUDE.md`'s user-facing lexicon now carries both rows, and
 * `replayIsNotRerun.test.ts` pins the copy.
 *
 * # What this claims about time, and what it refuses to
 *
 * - **It claims real offsets.** Every stop below is a server-side `elapsedMs`
 *   (`memory-and-replay` 46), minted where the frame was built, and `47`
 *   stored them. A gap between two stops is a real stall with a node named on
 *   both sides.
 * - **It does not claim absolute time.** The axis is milliseconds since the
 *   stream opened. It is not a wall clock and never carries a timestamp.
 * - **It does not claim to be what the user experienced.** That is the
 *   browser's arrival clock — a different question, still measured, still on
 *   the Inspector's badge, and deliberately not this.
 * - **It does not exist at all without an end.** `offered` is false for a run
 *   in flight and for a recording with no clock: *"a slider that cannot reach
 *   its right-hand edge is lying about what it can do."* A run with no bursts
 *   is therefore drawn as a run nobody timed, never as an instant one.
 *
 * Framework-free, and a module singleton for the same reason `runView` is one:
 * the writer is the shell's binding table and the reader is a panel that is
 * mounted and unmounted independently of it.
 */
export interface TransportState {
  readonly playing: boolean;
  /** Where the playhead is, in ms on the run's own clock. */
  readonly atMs: number;
  /** Playback rate. `1` is the run's real speed. */
  readonly rate: number;
  /**
   * The stops `Step` moves between, ascending — **frame offsets, not seconds**.
   *
   * The owner settled the unit: *"the useful unit is what happened next, and a
   * 10-second model call is one thing happening."* Stepping by a second would
   * cost ten presses to cross one event and would invent a granularity the
   * recording does not have.
   */
  readonly stops: readonly number[];
  /** The recording's end. `null` while a run is live or unclocked. */
  readonly totalMs: number | null;
}

/** The rates offered. Three, because a fourth button is width and not a choice. */
export const REPLAY_SPEEDS: readonly number[] = [1, 2, 8];

const EMPTY: TransportState = { playing: false, atMs: 0, rate: 1, stops: [], totalMs: null };

/**
 * Every dated end of every bar and every lane, ascending and deduplicated.
 *
 * Both ends of each bar, not just the starts: the end of a run's last model
 * call is a moment a reader wants to land on, and it is the start of nothing.
 * `null` offsets contribute nothing rather than a zero — a bar the run never
 * timed is not a bar at `0 ms`.
 */
export function stopsOf(lanes: readonly RunLane[], totalMs: number | null): readonly number[] {
  const seen = new Set<number>([0]);
  for (const lane of lanes) {
    if (lane.startMs !== null) seen.add(lane.startMs);
    if (lane.endMs !== null) seen.add(lane.endMs);
    for (const step of lane.steps) {
      if (step.startMs === null) continue;
      seen.add(step.startMs);
      if (step.durationMs !== null) seen.add(step.startMs + step.durationMs);
    }
  }
  if (totalMs !== null) seen.add(totalMs);
  return [...seen].filter((at) => totalMs === null || at <= totalMs).sort((a, b) => a - b);
}

/** The next stop strictly after `at`, or the end. */
export function nextStop(stops: readonly number[], at: number, totalMs: number | null): number {
  return stops.find((stop) => stop > at + EPSILON) ?? totalMs ?? at;
}

/** The last stop strictly before `at`, or zero. */
export function previousStop(stops: readonly number[], at: number): number {
  return [...stops].reverse().find((stop) => stop < at - EPSILON) ?? 0;
}

/**
 * Whether a transport may be offered at all.
 *
 * Two refusals and they are different refusals. A **live** run has no end to
 * scrub to. An **unclocked** recording has no axis: `108`'s rule at the level
 * of the whole control — an axis with no measurements is not a slow axis, and
 * a scrubber over it would invite a reader to point at times nobody measured.
 */
export function transportOffered(running: boolean, totalMs: number | null): boolean {
  return !running && totalMs !== null && totalMs > 0;
}

/** Guards a float comparison over offsets that are whole milliseconds. */
const EPSILON = 0.5;

export class ReplayTransport {
  #state: TransportState = EMPTY;
  readonly #listeners = new Set<() => void>();

  read(): TransportState {
    return this.#state;
  }

  subscribe(listener: () => void): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }

  /**
   * Point the transport at a recording.
   *
   * Silent when the stops are unchanged, so the chart's per-frame re-render
   * during a live run does not restart the playhead sixty times a second. A
   * *different* recording rewinds to zero and stops playing, because a
   * playhead left at 14 s over a run that is now 3 s long is a control
   * pointing at nothing.
   */
  attach(stops: readonly number[], totalMs: number | null): void {
    const held = this.#state;
    if (held.totalMs === totalMs && sameStops(held.stops, stops)) return;
    this.#set({ ...held, stops, totalMs, atMs: 0, playing: false });
  }

  /** Play, or pause. **Never called on open** — there is no autoplay here. */
  toggle(): void {
    const at = this.#state;
    if (at.totalMs === null) return;
    this.#set({ ...at, playing: !at.playing, atMs: at.atMs >= at.totalMs ? 0 : at.atMs });
  }

  restart(): void {
    this.#set({ ...this.#state, atMs: 0, playing: false });
  }

  /** One frame forward, then stop — stepping is reading, not watching. */
  stepForward(): void {
    const at = this.#state;
    this.#set({ ...at, atMs: nextStop(at.stops, at.atMs, at.totalMs), playing: false });
  }

  stepBack(): void {
    const at = this.#state;
    this.#set({ ...at, atMs: previousStop(at.stops, at.atMs), playing: false });
  }

  setRate(rate: number): void {
    this.#set({ ...this.#state, rate });
  }

  /**
   * Move the playhead, clamped to the recording.
   *
   * `playing` is a parameter rather than always false because the rAF loop
   * seeks on every frame; a drag passes `false` and stops the film, which is
   * what pointing at something means.
   */
  seek(atMs: number, playing = false): void {
    const at = this.#state;
    const end = at.totalMs ?? 0;
    this.#set({ ...at, atMs: Math.max(0, Math.min(end, atMs)), playing });
  }

  #set(next: TransportState): void {
    this.#state = next;
    for (const listener of [...this.#listeners]) listener();
  }
}

function sameStops(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/** The one this tab uses — see the note on `runView` for why it is a singleton. */
export const replayTransport = new ReplayTransport();
