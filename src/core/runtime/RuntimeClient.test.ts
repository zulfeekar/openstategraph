import { describe, expect, it, vi } from 'vitest';
import { RuntimeClient, isCancelled, type FetchLike, type RunStreamEvent } from './RuntimeClient';

/**
 * The editor's route to the runtime.
 *
 * Every case here is an error path, and that is deliberate: the happy path is one
 * `fetch` and a cast, while the failures are what a developer actually meets — a
 * backend that is not running, no model configured, a workflow the server
 * rejects, a graph that blows up mid-run. Each has a different fix, so each needs
 * a different message.
 */

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

const stubFetch = (response: Response): { fetch: FetchLike; calls: string[]; bodies: string[] } => {
  const calls: string[] = [];
  const bodies: string[] = [];
  const fetchImpl: FetchLike = (url, init) => {
    calls.push(url);
    if (typeof init?.body === 'string') bodies.push(init.body);
    // Cloned so one stub can serve several calls — a `Response` body is a
    // single-use stream.
    return Promise.resolve(response.clone());
  };
  return { fetch: fetchImpl, calls, bodies };
};

const GOOD = {
  answer: 'Rock earns the most, at 826.65.',
  decisions: { 'node:route.grader-1': 'pass' },
  outputs: { 'node:agent.llm-1': 'Rock' },
  attempts: 2,
  mermaid: 'graph TD;',
  warnings: [],
};

describe('RuntimeClient.run', () => {
  it('posts the workflow and the question', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    const client = new RuntimeClient('http://rt', stub.fetch);

    await client.run({ workflow: { nodes: [], edges: [] }, question: 'Which genre?' });

    expect(stub.calls[0]).toBe('http://rt/api/runs');
    const sent = JSON.parse(stub.bodies[0]!) as Record<string, unknown>;
    expect(sent['question']).toBe('Which genre?');
    expect(sent['workflow']).toEqual({ nodes: [], edges: [] });
  });

  it('returns the answer, decisions and per-node outputs', async () => {
    const client = new RuntimeClient('http://rt', stubFetch(jsonResponse(GOOD)).fetch);
    const result = await client.run({ workflow: {}, question: 'q' });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.answer).toContain('826.65');
    // Decisions and outputs are what let the canvas highlight the path that ran.
    expect(result.value.decisions['node:route.grader-1']).toBe('pass');
    expect(result.value.outputs['node:agent.llm-1']).toBe('Rock');
    expect(result.value.attempts).toBe(2);
  });

  it('sends the recursion limit under the key the server expects', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    await new RuntimeClient('http://rt', stub.fetch).run({
      workflow: {},
      question: 'q',
      recursionLimit: 42,
    });

    // snake_case at the boundary. Sending `recursionLimit` would be silently
    // ignored by FastAPI's model and the default used instead.
    const sent = JSON.parse(stub.bodies[0]!) as Record<string, unknown>;
    expect(sent['recursion_limit']).toBe(42);
  });

  it('sends the workflow slug under the key the server expects', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    await new RuntimeClient('http://rt', stub.fetch).run({
      workflow: {},
      question: 'q',
      workflowSlug: 'chinook-assistant',
    });

    // The backend layers that workflow's own tools over its defaults; a
    // camelCase key would be silently dropped by FastAPI and the run would
    // bind no workflow tools — the agent then answers from memory.
    const sent = JSON.parse(stub.bodies[0]!) as Record<string, unknown>;
    expect(sent['workflow_slug']).toBe('chinook-assistant');
  });

  it('omits the slug when none is known — the field is optional server-side', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    await new RuntimeClient('http://rt', stub.fetch).run({ workflow: {}, question: 'q' });
    expect(JSON.parse(stub.bodies[0]!)).not.toHaveProperty('workflow_slug');
  });

  it('declares the audience only when the caller names one', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    const client = new RuntimeClient('http://rt', stub.fetch);
    await client.run({ workflow: {}, question: 'q', audience: 'developer' });
    await client.run({ workflow: {}, question: 'q' });

    // Omitted rather than sent as `'customer'`, because the backend already
    // defaults to `customer` and the safe value should be the one nobody has
    // to remember to send. Nothing can opt in by accident.
    expect(JSON.parse(stub.bodies[0]!)).toHaveProperty('audience', 'developer');
    expect(JSON.parse(stub.bodies[1]!)).not.toHaveProperty('audience');
  });

  it('reports no developer channel when the run was a customer run', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    const result = await new RuntimeClient('http://rt', stub.fetch).run({
      workflow: {},
      question: 'q',
    });

    // `null`, not an empty channel: "this run was not entitled to one" is a
    // different fact from "there was nothing to report", and a UI that
    // conflated them would claim an all-clear the payload never gave.
    expect(result.ok && result.value.developer).toBeNull();
    expect(result.ok && result.value.warnings).toEqual([]);
  });

  it('reads warnings and the suggestion off the developer channel', async () => {
    const stub = stubFetch(
      jsonResponse({
        ...GOOD,
        developer: { warnings: ['no tool'], suggestion: { nodeType: 'tool.web-search' } },
      }),
    );
    const result = await new RuntimeClient('http://rt', stub.fetch).run({
      workflow: {},
      question: 'q',
      audience: 'developer',
    });

    expect(result.ok && result.value.warnings).toEqual(['no tool']);
    expect(result.ok && result.value.developer?.suggestion).toEqual({
      nodeType: 'tool.web-search',
    });
  });

  it('omits the model when none is chosen, so the server decides', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    await new RuntimeClient('http://rt', stub.fetch).run({ workflow: {}, question: 'q' });

    // Sending `model: undefined` would serialise to nothing, but sending
    // `model: null` would be rejected — omitting is the only safe form.
    expect(JSON.parse(stub.bodies[0]!)).not.toHaveProperty('model');
  });

  describe('failures each get an actionable message', () => {
    it('names the address when the backend is not running', async () => {
      const client = new RuntimeClient('http://rt', () => Promise.reject(new Error('nope')));
      const result = await client.run({ workflow: {}, question: 'q' });

      expect(result.ok).toBe(false);
      if (result.ok) return;
      // The most common development failure by far, so it gets the message that
      // actually helps rather than a bare "Failed to fetch".
      expect(result.error).toContain('http://rt');
      expect(result.error).toMatch(/backend running/i);
    });

    it('passes through the server’s explanation when no model is configured', async () => {
      const detail = 'No model configured. Set ANTHROPIC_API_KEY or…';
      const client = new RuntimeClient('http://rt', stubFetch(jsonResponse({ detail }, 503)).fetch);
      const result = await client.run({ workflow: {}, question: 'q' });

      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error).toBe(detail);
    });

    it('summarises a validation error rather than dumping its structure', async () => {
      // FastAPI's 422 detail is an array of field errors; pasted raw into a
      // toast it is unreadable.
      const body = { detail: [{ msg: 'question is too short' }, { msg: 'workflow required' }] };
      const client = new RuntimeClient('http://rt', stubFetch(jsonResponse(body, 422)).fetch);
      const result = await client.run({ workflow: {}, question: '' });

      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error).toBe('question is too short; workflow required');
    });

    it('reports a run that failed mid-graph', async () => {
      const client = new RuntimeClient(
        'http://rt',
        stubFetch(jsonResponse({ detail: 'ValueError: bad node' }, 502)).fetch,
      );
      const result = await client.run({ workflow: {}, question: 'q' });
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error).toContain('bad node');
    });

    it('marks a provider 5xx as transient rather than blaming the workflow', async () => {
      const detail = 'ResponseError: Internal Server Error (status code: 500)';
      const client = new RuntimeClient('http://rt', stubFetch(jsonResponse({ detail }, 502)).fetch);
      const result = await client.run({ workflow: {}, question: 'q' });

      expect(result.ok).toBe(false);
      if (result.ok) return;
      // Seen for real from Ollama cloud on a request that succeeded next try.
      // Surfacing the raw string implied the workflow was broken when it was not.
      expect(result.error).toMatch(/transient/i);
      expect(result.error).toContain(detail);
    });

    it('still reports a genuine workflow failure plainly', async () => {
      const client = new RuntimeClient(
        'http://rt',
        stubFetch(jsonResponse({ detail: 'KeyError: prompt' }, 502)).fetch,
      );
      const result = await client.run({ workflow: {}, question: 'q' });
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error).toBe('KeyError: prompt');
    });

    it('falls back to the status when the body carries no detail', async () => {
      const client = new RuntimeClient(
        'http://rt',
        stubFetch(new Response('', { status: 500 })).fetch,
      );
      const result = await client.run({ workflow: {}, question: 'q' });
      expect(result.ok).toBe(false);
      if (result.ok) return;
      expect(result.error).toContain('500');
    });

    it('does not throw on a malformed success body', async () => {
      const client = new RuntimeClient('http://rt', stubFetch(new Response('not json')).fetch);
      const result = await client.run({ workflow: {}, question: 'q' });
      // A 200 with a broken body is a bug on the server; the editor should say
      // so rather than crash the panel.
      expect(result.ok).toBe(false);
    });

    it('tolerates missing fields in an otherwise valid response', async () => {
      const client = new RuntimeClient('http://rt', stubFetch(jsonResponse({})).fetch);
      const result = await client.run({ workflow: {}, question: 'q' });

      expect(result.ok).toBe(true);
      if (!result.ok) return;
      // Defaults rather than undefined, so the UI never has to guard.
      expect(result.value.answer).toBe('');
      expect(result.value.decisions).toEqual({});
      expect(result.value.warnings).toEqual([]);
    });
  });
});

/** Builds an SSE body from `(event, data)` pairs, exactly as the backend frames them. */
const sseBody = (frames: readonly [string, Record<string, unknown>][]): string =>
  frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('');

/**
 * A streamed `Response` whose body arrives across two chunks, split
 * mid-frame — the case a naive line-by-line parser gets wrong, and exactly
 * what a real network read can do regardless of how the server wrote it.
 */
const streamedResponse = (text: string, splitAt: number): Response => {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(text);
  const first = bytes.slice(0, splitAt);
  const second = bytes.slice(splitAt);
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(first);
      controller.enqueue(second);
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
};

describe('RuntimeClient.runStream', () => {
  const FRAMES: [string, Record<string, unknown>][] = [
    ['update', { node: 'node:input.text-1', namespace: [], taskId: null, output: 'hello' }],
    [
      'update',
      { node: 'node:orchestrate.worker-1', namespace: [], taskId: 'task-1', output: null },
    ],
    ['token', { node: 'node:agent.llm-1', namespace: [], content: 'Ro' }],
    ['token', { node: 'node:agent.llm-1', namespace: [], content: 'ck' }],
    [
      'done',
      {
        answer: 'Rock earns the most.',
        decisions: { 'node:route.grader-1': 'pass' },
        outputs: { 'node:input.text-1': 'hello' },
        attempts: 1,
        mermaid: 'graph TD;',
        warnings: [],
      },
    ],
  ];

  /**
   * The body contract, asserted on the door the product opens.
   *
   * Every one of these was covered on `run()` — which has **no product caller
   * at all** — while `runStream`, which both shipped UIs use, asserted only
   * `thread_id` (reviews-2026-08-14 ticket 02). Dropping `workflow_slug` or
   * `audience` from the stream body cost the editor its tool registry or its
   * developer channel, and left the suite green.
   *
   * Both doors now share `runBody`, so these hold for `run` and `resume` too;
   * they live here because this is the one a user's keystroke reaches.
   */
  const bodySentBy = async (
    request: Parameters<RuntimeClient['runStream']>[0],
  ): Promise<Record<string, unknown>> => {
    let sent = '';
    const client = new RuntimeClient('http://rt', (_url, init) => {
      sent = String(init?.body ?? '');
      return Promise.resolve(streamedResponse(sseBody(FRAMES), 5));
    });
    await client.runStream(request, () => {});
    return JSON.parse(sent) as Record<string, unknown>;
  };

  it('sends the slug, so the run can bind the workflow’s own tools', async () => {
    const body = await bodySentBy({ workflow: {}, question: 'q', workflowSlug: 'chinook' });

    expect(body['workflow_slug']).toBe('chinook');
  });

  it('sends the audience, so a developer gets the developer channel', async () => {
    const body = await bodySentBy({ workflow: {}, question: 'q', audience: 'developer' });

    expect(body['audience']).toBe('developer');
  });

  it('sends the step budget under the name the backend reads', async () => {
    const body = await bodySentBy({ workflow: {}, question: 'q', recursionLimit: 42 });

    expect(body['recursion_limit']).toBe(42);
  });

  it('sends browser-held credentials', async () => {
    // Serialized here and asserted nowhere before this: `AskPanel` spreads
    // `credentialsPatch(...)` into every send, and a key pasted into the
    // dialog only reaches a run through this field.
    const body = await bodySentBy({
      workflow: {},
      question: 'q',
      credentials: { OPENAI_API_KEY: 'sk-from-the-browser' },
    });

    expect(body['credentials']).toEqual({ OPENAI_API_KEY: 'sk-from-the-browser' });
  });

  it('omits every optional field when it was not given', async () => {
    // The other half: a key that is always present would make a deployment
    // with server-side configuration look like one being overridden.
    const body = await bodySentBy({ workflow: {}, question: 'q' });

    expect(Object.keys(body).sort()).toEqual(['question', 'workflow']);
  });

  it('calls onEvent for every update and token frame, in order', async () => {
    const text = sseBody(FRAMES);
    const client = new RuntimeClient('http://rt', () =>
      Promise.resolve(streamedResponse(text, Math.floor(text.length / 2))),
    );

    const seen: string[] = [];
    await client.runStream({ workflow: {}, question: 'q' }, (event) => seen.push(event.type));

    expect(seen).toEqual(['update', 'update', 'token', 'token']);
  });

  it('resolves with the final result from the done frame', async () => {
    const text = sseBody(FRAMES);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 5)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(true);
    if (!result.ok || 'interrupted' in result.value || 'cancelled' in result.value) return;
    expect(result.value.answer).toBe('Rock earns the most.');
    expect(result.value.decisions['node:route.grader-1']).toBe('pass');
  });

  it('surfaces the task id that tells two dispatched worker instances apart', async () => {
    const text = sseBody(FRAMES);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 1)));

    const updates: unknown[] = [];
    await client.runStream({ workflow: {}, question: 'q' }, (event) => {
      if (event.type === 'update') updates.push(event.taskId);
    });

    expect(updates).toEqual([null, 'task-1']);
  });

  it('carries the resolved active canvas node, falling back to the frame node', async () => {
    // Ticket 01: the stream decides what is running; the client never guesses.
    // A frame from an older backend has no `activeNode` and must still work.
    const text = sseBody([
      ['update', { node: 'node:router.1', namespace: [], activeNode: 'node:router.1' }],
      [
        'update',
        {
          node: 'inner_answer',
          namespace: ['wf_music:ckpt-1'],
          internal: true,
          activeNode: 'node:mount.music',
        },
      ],
      ['update', { node: 'node:legacy.1', namespace: [] }],
      ['done', { answer: 'a', decisions: {}, outputs: {}, attempts: 0, mermaid: '', warnings: [] }],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 7)));

    const active: string[] = [];
    await client.runStream({ workflow: {}, question: 'q' }, (event) => {
      if (event.type === 'update') active.push(event.activeNode);
    });

    expect(active).toEqual(['node:router.1', 'node:mount.music', 'node:legacy.1']);
  });

  it('carries the active node on token frames, which are the ones that arrive early', async () => {
    // Ticket 02. `update` frames are emitted when a node *finishes*, so a
    // highlight fed by them alone shows the last node to complete. Tokens are
    // the only frames that arrive while a node is still working — recorded
    // live: 100+ of them streamed from inside a mounted workflow while the
    // last update frame still named the router.
    const text = sseBody([
      [
        'token',
        {
          node: 'model',
          namespace: ['analyst:c1', 'agent_sql:c2'],
          content: 'a',
          activeNode: 'analyst',
        },
      ],
      [
        'token',
        {
          node: 'model',
          namespace: ['analyst:c1', 'agent_sql:c2'],
          content: 'b',
          activeNode: 'analyst',
        },
      ],
      // Older backend: no field, and no guess from `node` — `model` is on no
      // canvas, so pointing the highlight at it would be worse than silence.
      ['token', { node: 'model', namespace: [], content: 'c' }],
      ['done', { answer: 'a', decisions: {}, outputs: {}, attempts: 0, mermaid: '', warnings: [] }],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const active: string[] = [];
    await client.runStream({ workflow: {}, question: 'q' }, (event) => {
      if (event.type === 'token') active.push(event.activeNode);
    });

    expect(active).toEqual(['analyst', 'analyst', '']);
  });

  it('a frame split exactly at the blank-line boundary still parses correctly', async () => {
    // The boundary the parser looks for is "\n\n" — splitting the byte stream
    // exactly there is the sharpest edge case for a buffering parser.
    const text = sseBody(FRAMES);
    const boundary = text.indexOf('\n\n') + 2;
    const client = new RuntimeClient('http://rt', () =>
      Promise.resolve(streamedResponse(text, boundary)),
    );

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(true);
  });

  it('resolves with an error when the server emits an error frame', async () => {
    const text = sseBody([['error', { detail: 'KeyError: prompt' }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 3)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toBe('KeyError: prompt');
  });

  it('is a failure, not a hang, if the stream closes with no done frame', async () => {
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse('', 0)));
    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(false);
  });

  it('reports unreachability the same way run() does', async () => {
    const client = new RuntimeClient('http://rt', () => Promise.reject(new Error('down')));
    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('Is the backend running?');
  });
});

/**
 * The conversation, both directions.
 *
 * A client can only ask a follow-up if it can (a) learn which thread its last
 * question landed in and (b) name that thread on the next one. Neither half is
 * visible from a rendered answer — a question sent into a fresh thread looks
 * exactly like one sent into the right thread until the model is asked
 * something that needs an antecedent — so both are pinned here.
 */
describe('RuntimeClient — thread continuity', () => {
  const doneFrame = (extra: Record<string, unknown> = {}) =>
    sseBody([
      [
        'done',
        {
          threadId: 'run-1234-abcd',
          answer: 'Rock, $826.65',
          decisions: {},
          outputs: {},
          attempts: 1,
          mermaid: '',
          ...extra,
        },
      ],
    ]);

  it('names the thread the done frame reported', async () => {
    const text = doneFrame();
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 7)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(true);
    if (!result.ok || 'interrupted' in result.value || 'cancelled' in result.value) return;
    expect(result.value.threadId).toBe('run-1234-abcd');
  });

  it('sends a known thread back under the key the server expects', async () => {
    const text = doneFrame();
    const stub = stubFetch(streamedResponse(text, 7));
    await new RuntimeClient('http://rt', stub.fetch).runStream(
      { workflow: {}, question: 'how did you get that?', threadId: 'run-1234-abcd' },
      () => {},
    );

    // snake_case, like every other field on this request: FastAPI forbids
    // unknown keys on `RunRequest`, and a camelCase `threadId` would be
    // rejected outright rather than silently starting a new conversation.
    const sent = JSON.parse(stub.bodies[0]!) as Record<string, unknown>;
    expect(sent['thread_id']).toBe('run-1234-abcd');
  });

  it('omits the thread on the first question, so the server mints one', async () => {
    const text = doneFrame();
    const stub = stubFetch(streamedResponse(text, 7));
    await new RuntimeClient('http://rt', stub.fetch).runStream(
      { workflow: {}, question: 'which genre earns the most?' },
      () => {},
    );
    expect(JSON.parse(stub.bodies[0]!)).not.toHaveProperty('thread_id');
  });

  it('names the thread on a failure too — a failed turn still happened in one', async () => {
    // The failure settles as `Err(detail)`, which carries prose and no thread,
    // so the `error` *event* is the only place a surface can learn it. Without
    // this the send after a failed turn would silently open a second
    // conversation.
    const text = sseBody([['error', { threadId: 'run-1234-abcd', detail: 'KeyError: prompt' }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 3)));

    const threads: string[] = [];
    await client.runStream({ workflow: {}, question: 'q' }, (event) => {
      if (event.type === 'error') threads.push(event.threadId);
    });
    expect(threads).toEqual(['run-1234-abcd']);
  });

  it('reports an empty thread rather than inventing one, against an older backend', async () => {
    // Empty means "this frame said nothing about its thread". Consumers treat
    // it as "keep what you have" (`thread.ts`), never as "there is none".
    const text = sseBody([
      ['done', { answer: 'a', decisions: {}, outputs: {}, attempts: 0, mermaid: '' }],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 5)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(true);
    if (!result.ok || 'interrupted' in result.value || 'cancelled' in result.value) return;
    expect(result.value.threadId).toBe('');
  });
});

/**
 * A stop, from the client's side.
 *
 * The interesting property is that stopping is **not an error**: the run did
 * what it was told, so the outcome is `Ok` carrying a `cancelled` marker and
 * every surface can render "Stopped by you" as a muted line rather than a
 * failure. Anything already streamed still reached `onEvent` — a stopped run
 * keeps the partial trace it earned.
 */
describe('RuntimeClient.runStream — stopping', () => {
  /**
   * A fetch whose body stays open until the caller's `AbortSignal` fires,
   * which is what a real streaming run looks like when Stop is pressed
   * mid-flight (a closed body would settle on its own and prove nothing).
   */
  const openStream = (
    prelude: string,
  ): { fetch: FetchLike; signals: (AbortSignal | undefined)[] } => {
    const signals: (AbortSignal | undefined)[] = [];
    const fetchImpl: FetchLike = (_url, init) => {
      const signal = init?.signal ?? undefined;
      signals.push(signal);
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(prelude));
          signal?.addEventListener('abort', () => {
            controller.error(new DOMException('The operation was aborted.', 'AbortError'));
          });
        },
      });
      return Promise.resolve(
        new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
      );
    };
    return { fetch: fetchImpl, signals };
  };

  it('forwards the signal to fetch, so the request itself is torn down', async () => {
    const stub = openStream('');
    const controller = new AbortController();
    const client = new RuntimeClient('http://rt', stub.fetch);

    const pending = client.runStream({ workflow: {}, question: 'q' }, () => {}, {
      signal: controller.signal,
    });
    controller.abort();
    await pending;

    expect(stub.signals[0]).toBe(controller.signal);
  });

  it('settles as a cancelled outcome, not a failure', async () => {
    const stub = openStream(sseBody([['update', { node: 'node:input.text-1', namespace: [] }]]));
    const controller = new AbortController();
    const client = new RuntimeClient('http://rt', stub.fetch);
    const seen: RunStreamEvent[] = [];

    const pending = client.runStream(
      { workflow: {}, question: 'q' },
      (event) => {
        seen.push(event);
        controller.abort(); // stop the moment the first node reports
      },
      { signal: controller.signal },
    );
    const result = await pending;

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(true);
    // The partial trace survives — a stop is not an undo.
    expect(seen).toHaveLength(1);
  });

  it('is cancelled, not "is the backend running?", when the abort beats the response', async () => {
    const controller = new AbortController();
    controller.abort();
    const client = new RuntimeClient('http://rt', () =>
      Promise.reject(new DOMException('The operation was aborted.', 'AbortError')),
    );

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {}, {
      signal: controller.signal,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(true);
  });

  it('stops a resume the same way — one seam, both endpoints', async () => {
    const stub = openStream('');
    const controller = new AbortController();
    const client = new RuntimeClient('http://rt', stub.fetch);

    const pending = client.resume({ threadId: 't1', workflow: {}, decision: 'approve' }, () => {}, {
      signal: controller.signal,
    });
    controller.abort();
    const result = await pending;

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(true);
  });

  it('is cancelled, not "closed without a result", when the read just ends', async () => {
    // The shape found live: cancelling a reader can resolve the pending read
    // with `done: true` instead of throwing, so the loop exits cleanly with
    // no `done` frame — indistinguishable from a server hanging up early
    // except for the signal.
    const controller = new AbortController();
    controller.abort();
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse('', 0)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {}, {
      signal: controller.signal,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(true);
  });

  it('still reports a real result that arrived before the stop', async () => {
    // The signal is checked last on purpose: a `done` frame already parsed is
    // the answer, and a stop pressed a moment later must not discard it.
    const controller = new AbortController();
    controller.abort();
    const text = sseBody([['done', { answer: 'Rock.', decisions: {}, outputs: {} }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 4)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {}, {
      signal: controller.signal,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(false);
  });

  it('leaves an unsignalled run exactly as it was', async () => {
    const text = sseBody([['done', { answer: 'Rock.', decisions: {}, outputs: {} }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 4)));
    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(false);
  });
});

/**
 * The other half of the terminal-frame contract (UX-02).
 *
 * The server guarantees exactly one of `done` / `interrupt` / `error` as the
 * last frame of every stream it is still able to write to. The one case it
 * cannot cover is its own death — a `--reload` restart or a crash runs no
 * code and closes the socket — so **this client is the authority there**, and
 * a body that ends with no terminal frame must settle as a named failure
 * rather than a silent success or an open spinner.
 */
describe('RuntimeClient.runStream — how a stream ended', () => {
  it('settles on the interrupt frame, which is terminal and carries no answer', async () => {
    const text = sseBody([
      ['update', { node: 'node:input.text-1', namespace: [] }],
      [
        'interrupt',
        {
          threadId: 'th-1',
          node: 'node:human.approval-1',
          message: 'Approve this?',
          candidate: 'the draft',
        },
      ],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(true);
    if (!result.ok || !('interrupted' in result.value)) throw new Error('expected a pause');
    expect(result.value.threadId).toBe('th-1');
    // The node that is waiting, not the last one that reported — what lets a
    // surface mark the approval node itself.
    expect(result.value.node).toBe('node:human.approval-1');
  });

  it('carries the upstream grader\u2019s verdict and reason when the frame has them', async () => {
    // `workflow-gallery` 32. Grade-then-gate is the natural shape for anything
    // a person signs off, and the reviewer was shown the draft with the one
    // existing machine opinion of it discarded.
    const text = sseBody([
      [
        'interrupt',
        {
          threadId: 'th-1',
          node: 'node:human.approval-1',
          message: 'Approve this?',
          candidate: 'the draft',
          verdict: 'revise',
          reason: "'if appropriate' is a hedge the rubric forbids.",
        },
      ],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    if (!result.ok || !('interrupted' in result.value)) throw new Error('expected a pause');
    expect(result.value.verdict).toBe('revise');
    expect(result.value.reason).toBe("'if appropriate' is a hedge the rubric forbids.");
  });

  it('leaves the verdict empty when no grader produced the candidate', async () => {
    // Both keys are absent together, and absence is a value: no machine
    // opinion exists. An empty string is how this client says that \u2014 the
    // same shape every other optional string field takes here.
    const text = sseBody([
      ['interrupt', { threadId: 'th-1', message: 'Approve this?', candidate: 'the draft' }],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    if (!result.ok || !('interrupted' in result.value)) throw new Error('expected a pause');
    expect(result.value.verdict).toBe('');
    expect(result.value.reason).toBe('');
  });

  it('leaves the paused node empty rather than inventing one', async () => {
    const text = sseBody([['interrupt', { threadId: 'th-1', message: 'Approve this?' }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    if (!result.ok || !('interrupted' in result.value)) throw new Error('expected a pause');
    expect(result.value.node).toBe('');
  });

  it('settles on the error frame as a failure, not a missing result', async () => {
    const text = sseBody([
      ['update', { node: 'node:input.text-1', namespace: [] }],
      ['error', { detail: 'RuntimeError: the checkpointer is gone' }],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('the checkpointer is gone');
  });

  it('names the dropped connection when the body ends with no terminal frame', async () => {
    // A killed backend, exactly: frames arrived, then the socket closed with
    // no `done`, no `interrupt`, no `error`, and no abort signal to explain
    // it. Guessing "finished" here is what would show an empty answer as
    // success; guessing "still running" is a spinner that never stops.
    const text = sseBody([['update', { node: 'node:input.text-1', namespace: [] }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toMatch(/without saying how it ended/);
    expect(result.error).toMatch(/restarted or crashed/);
  });

  it('is a failure, not a thrown error, when the socket dies mid-stream', async () => {
    // How a killed backend usually arrives: not a clean end of body, but a
    // rejected `read()`. This used to propagate out of `runStream`, past
    // `AskPanel`'s `await` — which has no `catch` — leaving the turn stuck on
    // `running: true` forever. A stuck spinner is the exact failure mode the
    // terminal-frame contract exists to prevent, so the transport settles it.
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(sseBody([['update', { node: 'node:a', namespace: [] }]])),
        );
        controller.error(new TypeError('network error'));
      },
    });
    const client = new RuntimeClient('http://rt', () =>
      Promise.resolve(new Response(body, { status: 200 })),
    );

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toMatch(/without saying how it ended/);
    expect(result.error).toContain('network error');
  });

  it('keeps a stop a stop, even though a stop also has no terminal frame', async () => {
    // The two look identical on the wire — the signal is the only evidence
    // that separates them, so the dropped-connection message must not
    // swallow the user's own Stop.
    const controller = new AbortController();
    controller.abort();
    const text = sseBody([['update', { node: 'node:input.text-1', namespace: [] }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {}, {
      signal: controller.signal,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isCancelled(result.value)).toBe(true);
  });
});

describe('RuntimeClient — past runs', () => {
  const ROW = {
    thread_id: 't-1',
    workflow_slug: 'chinook-assistant',
    session_id: 's-1',
    user_email: 'ada@example.com',
    updated_at: '2026-08-10T12:00:00+00:00',
    steps: 4,
    question: 'how many tracks?',
    answer: 'Rock earns the most.',
    status: 'paused',
  };

  it('lists what the backend stored, renamed into the editor’s vocabulary', async () => {
    const stub = stubFetch(jsonResponse({ threads: [ROW] }));
    const result = await new RuntimeClient('', stub.fetch).pastRuns();
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value[0]).toEqual({
      threadId: 't-1',
      workflowSlug: 'chinook-assistant',
      sessionId: 's-1',
      userEmail: 'ada@example.com',
      updatedAt: '2026-08-10T12:00:00+00:00',
      steps: 4,
      question: 'how many tracks?',
      answer: 'Rock earns the most.',
      status: 'paused',
      failed: false,
    });
  });

  it('reads a failed node’s sentinel back as `failed`, separately from `status`', async () => {
    const stub = stubFetch(jsonResponse({ threads: [{ ...ROW, failed: true }] }));
    const result = await new RuntimeClient('', stub.fetch).pastRuns();
    expect(result.ok && result.value[0]?.failed).toBe(true);
  });

  it('sends the filters as query parameters, not as a body', async () => {
    const stub = stubFetch(jsonResponse({ threads: [] }));
    await new RuntimeClient('', stub.fetch).pastRuns({
      workflowSlug: 'demo',
      userEmail: 'ada@example.com',
      limit: 5,
    });
    expect(stub.calls[0]).toContain('/api/threads?');
    expect(stub.calls[0]).toContain('workflow_slug=demo');
    expect(stub.calls[0]).toContain('user_email=ada%40example.com');
    expect(stub.calls[0]).toContain('limit=5');
    expect(stub.bodies).toEqual([]);
  });

  it('asks for no filters when given none', async () => {
    const stub = stubFetch(jsonResponse({ threads: [] }));
    await new RuntimeClient('', stub.fetch).pastRuns();
    expect(stub.calls[0]).toBe('/api/threads');
  });

  it('treats an unknown status as finished — never offering a Resume that cannot work', async () => {
    const stub = stubFetch(jsonResponse({ threads: [{ ...ROW, status: 'something-new' }] }));
    const result = await new RuntimeClient('', stub.fetch).pastRuns();
    expect(result.ok && result.value[0]?.status).toBe('finished');
  });

  it('reads one run back as its steps, oldest first', async () => {
    const stub = stubFetch(
      jsonResponse({
        thread: ROW,
        steps: [
          { checkpoint_id: 'c1', step: -1, at: 'a', source: 'input', values: {} },
          { checkpoint_id: 'c2', step: 0, at: 'b', source: 'loop', values: { answer: 'x' } },
        ],
      }),
    );
    const result = await new RuntimeClient('', stub.fetch).pastRun('t-1');
    expect(stub.calls[0]).toBe('/api/threads/t-1');
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.run.threadId).toBe('t-1');
    expect(result.value.steps.map((step) => step.step)).toEqual([-1, 0]);
    expect(result.value.steps[1]?.values['answer']).toBe('x');
  });

  it('escapes a thread id rather than pasting it into a URL', async () => {
    const stub = stubFetch(jsonResponse({ thread: ROW, steps: [] }));
    await new RuntimeClient('', stub.fetch).pastRun('a/b?c');
    expect(stub.calls[0]).toBe('/api/threads/a%2Fb%3Fc');
  });

  it('says plainly when a thread is not stored', async () => {
    const stub = stubFetch(jsonResponse({ detail: 'nope' }, 404));
    const result = await new RuntimeClient('', stub.fetch).pastRun('gone');
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('gone');
  });

  it('reports an unreachable backend as such, not as an empty history', async () => {
    const client = new RuntimeClient('http://localhost:8000', () => Promise.reject(new Error('x')));
    const result = await client.pastRuns();
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('Is the backend running?');
  });
});

describe('RuntimeClient.health', () => {
  it('reports whether a model is configured', async () => {
    const client = new RuntimeClient(
      'http://rt',
      stubFetch(jsonResponse({ ok: true, model_configured: true })).fetch,
    );
    const result = await client.health();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.modelConfigured).toBe(true);
  });

  it('is a failure, not a crash, when nothing is listening', async () => {
    const client = new RuntimeClient('http://rt', () => Promise.reject(new Error('down')));
    expect((await client.health()).ok).toBe(false);
  });
});

describe('the base URL a real page gets', () => {
  /**
   * The regression this pins: served from the wheel on port 51423, an absolute
   * `http://localhost:8000` sends every call to a port with nothing on it, and
   * the editor loads perfectly while doing nothing at all.
   */
  it('is same-origin relative in a production bundle', async () => {
    vi.stubEnv('DEV', false);
    const stub = stubFetch(jsonResponse(GOOD));

    await new RuntimeClient(undefined, stub.fetch).run({ workflow: {}, question: 'q' });

    expect(stub.calls[0]).toBe('/api/runs');
    vi.unstubAllEnvs();
  });

  it('is the dev backend when Vite is serving the app', async () => {
    vi.stubEnv('DEV', true);
    const stub = stubFetch(jsonResponse(GOOD));

    await new RuntimeClient(undefined, stub.fetch).run({ workflow: {}, question: 'q' });

    expect(stub.calls[0]).toBe('http://localhost:8000/api/runs');
    vi.unstubAllEnvs();
  });

  it('names the origin rather than an empty string when nothing answers', async () => {
    vi.stubEnv('DEV', false);
    const client = new RuntimeClient(undefined, () => Promise.reject(new Error('down')));

    const result = await client.run({ workflow: {}, question: 'q' });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('this page’s own origin');
    vi.unstubAllEnvs();
  });
});

describe('the terminal frame keeps the parent and its mounts apart (ticket 40)', () => {
  it('reads the nested maps, keyed by mount path', async () => {
    const text = sseBody([
      [
        'done',
        {
          answer: 'Iron Maiden.',
          decisions: { router1: 'b-music' },
          outputs: { in1: "the parent's question" },
          nested: {
            decisions: { 'wf-music/router1': 'b-data' },
            outputs: { 'wf-music/agent-sql': 'the SQL answer' },
          },
        },
      ],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 8)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(true);
    if (!result.ok || 'interrupted' in result.value || 'cancelled' in result.value) return;
    // Both true facts, side by side. The flat map used to hold whichever
    // document wrote last, and `concierge`'s own `b-music` was the casualty.
    expect(result.value.decisions['router1']).toBe('b-music');
    expect(result.value.nested.decisions['wf-music/router1']).toBe('b-data');
    expect(result.value.nested.outputs['wf-music/agent-sql']).toBe('the SQL answer');
  });

  it('is empty rather than absent when a run touched no mounts', async () => {
    // A reader should not have to special-case the common single-document run.
    const text = sseBody([['done', { answer: 'Rock.', decisions: {}, outputs: { in1: 'q' } }]]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 4)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});
    expect(result.ok).toBe(true);
    if (!result.ok || 'interrupted' in result.value || 'cancelled' in result.value) return;
    expect(result.value.nested).toEqual({ outputs: {}, decisions: {} });
  });
});

/**
 * The MCP registry (mcp-connect ticket 03).
 *
 * Three routes, one property worth pinning above all others: **no request
 * this client makes has anywhere to put a credential**. The panel collects a
 * variable NAME, the server resolves it from its own environment, and the
 * test below is what keeps that true when somebody adds a field.
 */
describe('RuntimeClient and the MCP registry', () => {
  const SERVERS = [
    {
      name: 'LangChain docs',
      url: 'https://docs.langchain.com/mcp',
      transport: 'streamable_http',
      auth: { kind: 'none', headerName: '', tokenEnv: '' },
      origin: 'built-in',
      credentialConfigured: true,
    },
  ];

  it('lists what the project can bind', async () => {
    const stub = stubFetch(jsonResponse(SERVERS));
    const result = await new RuntimeClient('http://rt', stub.fetch).mcp.servers();

    expect(stub.calls[0]).toBe('http://rt/api/mcp/servers');
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value[0]?.origin).toBe('built-in');
    expect(result.value[0]?.credentialConfigured).toBe(true);
  });

  it('posts a variable name and never a value', async () => {
    const stub = stubFetch(jsonResponse(SERVERS));
    await new RuntimeClient('http://rt', stub.fetch).mcp.save({
      name: 'Internal docs',
      url: 'https://mcp.example.test/mcp',
      transport: 'sse',
      auth: { kind: 'bearer', headerName: '', tokenEnv: 'MY_MCP_TOKEN' },
    });

    const sent = JSON.parse(stub.bodies[0]!) as Record<string, unknown>;
    expect(sent['transport']).toBe('sse');
    expect(sent['auth']).toEqual({ kind: 'bearer', headerName: '', tokenEnv: 'MY_MCP_TOKEN' });
    // The whole secrets rule, as one assertion: there is no key in the body a
    // credential could be in, so a paste into the field lands in `tokenEnv`
    // and is refused by the validator and by the loader, not shipped.
    expect(Object.keys(sent).sort()).toEqual(['auth', 'name', 'transport', 'url']);
  });

  it('escapes a server name with a space in it', async () => {
    const stub = stubFetch(jsonResponse([]));
    await new RuntimeClient('http://rt', stub.fetch).mcp.remove('LangChain docs');

    expect(stub.calls[0]).toBe('http://rt/api/mcp/servers/LangChain%20docs');
  });

  it('returns the server’s own refusal rather than a generic one', async () => {
    const stub = stubFetch(
      jsonResponse({ detail: 'auth.token_env must be an environment variable NAME' }, 400),
    );
    const result = await new RuntimeClient('http://rt', stub.fetch).mcp.save({
      name: 'Vendor',
      url: 'https://vendor.test/mcp',
      transport: 'streamable_http',
      auth: { kind: 'bearer', headerName: '', tokenEnv: 'sk-live' },
    });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain('environment variable NAME');
  });

  it('reads a verdict back with its tool names', async () => {
    const stub = stubFetch(
      jsonResponse({
        status: 'live',
        message: 'Docs by LangChain answered with 3 tools.',
        serverName: 'Docs by LangChain',
        serverVersion: '1.0.0',
        tools: ['search_docs_by_lang_chain', 'submit_feedback'],
        elapsedSeconds: 0.86,
      }),
    );
    const result = await new RuntimeClient('http://rt', stub.fetch).mcp.validate({
      server: 'LangChain docs',
    });

    expect(stub.calls[0]).toBe('http://rt/api/mcp/validate');
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.status).toBe('live');
    expect(result.value.tools).toEqual(['search_docs_by_lang_chain', 'submit_feedback']);
  });

  it('treats an unrecognised status as “not an MCP server” rather than as live', async () => {
    // A status this client does not know is a server it cannot vouch for, and
    // the failing badge is the safe direction to round towards.
    const stub = stubFetch(jsonResponse({ status: 'something-new', message: 'hm' }));
    const result = await new RuntimeClient('http://rt', stub.fetch).mcp.validate({
      url: 'https://vendor.test/mcp',
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.status).toBe('not_mcp');
  });
});
