import { describe, expect, it } from 'vitest';
import { MCP_STATUSES } from '@core/runtime/McpRegistryClient';
import {
  McpStatusMemory,
  describeMcpStatus,
  mcpStatusTone,
  type McpStatusRecord,
} from './mcpServerStatus';

const record = (over: Partial<McpStatusRecord> = {}): McpStatusRecord => ({
  status: 'live',
  message: 'Docs by LangChain answered with 3 tools.',
  tools: ['search_docs_by_lang_chain'],
  checkedAt: 1_760_000_000_000,
  ...over,
});

class FakeStorage {
  readonly items = new Map<string, string>();
  getItem(key: string) {
    return this.items.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.items.set(key, value);
  }
  removeItem(key: string) {
    this.items.delete(key);
  }
}

describe('the four badges', () => {
  it('has a distinct word for every status the runtime can return', () => {
    // The research's taxonomy is four messages, and they are four because each
    // sends a developer somewhere different: a network, a credential, a URL.
    const words = MCP_STATUSES.map((status) => describeMcpStatus(status).label);
    expect(new Set(words).size).toBe(MCP_STATUSES.length);
  });

  it('says what each verdict means in the research’s own words', () => {
    expect(describeMcpStatus('unreachable').detail).toBe('Nothing answered at that address.');
    expect(describeMcpStatus('auth_required').detail).toBe(
      'The server answered, but rejected the credential.',
    );
    expect(describeMcpStatus('not_mcp').detail).toBe(
      'Something answered, but it does not speak MCP.',
    );
  });

  it('paints only a live server green', () => {
    expect(mcpStatusTone('live')).toBe('success');
    expect(mcpStatusTone('unreachable')).toBe('danger');
    expect(mcpStatusTone('auth_required')).toBe('danger');
    expect(mcpStatusTone('not_mcp')).toBe('danger');
  });
});

describe('what this browser remembers about a server', () => {
  it('carries a verdict across a reload, keyed by name', () => {
    const storage = new FakeStorage();
    const memory = new McpStatusMemory(storage);

    memory.remember('LangChain docs', record());

    expect(new McpStatusMemory(storage).recall('LangChain docs')?.status).toBe('live');
    expect(new McpStatusMemory(storage).recall('Never checked')).toBeNull();
  });

  it('keeps the tool names, which are the answer a Validate press was for', () => {
    const storage = new FakeStorage();
    new McpStatusMemory(storage).remember('LangChain docs', record());

    expect(new McpStatusMemory(storage).recall('LangChain docs')?.tools).toEqual([
      'search_docs_by_lang_chain',
    ]);
  });

  it('forgets a server that has been deleted rather than leaving a badge behind', () => {
    const storage = new FakeStorage();
    const memory = new McpStatusMemory(storage);
    memory.remember('Internal docs', record());

    memory.forget('Internal docs');

    expect(memory.recall('Internal docs')).toBeNull();
  });

  it('remembers nothing at all when there is no storage to remember in', () => {
    // Private mode, a sandboxed frame: the panel still works, it simply
    // re-checks on open — which it does anyway.
    const memory = new McpStatusMemory(null);
    memory.remember('LangChain docs', record());
    expect(memory.recall('LangChain docs')).toBeNull();
  });

  it('drops a remembered verdict it cannot read rather than throwing', () => {
    const storage = new FakeStorage();
    storage.setItem('openstategraph.mcpStatus', '{not json');

    expect(new McpStatusMemory(storage).recall('LangChain docs')).toBeNull();
  });

  it('rounds a stored status it does not recognise towards the failing badge', () => {
    const storage = new FakeStorage();
    storage.setItem(
      'openstategraph.mcpStatus',
      JSON.stringify({ 'LangChain docs': { status: 'green-ish', message: '', tools: [] } }),
    );

    expect(new McpStatusMemory(storage).recall('LangChain docs')?.status).toBe('not_mcp');
  });
});
