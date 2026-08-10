import { describe, expect, it } from 'vitest';
import {
  RuntimeClient,
  isCancelled,
  type FetchLike,
  type RunStreamEvent,
} from './RuntimeClient';

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
      workflowSlug: 'chinook-nl-to-sql',
    });

    // The backend layers that workflow's own tools over its defaults; a
    // camelCase key would be silently dropped by FastAPI and the run would
    // bind no workflow tools — the agent then answers from memory.
    const sent = JSON.parse(stub.bodies[0]!) as Record<string, unknown>;
    expect(sent['workflow_slug']).toBe('chinook-nl-to-sql');
  });

  it('omits the slug when none is known — the field is optional server-side', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    await new RuntimeClient('http://rt', stub.fetch).run({ workflow: {}, question: 'q' });
    expect(JSON.parse(stub.bodies[0]!)).not.toHaveProperty('workflow_slug');
  });

  it('sends the advisor flag only when the caller asks for it', async () => {
    const stub = stubFetch(jsonResponse(GOOD));
    const client = new RuntimeClient('http://rt', stub.fetch);
    await client.run({ workflow: {}, question: 'q', advisor: true });
    await client.run({ workflow: {}, question: 'q' });

    // Editor-only capability. Omitted rather than sent as `false` so the
    // customer `/chat` surface's requests stay byte-identical to what they
    // were before this existed — nothing there can ever opt in by accident.
    expect(JSON.parse(stub.bodies[0]!)).toHaveProperty('advisor', true);
    expect(JSON.parse(stub.bodies[1]!)).not.toHaveProperty('advisor');
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

    const pending = client.resume(
      { threadId: 't1', workflow: {}, decision: 'approve' },
      () => {},
      { signal: controller.signal },
    );
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
      ['interrupt', { threadId: 'th-1', message: 'Approve this?', candidate: 'the draft' }],
    ]);
    const client = new RuntimeClient('http://rt', () => Promise.resolve(streamedResponse(text, 9)));

    const result = await client.runStream({ workflow: {}, question: 'q' }, () => {});

    expect(result.ok).toBe(true);
    if (!result.ok || !('interrupted' in result.value)) throw new Error('expected a pause');
    expect(result.value.threadId).toBe('th-1');
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
