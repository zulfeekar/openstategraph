import { describe, expect, it } from 'vitest';
import { slugify, WorkflowFileClient, type FetchLike } from './WorkflowFileClient';

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

describe('slugify', () => {
  it('lowercases and hyphenates, matching the backend', () => {
    expect(slugify('Chinook Natural Language to SQL')).toBe('chinook-natural-language-to-sql');
  });

  it('falls back rather than producing an empty slug', () => {
    expect(slugify('!!!')).toBe('workflow');
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
      { slug: 'a', name: 'A', savedAt: 't', nodeCount: 2, edgeCount: 1, published: false },
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
            id: 'chinook-nl-to-sql/tools.ListTablesTool',
            name: 'chinook_list_tables',
            description: 'Lists tables.',
            args_schema: { type: 'object', properties: {} },
          },
        ],
        functions: [],
      }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.capabilities('chinook-nl-to-sql');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tools).toEqual([
      {
        id: 'chinook-nl-to-sql/tools.ListTablesTool',
        name: 'chinook_list_tables',
        description: 'Lists tables.',
        argsSchema: { type: 'object', properties: {} },
      },
    ]);
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/chinook-nl-to-sql/capabilities');
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
