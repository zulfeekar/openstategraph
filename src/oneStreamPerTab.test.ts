import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { LiveEventStream, type EventSourceLike } from '@core/runtime/LiveEventStream';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';

/**
 * One long-lived connection per tab — `osg-agent-experience/71`.
 *
 * ## Why a census and not a comment
 *
 * A browser allows **six concurrent HTTP/1.1 connections per origin**, and an
 * editor tab spent one per live subject: `/api/events` for the catalogue,
 * `/api/kanban/patrol/events` for the job chip, `/api/kanban/events` while a
 * board was open, and `69`'s per-package watcher would have been a fourth.
 * Staged on 2026-09-05 against the running editor with three: **two** tabs on
 * one workflow saturated the budget, the last `EventSource` opened sat at
 * `readyState 0` for minutes with `onopen` never firing, and an ordinary
 * `fetch('/api/workflows/<slug>/summary')` in that tab did not complete within
 * 45 seconds — so the five-second file watch, which is what tells a tab its
 * package was deleted, stopped answering too.
 *
 * Nothing was disobeyed to get there. Each stream was added for a good reason,
 * each was correct on its own, and no instrument could say *this tab now holds
 * three sockets and the next one degrades it*. That is `CLAUDE.md`'s own
 * lesson about a ceiling nobody measures, on a resource the browser owns
 * rather than one this codebase does.
 *
 * So the door is counted, the way
 * `backend/tests/test_a_runs_diagram_opens_its_mounts.py` counts
 * `draw_mermaid()` call sites: **exactly one shipped module may construct an
 * `EventSource`**, and a second one is a red test rather than an editor that
 * gets quietly worse the moment somebody opens a second tab.
 *
 * ## And the count in the browser, not only in the source
 *
 * A source census sees a door; it cannot see how many connections a tab
 * actually opens, because that is a question about how many *subjects* end up
 * on one URL. So the second half drives the real client objects — the ones
 * `AppShell` mounts — through one stream and counts the sockets it built.
 *
 * The sibling endpoints are untouched and still correct: `69`'s
 * `/api/workflows/{slug}/events` and both kanban streams remain the right door
 * for a client with connections to spare (the CLI, a custom integration). It
 * is this editor that stops opening them, which is why this file measures the
 * editor and not the backend.
 */

const SRC = fileURLToPath(new URL('.', import.meta.url));
const SKIPPED = new Set(['node_modules', 'dist', '__pycache__']);

/** Every shipped module — a test is not shipped and cannot cost a tab a socket. */
function shippedModules(dir = SRC, prefix = ''): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIPPED.has(entry.name)) {
        found.push(...shippedModules(`${dir}/${entry.name}`, `${prefix}${entry.name}/`));
      }
    } else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) {
      found.push(`${prefix}${entry.name}`);
    }
  }
  return found;
}

describe('the doors a tab opens', () => {
  it('has exactly one, and it is the shared stream', () => {
    const opening = shippedModules().filter((path) =>
      readFileSync(`${SRC}${path}`, 'utf8').includes('new EventSource('),
    );

    expect(
      opening,
      'Every live subject rides the one connection `LiveEventStream` owns. A second ' +
        '`EventSource` costs every tab another of the six the browser allows, and two ' +
        'tabs on one workflow is where that was measured to fail (osg-agent-experience/71).',
    ).toEqual(['core/runtime/LiveEventStream.ts']);
  });

  it('names the census over something rather than nothing', () => {
    // Anti-vacuity: a walker that found no modules would make the assertion
    // above a statement about an empty list, which is the shape of a pin that
    // passes for the wrong reason.
    expect(shippedModules().length).toBeGreaterThan(200);
    expect(shippedModules()).toContain('core/runtime/LiveEventStream.ts');
  });
});

describe('what the app shell subscribes to', () => {
  /** A stand-in for `EventSource`, counting every construction. */
  const counting = () => {
    const urls: string[] = [];
    const listeners = new Map<string, (event: MessageEvent) => void>();
    const sources: { closed: boolean }[] = [];
    const impl = (url: string): EventSourceLike => {
      urls.push(url);
      const self = { closed: false };
      sources.push(self);
      return {
        addEventListener: (type: string, listener: (event: MessageEvent) => void) =>
          listeners.set(type, listener),
        close: () => {
          self.closed = true;
        },
      };
    };
    return { urls, sources, listeners, impl };
  };

  /** The stream reconciles on a microtask — see `LiveEventStream`. */
  const settled = () => Promise.resolve().then(() => {});

  it('holds one connection for all four subjects', async () => {
    const fake = counting();
    const live = new LiveEventStream('http://rt', fake.impl);
    const runtime = new RuntimeClient(
      'http://rt',
      () => Promise.reject(new Error('unused')),
      () => '',
      live,
    );
    const files = new WorkflowFileClient(
      'http://rt',
      () => Promise.reject(new Error('unused')),
      live,
    );

    // Exactly what `AppShell` mounts, in the order it mounts it.
    files.watchCatalogue(() => {});
    runtime.watchPatrolEvents(() => {});
    files.watchWorkflow('billing', () => {});
    const stopBoard = runtime.watchKanbanEvents(() => {});
    await settled();

    expect(fake.urls).toEqual(['http://rt/api/events?patrol=1&kanban=1&slug=billing']);
    expect(fake.sources.filter((source) => !source.closed)).toHaveLength(1);

    // Closing the board drops its subject rather than a connection: one
    // reconnect, still one socket, and the backend stops polling the store.
    stopBoard();
    await settled();

    expect(fake.urls).toEqual([
      'http://rt/api/events?patrol=1&kanban=1&slug=billing',
      'http://rt/api/events?patrol=1&slug=billing',
    ]);
    expect(fake.sources.filter((source) => !source.closed)).toHaveLength(1);
  });

  it('opens nothing until somebody asks, and lets go when nobody does', async () => {
    const fake = counting();
    const live = new LiveEventStream('http://rt', fake.impl);

    await settled();
    expect(fake.urls).toEqual([]);

    const stop = live.subscribe({ topic: 'catalogue' }, () => {});
    await settled();
    expect(fake.urls).toEqual(['http://rt/api/events']);

    stop();
    await settled();
    expect(fake.sources.every((source) => source.closed)).toBe(true);
  });

  it('coalesces a commit’s worth of subscriptions into one open', async () => {
    // The reason the reconcile is deferred: React mounts its effects in one
    // commit, so reconciling synchronously would open three connections on
    // the way to the one it wanted — three server-side subscriptions, three
    // of the browser's six, for a tab that ends up holding one.
    const fake = counting();
    const live = new LiveEventStream('http://rt', fake.impl);

    live.subscribe({ topic: 'catalogue' }, () => {});
    live.subscribe({ topic: 'patrol' }, () => {});
    live.subscribe({ topic: 'workflow', slug: 'billing' }, () => {});
    await settled();

    expect(fake.urls).toHaveLength(1);
  });
});
