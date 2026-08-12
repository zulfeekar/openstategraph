import { describe, expect, it, vi } from 'vitest';
import {
  WorkflowFileClient,
  type CatalogueChange,
  type EventSourceLike,
  type FetchLike,
} from './WorkflowFileClient';

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const stubFetch = (
  response: Response,
): { fetch: FetchLike; calls: { url: string; init?: RequestInit }[] } => {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchImpl: FetchLike = (url, init) => {
    calls.push({ url, init });
    return Promise.resolve(response.clone());
  };
  return { fetch: fetchImpl, calls };
};

/**
 * There is no `slugify` test here any more, and no `slugify` either (ticket
 * 20). The editor does not derive a slug from a name — it asks the backend to
 * mint one, because only the backend can see which names are already taken.
 */
describe('WorkflowFileClient.create', () => {
  it('posts the name and document and returns the slug the backend minted', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'my-workflow-k7m3qp', document: {} }, 201));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.create('My Workflow', { nodes: [] });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Not `my-workflow`: the name collided, and the answer came from the only
    // place that could know that.
    expect(result.value).toBe('my-workflow-k7m3qp');
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows');
    expect(stub.calls[0]!.init?.method).toBe('POST');
    expect(JSON.parse(String(stub.calls[0]!.init?.body))).toEqual({
      name: 'My Workflow',
      document: { nodes: [] },
    });
  });

  it('fails loudly when the response names no slug', async () => {
    const stub = stubFetch(jsonResponse({ document: {} }, 201));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.create('My Workflow', {});

    // Silence here would leave the editor holding no identity for a workflow
    // that now exists on disk — and the next save would try to create it again.
    expect(result.ok).toBe(false);
  });

  it('reports the backend detail rather than a bare status', async () => {
    const stub = stubFetch(jsonResponse({ detail: 'no free directory' }, 507));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.create('My Workflow', {});

    expect(result).toEqual({ ok: false, error: 'no free directory' });
  });
});

describe('WorkflowFileClient.list', () => {
  it('maps the snake_case backend fields to camelCase', async () => {
    const stub = stubFetch(
      jsonResponse([
        { slug: 'a', name: 'A', saved_at: 't', node_count: 2, edge_count: 1, published: false },
      ]),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.list();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toEqual([
      {
        slug: 'a',
        name: 'A',
        savedAt: 't',
        nodeCount: 2,
        edgeCount: 1,
        published: false,
        hidden: false,
      },
    ]);
    // The editor sees everything, drafts included — its surface is explicit.
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows?surface=editor');
  });

  it('treats a row without the published field as published (pre-lifecycle backend)', async () => {
    const stub = stubFetch(
      jsonResponse([{ slug: 'a', name: 'A', saved_at: 't', node_count: 0, edge_count: 0 }]),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.list();
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value[0]!.published).toBe(true);
  });

  it('is a failure, not a crash, when nothing is listening', async () => {
    const client = new WorkflowFileClient('http://rt', () => Promise.reject(new Error('down')));
    const result = await client.list();
    expect(result.ok).toBe(false);
  });
});

/**
 * Ticket 21: existence, asked separately from visibility. `list()` is a
 * surface and omits hidden packages; this asks the backend about one slug, so
 * "not advertised" and "not there" stop being the same answer.
 */
describe('WorkflowFileClient.summary', () => {
  it('asks about the one slug, and reports a hidden workflow as existing', async () => {
    const stub = stubFetch(
      jsonResponse({
        slug: 'concierge',
        name: 'Concierge (gateway)',
        saved_at: 't',
        node_count: 15,
        edge_count: 17,
        published: true,
        hidden: true,
      }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.summary('concierge');

    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/concierge/summary');
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value?.hidden).toBe(true);
    expect(result.value?.savedAt).toBe('t');
  });

  it('a 404 is an answer — null, not an error', async () => {
    const client = new WorkflowFileClient('http://rt', () =>
      Promise.resolve(new Response('{}', { status: 404 })),
    );
    const result = await client.summary('gone');
    expect(result).toEqual({ ok: true, value: null });
  });

  it('an unreachable backend stays an error, so a blip is never read as a deletion', async () => {
    const client = new WorkflowFileClient('http://rt', () => Promise.reject(new Error('down')));
    const result = await client.summary('a');
    expect(result.ok).toBe(false);
  });

  it('a 500 stays an error too — "I could not ask" is not "the answer is no"', async () => {
    const client = new WorkflowFileClient('http://rt', () =>
      Promise.resolve(new Response('{}', { status: 500 })),
    );
    const result = await client.summary('a');
    expect(result.ok).toBe(false);
  });
});

describe('WorkflowFileClient.setPublished', () => {
  it('POSTs the flag to the publish endpoint', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'my-flow', published: true, note: 'n' }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.setPublished('my-flow', true);

    expect(result.ok).toBe(true);
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/my-flow/publish');
    expect(stub.calls[0]!.init?.method).toBe('POST');
    expect(JSON.parse(stub.calls[0]!.init?.body as string)).toEqual({ published: true });
  });

  it('reports a 404 plainly', async () => {
    const stub = stubFetch(jsonResponse({ detail: "No workflow named 'x'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.setPublished('x', false);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("No workflow named 'x'");
  });
});

describe('WorkflowFileClient.save', () => {
  it('PUTs to the slug-specific path with name and document', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'my-flow', document: {} }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    await client.save('my-flow', 'My Flow', { nodes: [], edges: [] });

    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/my-flow');
    expect(stub.calls[0]!.init?.method).toBe('PUT');
    const body = JSON.parse(stub.calls[0]!.init?.body as string);
    expect(body).toEqual({ name: 'My Flow', document: { nodes: [], edges: [] } });
  });

  it('url-encodes the slug', async () => {
    const stub = stubFetch(jsonResponse({}));
    const client = new WorkflowFileClient('http://rt', stub.fetch);
    await client.save('a b', 'x', {});
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/a%20b');
  });
});

describe('WorkflowFileClient.load', () => {
  it('returns the document', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'x', document: { nodes: [1], edges: [] } }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.load('x');
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toEqual({ nodes: [1], edges: [] });
  });

  it('reports a 404 plainly', async () => {
    const stub = stubFetch(jsonResponse({ detail: "No workflow named 'x'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.load('x');
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("No workflow named 'x'");
  });
});

describe('WorkflowFileClient.loadIfPresent', () => {
  it('returns the document when it exists', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'x', document: { nodes: [1] } }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.loadIfPresent('x');
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toEqual({ nodes: [1] });
  });

  it('treats a 404 as an answer, not a failure', async () => {
    const stub = stubFetch(jsonResponse({ detail: "No workflow named 'x'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.loadIfPresent('x');
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toBeNull();
  });

  it('still fails when the runtime is unreachable', async () => {
    const client = new WorkflowFileClient('http://rt', () => Promise.reject(new Error('down')));
    const result = await client.loadIfPresent('x');
    expect(result.ok).toBe(false);
  });
});

describe('WorkflowFileClient.remove', () => {
  it('DELETEs the slug-specific path', async () => {
    const stub = stubFetch(new Response(null, { status: 204 }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.remove('my-flow');

    expect(result.ok).toBe(true);
    expect(stub.calls[0]!.init?.method).toBe('DELETE');
  });
});

describe('WorkflowFileClient.capabilities', () => {
  it('maps the snake_case tool fields to camelCase', async () => {
    const stub = stubFetch(
      jsonResponse({
        tools: [
          {
            id: 'chinook-assistant/tools.ListTablesTool',
            name: 'chinook_list_tables',
            description: 'Lists tables.',
            args_schema: { type: 'object', properties: {} },
            node_type: 'tool.chinook-get-all-tables',
          },
        ],
        functions: [],
      }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.capabilities('chinook-assistant');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tools).toEqual([
      {
        id: 'chinook-assistant/tools.ListTablesTool',
        name: 'chinook_list_tables',
        description: 'Lists tables.',
        argsSchema: { type: 'object', properties: {} },
        // Ticket 32: this field is what stops discovery minting a second,
        // differently-described card for a tool that already has one. It was
        // read by `isAlreadyHandAuthored` but never parsed here, so it was
        // `undefined` at runtime and the guard could never fire.
        nodeType: 'tool.chinook-get-all-tables',
      },
    ]);
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/chinook-assistant/capabilities');
  });

  it('reads a missing node_type as "no card declared" rather than undefined', async () => {
    const stub = stubFetch(
      jsonResponse({
        tools: [{ id: 'w/tools.Solo', name: 'solo', description: '', args_schema: {} }],
        functions: [],
      }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.capabilities('w');

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.tools[0]?.nodeType).toBe('');
  });

  it('is an empty list, not a crash, for a workflow with no tools folder', async () => {
    const stub = stubFetch(jsonResponse({ tools: [], functions: [] }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.capabilities('empty-workflow');

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.tools).toEqual([]);
  });

  it('is a failure, not a crash, for an unsaved workflow with no folder at all', async () => {
    const stub = stubFetch(jsonResponse({ detail: "No workflow named 'x'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.capabilities('x');

    expect(result.ok).toBe(false);
  });
});

describe('the base URL a real page gets', () => {
  it('is same-origin relative in a production bundle, so any port works', async () => {
    vi.stubEnv('DEV', false);
    const stub = stubFetch(jsonResponse([]));

    await new WorkflowFileClient(undefined, stub.fetch).list();

    expect(stub.calls[0]!.url).toBe('/api/workflows?surface=editor');
    vi.unstubAllEnvs();
  });

  it('keeps the explicit cross-origin dev backend under Vite', async () => {
    vi.stubEnv('DEV', true);
    const stub = stubFetch(jsonResponse([]));

    await new WorkflowFileClient(undefined, stub.fetch).list();

    expect(stub.calls[0]!.url).toBe('http://localhost:8000/api/workflows?surface=editor');
    vi.unstubAllEnvs();
  });
});

describe('WorkflowFileClient.watchCatalogue', () => {
  /** A stand-in for `EventSource`, which Vitest's node environment lacks. */
  const fakeSource = () => {
    const listeners = new Map<string, (event: MessageEvent) => void>();
    let closed = false;
    const source: EventSourceLike = {
      addEventListener: (type, listener) => listeners.set(type, listener),
      close: () => {
        closed = true;
      },
    };
    return {
      factory: (url: string) => {
        urls.push(url);
        return source;
      },
      emit: (data: string) => listeners.get('workflows.changed')?.({ data } as MessageEvent),
      isClosed: () => closed,
      listens: () => [...listeners.keys()],
    };
  };
  const urls: string[] = [];

  it('subscribes to the runtime event stream', () => {
    const fake = fakeSource();
    urls.length = 0;

    new WorkflowFileClient(
      'http://rt',
      stubFetch(jsonResponse([])).fetch,
      fake.factory,
    ).watchCatalogue(() => {});

    expect(urls).toEqual(['http://rt/api/events']);
    expect(fake.listens()).toEqual(['workflows.changed']);
  });

  it('maps the snake_case event to a change', () => {
    const fake = fakeSource();
    const seen: CatalogueChange[] = [];
    new WorkflowFileClient(
      'http://rt',
      stubFetch(jsonResponse([])).fetch,
      fake.factory,
    ).watchCatalogue((change) => seen.push(change));

    fake.emit(JSON.stringify({ reason: 'published', slug: 'billing', surface_visible: true }));

    expect(seen).toEqual([{ reason: 'published', slug: 'billing', surfaceVisible: true }]);
  });

  it('survives a frame it cannot parse rather than tearing the stream down', () => {
    const fake = fakeSource();
    const seen: CatalogueChange[] = [];
    new WorkflowFileClient(
      'http://rt',
      stubFetch(jsonResponse([])).fetch,
      fake.factory,
    ).watchCatalogue((change) => seen.push(change));

    fake.emit('not json');
    fake.emit(JSON.stringify({ reason: 'deleted', slug: 'gone', surface_visible: false }));

    expect(seen).toEqual([{ reason: 'deleted', slug: 'gone', surfaceVisible: false }]);
    expect(fake.isClosed()).toBe(false);
  });

  it('closes the connection when the caller unsubscribes', () => {
    const fake = fakeSource();
    const stop = new WorkflowFileClient(
      'http://rt',
      stubFetch(jsonResponse([])).fetch,
      fake.factory,
    ).watchCatalogue(() => {});

    expect(fake.isClosed()).toBe(false);
    stop();
    expect(fake.isClosed()).toBe(true);
  });

  it('degrades to a no-op where EventSource does not exist', () => {
    // The whole feature is additive: a browser (or a test) without
    // `EventSource` must keep the panel working exactly as before.
    const stop = new WorkflowFileClient(
      'http://rt',
      stubFetch(jsonResponse([])).fetch,
      null,
    ).watchCatalogue(() => {
      throw new Error('nothing can arrive');
    });

    expect(() => stop()).not.toThrow();
  });
});

describe('WorkflowFileClient.templates', () => {
  it('asks the backend to render the templates for this workflow name', async () => {
    const stub = stubFetch(
      jsonResponse([
        { name: 'minimal', summary: 'input to agent to output.', document: { version: 2 } },
      ]),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.templates('My Flow');

    expect(stub.calls[0]?.url).toBe('http://rt/api/templates?name=My%20Flow');
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toEqual([
        { name: 'minimal', summary: 'input to agent to output.', document: { version: 2 } },
      ]);
    }
  });

  it('reports an unreachable runtime rather than throwing', async () => {
    const client = new WorkflowFileClient('http://rt', () => Promise.reject(new Error('down')));

    const result = await client.templates('x');

    expect(result.ok).toBe(false);
  });

  it('reports a backend too old to know the endpoint', async () => {
    const stub = stubFetch(jsonResponse({ detail: 'Not Found' }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.templates('x');

    expect(result.ok).toBe(false);
  });
});

describe('WorkflowFileClient.sqlSchema', () => {
  it('reads the tables the wired database actually has', async () => {
    const stub = stubFetch(
      jsonResponse({
        sources: [
          {
            database: 'chinook-assistant/data/Chinook_Sqlite.sqlite',
            engine: 'sqlite',
            tables: [{ name: 'Genre', detail: '## Columns\n- GenreId (INTEGER) PRIMARY KEY' }],
            warning: '',
          },
        ],
      }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.sqlSchema('chinook-assistant');

    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/chinook-assistant/sql-schema');
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value[0]?.engine).toBe('sqlite');
    expect(result.value[0]?.tables.map((t) => t.name)).toEqual(['Genre']);
  });

  it('is an empty list, not a crash, for a workflow with no database', async () => {
    const stub = stubFetch(jsonResponse({ sources: [] }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.sqlSchema('dry-flow');

    expect(result.ok && result.value).toEqual([]);
  });

  it('reports an unreachable runtime rather than throwing', async () => {
    const client = new WorkflowFileClient('http://rt', () => Promise.reject(new Error('down')));

    const result = await client.sqlSchema('chinook-assistant');

    expect(result.ok).toBe(false);
  });
});
