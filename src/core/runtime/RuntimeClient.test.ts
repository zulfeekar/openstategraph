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

const stubFetch = (
  response: Response,
): { fetch: FetchLike; calls: string[]; bodies: string[] } => {
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
      const client = new RuntimeClient(
        'http://rt',
        stubFetch(jsonResponse({ detail }, 503)).fetch,
      );
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

    it('falls back to the status when the body carries no detail', async () => {
      const client = new RuntimeClient('http://rt', stubFetch(new Response('', { status: 500 })).fetch);
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
