import { describe, expect, it } from 'vitest';
import { appendToolChunk, type ToolResult } from './toolResults';

const NONE: readonly ToolResult[] = [];

describe('appendToolChunk', () => {
  it('records a tool result under the tool that returned it', () => {
    const out = appendToolChunk(NONE, {
      toolName: 'list_all_tables',
      toolCallId: 'call_1',
      content: '| Table | Rows |\n| Album | 347 |',
    });

    expect(out).toEqual([
      { callId: 'call_1', tool: 'list_all_tables', text: '| Table | Rows |\n| Album | 347 |' },
    ]);
  });

  it('joins chunks of one result rather than listing them separately', () => {
    const first = appendToolChunk(NONE, {
      toolName: 'list_all_tables',
      toolCallId: 'call_1',
      content: '| Album | 347 |\n',
    });
    const out = appendToolChunk(first, {
      toolName: 'list_all_tables',
      toolCallId: 'call_1',
      content: '| Artist | 275 |',
    });

    expect(out).toHaveLength(1);
    expect(out[0]?.text).toBe('| Album | 347 |\n| Artist | 275 |');
  });

  // The reason the call id is carried at all: an agent reading two schemas
  // calls one tool twice, and on the name alone the second result would be
  // appended to the first — one card claiming to be both tables.
  it('keeps two calls to the same tool apart', () => {
    const first = appendToolChunk(NONE, {
      toolName: 'get_table_schema',
      toolCallId: 'call_1',
      content: '## Invoice',
    });
    const out = appendToolChunk(first, {
      toolName: 'get_table_schema',
      toolCallId: 'call_2',
      content: '## InvoiceLine',
    });

    expect(out.map((r) => r.text)).toEqual(['## Invoice', '## InvoiceLine']);
  });

  // A backend that predates the tagging sends neither id nor name. Coalescing
  // on the previous entry is the best available guess and beats emitting one
  // card per streamed fragment.
  it('coalesces on the previous entry when no call id is supplied', () => {
    const first = appendToolChunk(NONE, { toolName: '', toolCallId: '', content: 'a' });
    const out = appendToolChunk(first, { toolName: '', toolCallId: '', content: 'b' });

    expect(out).toHaveLength(1);
    expect(out[0]?.text).toBe('ab');
  });

  it('does not mutate the list it was given', () => {
    const first = appendToolChunk(NONE, { toolName: 't', toolCallId: 'c1', content: 'a' });
    const out = appendToolChunk(first, { toolName: 't', toolCallId: 'c1', content: 'b' });

    expect(first[0]?.text).toBe('a');
    expect(out).not.toBe(first);
  });

  it('falls back to a readable label when the tool is unnamed', () => {
    const out = appendToolChunk(NONE, { toolName: '', toolCallId: 'c1', content: 'x' });
    expect(out[0]?.tool).toBe('tool');
  });
});
