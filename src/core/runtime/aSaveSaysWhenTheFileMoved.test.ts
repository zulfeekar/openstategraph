import { describe, expect, it } from 'vitest';

import {
  WorkflowFileClient,
  saveFailureMessage,
  type FetchLike,
  type SaveFailure,
} from './WorkflowFileClient';

/**
 * A save quotes the version it is editing, and hears "no" (`osg-agent-experience/45`).
 *
 * A coding agent rewrites `workflows/<slug>/workflow.json` while the editor
 * has it open; autosave posts a document built before those edits and the
 * backend answers 200. Four edges were gone before anybody looked. The
 * backend is the only process that can see the file, so the refusal lives
 * there — this side's job is to *say which version it edited* and to read
 * the 409 back as something the editor can act on rather than as one more
 * failed request.
 *
 * The two facts a conflict must carry are the sentence a person reads and
 * the digest the file actually has. Without the second there is no way to
 * say "keep mine" other than turning the guard off, which is how a guard
 * becomes a checkbox nobody leaves on.
 */

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const stubFetch = (
  ...responses: Response[]
): { fetch: FetchLike; calls: { url: string; init?: RequestInit }[] } => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchImpl: FetchLike = (url, init) => {
    calls.push({ url, init });
    const next = responses[Math.min(calls.length - 1, responses.length - 1)]!;
    return Promise.resolve(next.clone());
  };
  return { fetch: fetchImpl, calls };
};

const bodyOf = (call: { init?: RequestInit }): Record<string, unknown> =>
  JSON.parse(call.init?.body as string) as Record<string, unknown>;

describe('WorkflowFileClient.save — quoting the version it edited', () => {
  it('sends the base digest it was given', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'my-flow', document: {}, digest: 'sha-2' }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    await client.save('my-flow', 'My Flow', { nodes: [] }, 'sha-1');

    expect(bodyOf(stub.calls[0]!)).toEqual({
      name: 'My Flow',
      document: { nodes: [] },
      must_exist: true,
      base_digest: 'sha-1',
    });
  });

  it('omits the field entirely when the caller has no version to quote', async () => {
    // Unguarded is a real answer, not a lapse: an explicit Save is the user
    // saying "keep mine", and a client that has never been handed a digest
    // must not invent one.
    const stub = stubFetch(jsonResponse({ slug: 'my-flow', document: {}, digest: 'sha-2' }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    await client.save('my-flow', 'My Flow', { nodes: [] });

    expect('base_digest' in bodyOf(stub.calls[0]!)).toBe(false);
  });

  it('answers with the new digest so the next save can quote it', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'my-flow', document: {}, digest: 'sha-2' }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const outcome = await client.save('my-flow', 'My Flow', { nodes: [] }, 'sha-1');

    expect(outcome).toEqual({ ok: true, value: { digest: 'sha-2' } });
  });

  it('reads a 409 as a conflict carrying the digest the file actually has', async () => {
    const stub = stubFetch(
      jsonResponse({ detail: { reason: "'my-flow' changed on disk", digest: 'sha-9' } }, 409),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const outcome = await client.save('my-flow', 'My Flow', { nodes: [] }, 'sha-1');

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error).toEqual({
      kind: 'conflict',
      reason: "'my-flow' changed on disk",
      digest: 'sha-9',
    });
  });

  it('is an ordinary error, never a conflict, when the backend says something else', async () => {
    const stub = stubFetch(jsonResponse({ detail: "No workflow named 'my-flow'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const outcome = await client.save('my-flow', 'My Flow', {}, 'sha-1');

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error.kind).toBe('error');
    expect(saveFailureMessage(outcome.error)).toBe("No workflow named 'my-flow'");
  });

  it('does not mistake a 409 with no digest for a usable conflict', async () => {
    // Strict in trusting: a conflict whose digest is missing offers no way
    // to keep your own version, so it is reported as the plain failure it is
    // rather than as a choice the editor cannot actually give.
    const stub = stubFetch(jsonResponse({ detail: 'conflict' }, 409));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const outcome = await client.save('my-flow', 'My Flow', {}, 'sha-1');

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error.kind).toBe('error');
  });
});

describe('saveFailureMessage — one copy owner for the sentence', () => {
  it('hands back the backend words for an ordinary failure', () => {
    const failure: SaveFailure = { kind: 'error', message: 'the runtime returned 500' };
    expect(saveFailureMessage(failure)).toBe('the runtime returned 500');
  });

  it('hands back the conflict reason, which the backend wrote', () => {
    const failure: SaveFailure = { kind: 'conflict', reason: 'x changed on disk', digest: 'd' };
    expect(saveFailureMessage(failure)).toBe('x changed on disk');
  });
});
