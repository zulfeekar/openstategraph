import { describe, expect, it } from 'vitest';
import { RuntimeClient, type FetchLike } from './RuntimeClient';

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
    if (!result.ok || 'interrupted' in result.value) return;
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
