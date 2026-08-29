import { describe, expect, it } from 'vitest';
import { RuntimeClient, type RunStreamEvent } from './RuntimeClient';

/**
 * The client's half of three frames the backend gained together —
 * `memory-and-replay` 53, 55 and 56.
 *
 * `contractDrift.test.ts` already proves this client *handles* every event
 * name the published contract declares and reads every field off each one.
 * What it cannot see is what the values become: a name it reads and then
 * mangles, a `null` it turns into a zero, a withheld field it renders as a
 * fact. That is what is here.
 *
 * The three, in the order a reader meets them on the wire:
 *
 * - **`started`** opens the stream and carries `threadId`, which used to reach
 *   a client only on a terminal frame — so a dropped connection lost the
 *   conversation.
 * - **`invoked`** says an ordinary tool was asked for, before its answer comes
 *   back, and is blanked rather than withheld for a customer.
 * - **`usage`** is what the whole run cost, per model, on all three terminal
 *   frames — `null` when the reader is not told, `[]` when no model was
 *   called, and those are different claims.
 */

const sseBody = (frames: readonly [string, Record<string, unknown>][]): string =>
  frames.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('');

const streaming = (frames: readonly [string, Record<string, unknown>][]): RuntimeClient => {
  const text = sseBody(frames);
  return new RuntimeClient('http://rt', () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        // Split mid-body, because a real network read does: the parser has to
        // buffer, and a frame kind added without that is a frame kind that
        // works only when the whole run fits in one chunk.
        const bytes = new TextEncoder().encode(text);
        controller.enqueue(bytes.slice(0, Math.floor(bytes.length / 2)));
        controller.enqueue(bytes.slice(Math.floor(bytes.length / 2)));
        controller.close();
      },
    });
    return Promise.resolve(
      new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    );
  });
};

const collect = async (
  frames: readonly [string, Record<string, unknown>][],
): Promise<{ events: RunStreamEvent[]; outcome: unknown }> => {
  const events: RunStreamEvent[] = [];
  const outcome = await streaming(frames).runStream({ workflow: {}, question: 'q' }, (event) =>
    events.push(event),
  );
  return { events, outcome };
};

const DONE: [string, Record<string, unknown>] = [
  'done',
  { answer: 'Rock.', decisions: {}, outputs: {}, attempts: 0, mermaid: '', usage: [] },
];

describe('the frame that opens a run', () => {
  it('reaches a consumer first, with the thread it is in', async () => {
    const { events } = await collect([['started', { threadId: 'thread-9', seq: 0 }], DONE]);

    expect(events.map((event) => event.type)).toEqual(['started']);
    expect(events[0]).toMatchObject({ type: 'started', threadId: 'thread-9', seq: 0 });
  });

  it('survives a backend that predates it, because nothing waits for it', async () => {
    // The client must not require the opening frame: a stream that begins with
    // an `update` is what every deployment older than this ticket sends.
    const { events } = await collect([['update', { node: 'in1' }], DONE]);

    expect(events.map((event) => event.type)).toEqual(['update']);
  });
});

describe('the frame that says a tool was asked for', () => {
  it('carries the identity that joins it to the tool result frame', async () => {
    const { events } = await collect([
      ['invoked', { node: 'agent', name: 'service_registry', callId: 'call-1', seq: 3 }],
      ['token', { node: 'agent', kind: 'tool', content: 'rows', tool: { callId: 'call-1' } }],
      DONE,
    ]);

    const invoked = events[0];
    expect(invoked).toMatchObject({
      type: 'invoked',
      name: 'service_registry',
      callId: 'call-1',
      withheld: false,
    });
    // The join, which is the reason there is no closing frame. The client
    // flattens the result frame's `tool` object into `toolName`/`toolCallId`,
    // so the pairing a surface actually makes is `invoked.callId` against
    // `token.toolCallId`.
    expect(events[1]).toMatchObject({ type: 'token', toolCallId: 'call-1' });
  });

  it('reports a blanked frame as withheld rather than as a nameless tool', async () => {
    // A customer's copy. `withheld` is what stops a surface rendering the
    // empty string as the tool's actual name.
    const { events } = await collect([
      ['invoked', { node: 'agent', name: '', callId: '', withheld: true }],
      DONE,
    ]);

    expect(events[0]).toMatchObject({ type: 'invoked', name: '', callId: '', withheld: true });
  });

  it('falls back to the reporting node when no active node was named', async () => {
    const { events } = await collect([['invoked', { node: 'agent', name: 'q' }], DONE]);

    expect(events[0]).toMatchObject({ activeNode: 'agent' });
  });
});

describe('what the run cost', () => {
  it('is read off the finished frame, one row per model', async () => {
    const { outcome } = await collect([
      [
        'done',
        {
          answer: 'Rock.',
          decisions: {},
          outputs: {},
          attempts: 0,
          mermaid: '',
          usage: [
            { model: 'gpt-oss:120b-cloud', inputTokens: 1436, outputTokens: 86, totalTokens: 1522 },
            { model: 'claude-haiku', inputTokens: 12, outputTokens: 3, totalTokens: 15 },
          ],
        },
      ],
    ]);

    expect(outcome).toMatchObject({
      ok: true,
      value: {
        usage: [
          { model: 'gpt-oss:120b-cloud', inputTokens: 1436, outputTokens: 86, totalTokens: 1522 },
          { model: 'claude-haiku', inputTokens: 12, outputTokens: 3, totalTokens: 15 },
        ],
      },
    });
  });

  it('is read off a failed run too, which is the half most easily lost', async () => {
    const { events } = await collect([
      [
        'error',
        {
          threadId: 't',
          detail: 'the provider hung up',
          usage: [{ model: 'm', inputTokens: 10, outputTokens: 0, totalTokens: 10 }],
        },
      ],
    ]);

    expect(events[0]).toMatchObject({
      type: 'error',
      usage: [{ model: 'm', inputTokens: 10, outputTokens: 0, totalTokens: 10 }],
    });
  });

  it('keeps "not for you" and "no model was called" apart', async () => {
    const withheld = await collect([['error', { threadId: 't', detail: 'x', usage: null }]]);
    const nothing = await collect([['error', { threadId: 't', detail: 'x', usage: [] }]]);

    expect(withheld.events[0]).toMatchObject({ usage: null });
    expect(nothing.events[0]).toMatchObject({ usage: [] });
  });

  it('reads a missing block as no claim, never as a run that cost nothing', async () => {
    // A backend that predates the field, which must not be reported as a free
    // run — the same rule `TokenUsage` follows one level down.
    const { events } = await collect([['error', { threadId: 't', detail: 'x' }]]);

    expect(events[0]).toMatchObject({ usage: null });
  });

  it('reads a malformed row as zeroes rather than dropping the whole list', async () => {
    const { events } = await collect([
      ['error', { threadId: 't', detail: 'x', usage: [{ model: 'm', inputTokens: 'lots' }] }],
    ]);

    expect(events[0]).toMatchObject({
      usage: [{ model: 'm', inputTokens: 0, outputTokens: 0, totalTokens: 0 }],
    });
  });
});
