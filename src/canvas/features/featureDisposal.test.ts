import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { makeWorkbench } from '@core/testing/fixtures';
import { createDefaultFeatures } from './defaultFeatures';
import type { IPaperFeature, PaperFeatureContext } from './IPaperFeature';

/**
 * `IPaperFeature`'s stated invariant, as a test:
 *
 * > Every feature must undo everything it installed on `dispose` — a canvas
 * > gets torn down and rebuilt whenever the document is replaced.
 *
 * It was prose for as long as it was true, and stopped being true the day a
 * `container.addEventListener('pointerdown', …)` landed in `SelectionFeature`
 * beside four `this.onDom` calls on the same element. The audit of 2026-08-15
 * measured one residual listener per install/dispose cycle — 100 cycles, 100
 * listeners, each closure retaining `controller`, `viewport` and `paper`,
 * i.e. the whole disposed canvas, because the container is the React-owned
 * stage div that `PaperController` deliberately leaves intact. `PanZoomFeature`
 * was flat at 0, which is how the audit knew it was one line rather than a
 * pattern.
 *
 * So this counts, rather than asserting about the one line: every feature in
 * the *production* list (`createDefaultFeatures`), every registration channel
 * a feature has (DOM on the container, on `window`, on `document`; JointJS
 * events on the paper and on the graph), zero residual after N cycles. A
 * feature added tomorrow is covered by being in that list.
 */

interface Registration {
  readonly type: string;
  readonly handler: unknown;
  readonly capture: boolean;
}

function captureOf(options?: boolean | AddEventListenerOptions): boolean {
  return typeof options === 'boolean' ? options : (options?.capture ?? false);
}

/** An `EventTarget` that remembers what is still attached to it. */
class CountingTarget implements EventTarget {
  readonly live: Registration[] = [];
  added = 0;
  removed = 0;

  addEventListener(
    type: string,
    handler: EventListenerOrEventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ): void {
    this.added += 1;
    this.live.push({ type, handler, capture: captureOf(options) });
  }

  removeEventListener(
    type: string,
    handler: EventListenerOrEventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ): void {
    const capture = captureOf(options);
    const at = this.live.findIndex(
      (entry) => entry.type === type && entry.handler === handler && entry.capture === capture,
    );
    if (at < 0) return;
    this.live.splice(at, 1);
    this.removed += 1;
  }

  dispatchEvent(): boolean {
    return true;
  }
}

/** The `on`/`off` half of a JointJS paper or graph, counted the same way. */
class CountingEmitter {
  readonly live: Registration[] = [];
  added = 0;
  removed = 0;

  on(type: string, handler: unknown): void {
    this.added += 1;
    this.live.push({ type, handler, capture: false });
  }

  off(type: string, handler: unknown): void {
    const at = this.live.findIndex((entry) => entry.type === type && entry.handler === handler);
    if (at < 0) return;
    this.live.splice(at, 1);
    this.removed += 1;
  }
}

/** What both counters expose: what is still attached, and the running ledger. */
interface Counted {
  readonly live: Registration[];
  readonly added: number;
  readonly removed: number;
}

interface Harness {
  readonly ctx: PaperFeatureContext;
  readonly targets: readonly { readonly name: string; readonly counter: Counted }[];
}

function harness(): Harness {
  const workbench = makeWorkbench();
  const container = new CountingTarget();
  const paper = Object.assign(new CountingEmitter(), {
    el: {},
    model: { getElements: () => [], getLinks: () => [] },
  });
  const graph = Object.assign(new CountingEmitter(), {
    getElements: () => [],
    getLinks: () => [],
  });

  const ctx = {
    paper,
    graph,
    adapter: { isApplying: false },
    controller: workbench.controller,
    viewport: {
      zoom: 1,
      translate: { x: 0, y: 0 },
      visibleRect: { x: 0, y: 0, width: 100, height: 100 },
      fit: () => {},
      onChange: () => () => {},
    },
    container,
  } as unknown as PaperFeatureContext;

  return {
    ctx,
    targets: [
      { name: 'container', counter: container },
      { name: 'paper', counter: paper },
      { name: 'graph', counter: graph },
      { name: 'window', counter: globalThis.window as unknown as CountingTarget },
      { name: 'document', counter: globalThis.document as unknown as CountingTarget },
    ],
  };
}

/** Features reach for these as bare globals; the node environment has neither. */
const GLOBALS = ['window', 'document'] as const;
const saved = new Map<string, unknown>();

beforeEach(() => {
  for (const name of GLOBALS) {
    saved.set(name, (globalThis as Record<string, unknown>)[name]);
    (globalThis as Record<string, unknown>)[name] = new CountingTarget();
  }
});

afterEach(() => {
  for (const name of GLOBALS) {
    const before = saved.get(name);
    if (before === undefined) delete (globalThis as Record<string, unknown>)[name];
    else (globalThis as Record<string, unknown>)[name] = before;
  }
});

const CYCLES = 100;

/** Only the targets still holding something, so a failure names the channel. */
function residuals(h: Harness): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const target of h.targets) {
    if (target.counter.live.length > 0) counts[target.name] = target.counter.live.length;
  }
  return counts;
}

/** The audit's added/removed columns: a leak shows as an unbalanced ledger. */
function ledger(h: Harness): Record<string, string> {
  const totals: Record<string, string> = {};
  for (const target of h.targets) {
    const { added, removed } = target.counter;
    if (added > 0) totals[target.name] = `${added}/${removed}`;
  }
  return totals;
}

describe('every canvas feature undoes what it installed', () => {
  const features = createDefaultFeatures().all;

  it('installs a list the test can actually enumerate', () => {
    // Guards the seam this test depends on: if the default list is ever
    // inlined back into `PaperController`, everything below silently stops
    // covering the features it stopped seeing.
    expect(features.length).toBeGreaterThan(0);
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
  });

  it.each(features.map((feature) => [feature.id, feature] as const))(
    `%s leaves nothing attached after ${CYCLES} install/dispose cycles`,
    (_id: string, feature: IPaperFeature) => {
      const h = harness();
      for (let i = 0; i < CYCLES; i += 1) {
        feature.install(h.ctx);
        feature.dispose();
      }
      expect(residuals(h)).toEqual({});
      // Same fact from the other side — `500 / 400` is what the audit saw.
      for (const [name, counts] of Object.entries(ledger(h))) {
        const [added, removed] = counts.split('/');
        expect(removed, `${name} removed fewer than it added`).toBe(added);
      }
    },
  );
});
