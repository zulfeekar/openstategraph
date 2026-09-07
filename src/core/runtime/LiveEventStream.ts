import { runtimeBaseUrl } from './runtimeBaseUrl';

/**
 * The one long-lived connection a tab holds — `osg-agent-experience/71`.
 *
 * ## The budget, measured
 *
 * A browser allows **six concurrent HTTP/1.1 connections per origin**. An
 * editor tab spent two of them on `EventSource`s that live for the life of the
 * tab: `/api/events` for the catalogue and `/api/kanban/patrol/events` for the
 * job chip. `69` needed a third for the per-package watcher, and staging it on
 * 2026-09-05 against the running editor showed what that costs: with **two**
 * tabs on one workflow the budget was gone, the last stream opened sat at
 * `readyState 0` for minutes with `onopen` never firing, and an ordinary
 * `fetch('/api/workflows/<slug>/summary')` in that tab did not complete within
 * 45 seconds. Two tabs on one workflow is `69`'s own scenario, so `69` shipped
 * with the editor deliberately not opening its stream.
 *
 * HTTP/2 raises the limit to about a hundred and is **not** the answer: it is a
 * property of whatever proxy somebody put in front of the backend, and this
 * project ships proxy configs as examples. A fix that only works behind the
 * right deployment reads as intermittent.
 *
 * ## So: one socket, several subjects
 *
 * `GET /api/events` carries every live subject a surface asks for — the
 * catalogue always, and `patrol.status`, `kanban.changed` and one package's
 * `workflow.changed` on request. This class is the client half: **the only
 * place in shipped code that constructs an `EventSource`**, pinned by
 * `src/oneStreamPerTab.test.ts` so the next one is a red test rather than an
 * editor that degrades the moment somebody opens a second tab.
 *
 * Callers do not see the connection. They ask for a subject and get frames;
 * this reconciles the union of what everybody wants into one URL, and reopens
 * only when that URL actually changes — so the board opening (which adds
 * `kanban=1`) costs one reconnect, and a component re-rendering costs nothing.
 *
 * **The reconcile is deferred to a microtask on purpose.** React mounts its
 * effects in one commit, so the catalogue, the patrol chip and the open
 * package all subscribe within a tick; reconciling synchronously would open
 * three connections in a row to arrive at the one it wanted. Deferring
 * coalesces them into a single open. Nothing observable waits on it except the
 * connection itself — frames cannot arrive before it exists either way.
 *
 * **The sibling endpoints still exist and are still correct.** `69`'s
 * `/api/workflows/{slug}/events`, and both kanban streams, remain the right
 * door for a client that is not already holding a connection — the CLI, a
 * custom integration, anything with its budget to spend. It is *this* editor
 * that stops opening them.
 */

/** A subject the merged stream can carry. */
export type LiveTopic = 'catalogue' | 'patrol' | 'kanban' | 'workflow';

/**
 * The SSE `event:` name each subject arrives under.
 *
 * The names are the ones the sibling endpoints already send, unchanged: one
 * wire vocabulary, so a frame means the same thing wherever it is read. The
 * backend's `api/live_stream.py` holds the same table on its side and is the
 * source of truth for the contract; this is the client's reader for it.
 */
const FRAME_NAMES: Readonly<Record<LiveTopic, string>> = {
  catalogue: 'workflows.changed',
  patrol: 'patrol.status',
  kanban: 'kanban.changed',
  workflow: 'workflow.changed',
};

/** Just enough of `EventSource` to be faked in a test with no DOM. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

/** One caller's standing interest in one subject. */
interface Registration {
  readonly topic: LiveTopic;
  /** Only for `workflow`: which package this caller is editing. */
  readonly slug?: string;
  readonly onFrame: (record: Record<string, unknown>) => void;
}

export class LiveEventStream {
  private readonly registrations = new Set<Registration>();
  private source: EventSourceLike | null = null;
  private openUrl: string | null = null;
  private reconcileQueued = false;

  constructor(
    private readonly baseUrl: string = runtimeBaseUrl(),
    /**
     * `null` where `EventSource` does not exist — an old browser, a unit test
     * in Vitest's node environment. Every live update in this editor is an
     * improvement over a refetch that still happens, never a dependency, so
     * the honest degradation is a no-op subscription.
     */
    private readonly eventSourceImpl: EventSourceFactory | null = typeof EventSource === 'undefined'
      ? null
      : (url) => new EventSource(url),
  ) {}

  /**
   * Receive one subject until the returned function is called.
   *
   * The payload is handed over as the raw record the backend sent — parsing a
   * frame into a domain type is the caller's job, because the caller is the
   * one that owns that type. This class knows about connections and nothing
   * else.
   */
  subscribe(
    request: { topic: LiveTopic; slug?: string },
    onFrame: (record: Record<string, unknown>) => void,
  ): () => void {
    if (!this.eventSourceImpl) return () => {};
    const registration: Registration = {
      topic: request.topic,
      slug: request.slug,
      onFrame,
    };
    this.registrations.add(registration);
    this.queueReconcile();
    return () => {
      this.registrations.delete(registration);
      this.queueReconcile();
    };
  }

  /**
   * Which URL the current interests add up to — exported for the test that
   * proves the board opening changes it and a re-render does not.
   */
  wantedUrl(): string | null {
    if (this.registrations.size === 0) return null;
    const parameters = new URLSearchParams();
    let wantsPatrol = false;
    let wantsKanban = false;
    const slugs = new Set<string>();
    for (const registration of this.registrations) {
      if (registration.topic === 'patrol') wantsPatrol = true;
      if (registration.topic === 'kanban') wantsKanban = true;
      if (registration.topic === 'workflow' && registration.slug) slugs.add(registration.slug);
    }
    if (wantsPatrol) parameters.set('patrol', '1');
    if (wantsKanban) parameters.set('kanban', '1');
    // **One slug, deliberately.** A tab edits one package at a time — the
    // open slug is a single value in `sessionStorage` — so a second one here
    // means two callers disagree about what is open, and the first sorted
    // wins rather than the last mount. A repeated parameter would be a wider
    // contract for a case the editor cannot produce, and the backend's
    // per-slug cost model is what would pay for it.
    const slug = [...slugs].sort()[0];
    if (slug) parameters.set('slug', slug);
    const query = parameters.toString();
    // Built in two steps rather than with a conditional inside the template:
    // `contractDrift.test.ts` reads the paths this client calls straight out
    // of the source, and a `?` inside the literal ends the path it can see.
    const suffix = query ? `?${query}` : '';
    return `${this.baseUrl}/api/events${suffix}`;
  }

  private queueReconcile(): void {
    if (this.reconcileQueued) return;
    this.reconcileQueued = true;
    void Promise.resolve().then(() => {
      this.reconcileQueued = false;
      this.reconcile();
    });
  }

  private reconcile(): void {
    const wanted = this.wantedUrl();
    if (wanted === this.openUrl) return;
    this.source?.close();
    this.source = null;
    this.openUrl = null;
    if (!wanted || !this.eventSourceImpl) return;
    const source = this.eventSourceImpl(wanted);
    this.source = source;
    this.openUrl = wanted;
    for (const topic of Object.keys(FRAME_NAMES) as LiveTopic[]) {
      source.addEventListener(FRAME_NAMES[topic], (event) => {
        this.deliver(topic, event);
      });
    }
  }

  private deliver(topic: LiveTopic, event: MessageEvent): void {
    let record: Record<string, unknown>;
    try {
      record = JSON.parse(event.data as string) as Record<string, unknown>;
    } catch {
      // One unparseable frame is not a reason to tear the stream down — the
      // next is very likely fine, and every listener refetches regardless.
      // The rule `watchCatalogue` established, now in one place for all four
      // subjects rather than restated at each door.
      return;
    }
    for (const registration of [...this.registrations]) {
      if (registration.topic !== topic) continue;
      // The server already filters `workflow.changed` by the slug this
      // connection named. This covers the window between a caller changing
      // slug and the reconnect completing, where a frame about the previous
      // package is still in flight.
      if (topic === 'workflow' && registration.slug && record['slug'] !== registration.slug) {
        continue;
      }
      registration.onFrame(record);
    }
  }
}

/**
 * The tab's connection.
 *
 * A module singleton rather than one per client object, because the thing
 * being shared is a **browser resource** — there is one connection budget per
 * origin and this holds the editor's whole share of it. Two `RuntimeClient`s
 * and a `WorkflowFileClient` are ordinary objects a component may make freely;
 * they must not each own a socket, which is the defect this ticket is about.
 *
 * Framework-free, like everything in `core/`: no React, no JointJS, and
 * nothing here knows a component exists.
 */
export const liveEvents = new LiveEventStream();
