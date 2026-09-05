import { describe, expect, it, vi } from 'vitest';
import { LiveEventStream, type EventSourceLike } from './LiveEventStream';
import { parseMountAddress } from '@core/model/MountAddress';
import { WorkflowFileClient, type CatalogueChange, type FetchLike } from './WorkflowFileClient';

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
        findings: [],
        // Absent from this row's JSON, and empty rather than `undefined`:
        // "I cannot tell you which version" is what a caller must read it as
        // (`osg-agent-experience/45`), never as "unchanged".
        digest: '',
      },
    ]);
    // The editor sees everything, drafts included — its surface is explicit.
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows?surface=editor');
  });

  /**
   * The package-contract findings (`the-cost-of-one-more/14`). Ticket 49 has
   * published these on every row since it landed and `asSummary` read no such
   * key, so a package with no `workflow.json` — one that cannot run and
   * cannot be opened — listed exactly like a healthy one.
   *
   * Two rows, because the interesting property is per-row: a clean package
   * next to a broken one must not borrow its neighbour's verdict.
   */
  it("carries each row's package-contract findings, and an absent key is a clean row", async () => {
    const stub = stubFetch(
      jsonResponse([
        {
          slug: 'broken',
          name: 'Broken',
          saved_at: 't',
          node_count: 0,
          edge_count: 0,
          findings: ['error: no workflow.json in broken/', 'warning: no AGENTS.md'],
        },
        { slug: 'clean', name: 'Clean', saved_at: 't', node_count: 1, edge_count: 0 },
      ]),
    );

    const result = await new WorkflowFileClient('http://rt', stub.fetch).list();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value[0]!.findings).toEqual([
      'error: no workflow.json in broken/',
      'warning: no AGENTS.md',
    ]);
    // Absent is empty, never undefined: a surface that maps over this must
    // not have to ask whether an older backend answered.
    expect(result.value[1]!.findings).toEqual([]);
  });

  /**
   * Production-ready ticket 33. The docstring used to say this endpoint omits
   * hidden packages; it never did on the editor surface, and it must not start
   * — `WorkflowCatalogue` feeds the mount combobox from `list()`, and the
   * shipped `concierge` mounts `workflow-architect`, which is hidden. A filter
   * here makes a composition we ship undrawable.
   */
  it('keeps hidden packages, marked, because the editor surface owns them', async () => {
    const stub = stubFetch(
      jsonResponse([
        {
          slug: 'workflow-architect',
          name: 'Workflow Architect',
          saved_at: 't',
          node_count: 9,
          edge_count: 8,
          published: true,
          hidden: true,
        },
      ]),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.list();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.map((row) => row.slug)).toEqual(['workflow-architect']);
    expect(result.value[0]!.hidden).toBe(true);
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
 * surface, and a surface omits things that exist — unreadable packages, and
 * hidden ones once the question is asked as `surface=chat`. This asks the
 * backend about one slug, so "not advertised" and "not there" stop being the
 * same answer.
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

  /**
   * `the-cost-of-one-more/18`. The note was dropped on the floor — this
   * method's own docstring named the note it dropped — so a developer
   * published and never learned the concierge would not route to the change.
   * It is carried now, unedited: what it *says* is the surface's problem, and
   * this client's job is not to have an opinion about the wording.
   */
  it('carries the note the publish endpoint answers with', async () => {
    const note = 'Concierge routing knowledge was not rebuilt automatically; rebuild it via …';
    const stub = stubFetch(jsonResponse({ slug: 'my-flow', published: true, note }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.setPublished('my-flow', true);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.note).toBe(note);
  });

  /**
   * **`null`, not `''`.** The absence of a note is the backend saying it has
   * nothing to add — today it always has, but a build that rebuilt routing on
   * publish would send none, and the toast reads exactly this to decide
   * whether to make the claim at all. An empty string would be a note that
   * says nothing, which is a different fact and one no surface can act on.
   */
  it.each([[{ slug: 'f', published: true }], [{ slug: 'f', published: true, note: 42 }]])(
    'reports no note as null rather than as an empty one (%j)',
    async (body) => {
      const client = new WorkflowFileClient('http://rt', stubFetch(jsonResponse(body)).fetch);

      const result = await client.setPublished('f', true);

      expect(result.ok).toBe(true);
      if (result.ok) expect(result.value.note).toBeNull();
    },
  );

  /**
   * A publish whose body cannot be read is still a publish: the flag flipped
   * server-side before the response was written. Failing the call here would
   * make the editor report an error for work that succeeded, which is worse
   * than losing one sentence.
   */
  it('still succeeds, noteless, when the answer is not readable JSON', async () => {
    const client = new WorkflowFileClient(
      'http://rt',
      stubFetch(new Response('not json', { status: 200 })).fetch,
    );

    const result = await client.setPublished('f', true);

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value.note).toBeNull();
  });
});

describe('WorkflowFileClient.duplicate', () => {
  it('POSTs an empty body so the backend names the copy', async () => {
    // The default name is `<original> (copy)`, which depends on the original's
    // name — the backend has it, and a client would have to fetch it first to
    // say the same thing.
    const stub = stubFetch(
      jsonResponse({ slug: 'my-flow-k7m3qp', name: 'My Flow (copy)', source: 'my-flow' }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.duplicate('my-flow');

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toEqual({
        slug: 'my-flow-k7m3qp',
        name: 'My Flow (copy)',
        source: 'my-flow',
      });
    }
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/my-flow/duplicate');
    expect(stub.calls[0]!.init?.method).toBe('POST');
    expect(JSON.parse(stub.calls[0]!.init?.body as string)).toEqual({});
  });

  it('sends a name when the caller supplies one', async () => {
    const stub = stubFetch(
      jsonResponse({ slug: 'experiment', name: 'Experiment', source: 'my-flow' }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    await client.duplicate('my-flow', 'Experiment');

    expect(JSON.parse(stub.calls[0]!.init?.body as string)).toEqual({ name: 'Experiment' });
  });

  it('fails loudly when the answer carries no slug', async () => {
    // The copy exists on disk at this point and the caller cannot name it.
    // Reporting that is better than returning a plausible-looking blank.
    const stub = stubFetch(jsonResponse({ name: 'My Flow (copy)' }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.duplicate('my-flow');

    expect(result.ok).toBe(false);
  });

  it('reports a 404 plainly', async () => {
    const stub = stubFetch(jsonResponse({ detail: "No workflow named 'x'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.duplicate('x');

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
    // `must_exist` on every save, and it is a data-loss guard rather than a
    // detail (launch-readiness 147). `PUT` creates a package at a free slug on
    // purpose, for the CLI and for scripts; for this client that behaviour
    // meant a tab whose workflow another tab had deleted re-created it on the
    // next keystroke, holding `workflow.json` alone while its `tools/` stayed
    // gone. Every save this client makes addresses a package it already holds
    // — a document with no slug goes through `create` — so the flag is true of
    // all of them, and asserted here so it cannot quietly stop being sent.
    expect(body).toEqual({
      name: 'My Flow',
      document: { nodes: [], edges: [] },
      must_exist: true,
    });
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

describe('WorkflowFileClient.loadMount', () => {
  const address = (raw: string) => parseMountAddress(raw)!;

  it('asks the mounts endpoint, one path segment per mount', async () => {
    const stub = stubFetch(
      jsonResponse({ root: 'concierge', slug: 'chinook-assistant', document: {}, warnings: [] }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    await client.loadMount(address('concierge/wf-music/wf-inner'));
    expect(stub.calls[0]!.url).toBe('http://rt/api/workflows/concierge/mounts/wf-music/wf-inner');
  });

  it('encodes each segment without eating the separator', async () => {
    // A minted id is `node:workflow.subgraph-1` — a colon survives a path
    // segment, but encoding the whole path in one go would turn the separator
    // into `%2F` and the route would stop matching.
    const stub = stubFetch(jsonResponse({ root: 'a', slug: 'b', document: {}, warnings: [] }));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    await client.loadMount(address('concierge/node:workflow.subgraph-1'));
    expect(stub.calls[0]!.url).toBe(
      'http://rt/api/workflows/concierge/mounts/node%3Aworkflow.subgraph-1',
    );
  });

  it('returns the class slug beside the document', async () => {
    // The instance is named by the address; the *class* is what capabilities,
    // knowledge and the palette are still asked about.
    const stub = stubFetch(
      jsonResponse({
        root: 'concierge',
        slug: 'chinook-assistant',
        mount_path: ['wf-music'],
        document: { nodes: [1] },
        warnings: ['wf-music: override targets unknown child node "typo"'],
      }),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.loadMount(address('concierge/wf-music'));
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.slug).toBe('chinook-assistant');
      expect(result.value.document).toEqual({ nodes: [1] });
      expect(result.value.warnings).toHaveLength(1);
    }
  });

  it('reports a stale address plainly', async () => {
    // A deleted mount, a renamed node, a bookmark from last week — all 404,
    // and all render the same way: this link no longer points at anything.
    const stub = stubFetch(jsonResponse({ detail: "'concierge' has no node 'wf-gone'" }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.loadMount(address('concierge/wf-gone'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain('wf-gone');
  });

  it('refuses a class address rather than silently fetching the package', async () => {
    // `loadMount` answers about an instance. Handed an address with no mount
    // path it must say so, not quietly become `load` — two spellings of one
    // call is how they drift.
    const stub = stubFetch(jsonResponse({}));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.loadMount(address('concierge'));
    expect(result.ok).toBe(false);
    expect(stub.calls).toHaveLength(0);
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
    // A developer's own `.env.local` (`VITE_RUNTIME_BASE_URL`, documented in
    // runtimeBaseUrl.ts) is ambient to Vitest in every mode. This pins the
    // *default*, so it must not see that value (`the-cost-of-one-more/23`).
    vi.stubEnv('VITE_RUNTIME_BASE_URL', '');
    const stub = stubFetch(jsonResponse([]));

    await new WorkflowFileClient(undefined, stub.fetch).list();

    expect(stub.calls[0]!.url).toBe('/api/workflows?surface=editor');
    vi.unstubAllEnvs();
  });

  it('keeps the explicit cross-origin dev backend under Vite', async () => {
    vi.stubEnv('DEV', true);
    vi.stubEnv('VITE_RUNTIME_BASE_URL', '');
    const stub = stubFetch(jsonResponse([]));

    await new WorkflowFileClient(undefined, stub.fetch).list();

    expect(stub.calls[0]!.url).toBe('http://localhost:8000/api/workflows?surface=editor');
    vi.unstubAllEnvs();
  });
});

describe('WorkflowFileClient.watchCatalogue', () => {
  /**
   * A stand-in for `EventSource`, which Vitest's node environment lacks.
   *
   * Handed to a `LiveEventStream` rather than to the client since
   * `osg-agent-experience/71`: one connection belongs to the tab, not to one
   * client object, so that is the seam a test drives.
   */
  const fakeSource = () => {
    const listeners = new Map<string, (event: MessageEvent) => void>();
    let closed = false;
    const source: EventSourceLike = {
      addEventListener: (type: string, listener: (event: MessageEvent) => void) =>
        listeners.set(type, listener),
      close: () => {
        closed = true;
      },
    };
    const urls: string[] = [];
    return {
      urls,
      live: new LiveEventStream('http://rt', (url: string) => {
        urls.push(url);
        return source;
      }),
      emit: (name: string, data: string) => listeners.get(name)?.({ data } as MessageEvent),
      isClosed: () => closed,
      listens: () => [...listeners.keys()],
    };
  };

  /** The stream reconciles on a microtask — see `LiveEventStream`. */
  const settled = () => Promise.resolve().then(() => {});

  const clientFor = (fake: ReturnType<typeof fakeSource> | null) =>
    new WorkflowFileClient('http://rt', stubFetch(jsonResponse([])).fetch, fake ? fake.live : null);

  it("asks the tab's one connection for the catalogue subject", async () => {
    const fake = fakeSource();

    clientFor(fake).watchCatalogue(() => {});
    await settled();

    expect(fake.urls).toEqual(['http://rt/api/events']);
    expect(fake.listens()).toContain('workflows.changed');
  });

  it('maps the snake_case event to a change', async () => {
    const fake = fakeSource();
    const seen: CatalogueChange[] = [];
    clientFor(fake).watchCatalogue((change) => seen.push(change));
    await settled();

    fake.emit(
      'workflows.changed',
      JSON.stringify({ reason: 'published', slug: 'billing', surface_visible: true }),
    );

    expect(seen).toEqual([{ reason: 'published', slug: 'billing', surfaceVisible: true }]);
  });

  it('survives a frame it cannot parse rather than tearing the stream down', async () => {
    const fake = fakeSource();
    const seen: CatalogueChange[] = [];
    clientFor(fake).watchCatalogue((change) => seen.push(change));
    await settled();

    fake.emit('workflows.changed', 'not json');
    fake.emit(
      'workflows.changed',
      JSON.stringify({ reason: 'deleted', slug: 'gone', surface_visible: false }),
    );

    expect(seen).toEqual([{ reason: 'deleted', slug: 'gone', surfaceVisible: false }]);
    expect(fake.isClosed()).toBe(false);
  });

  it('lets the connection go when the caller unsubscribes', async () => {
    const fake = fakeSource();
    const stop = clientFor(fake).watchCatalogue(() => {});
    await settled();

    expect(fake.isClosed()).toBe(false);
    stop();
    await settled();
    expect(fake.isClosed()).toBe(true);
  });

  it('degrades to a no-op where EventSource does not exist', async () => {
    // The whole feature is additive: a browser (or a test) without
    // `EventSource` must keep the panel working exactly as before.
    const stop = clientFor(null).watchCatalogue(() => {
      throw new Error('nothing can arrive');
    });
    await settled();

    expect(() => stop()).not.toThrow();
  });

  /**
   * `osg-agent-experience/69`'s subject, reaching the editor through `71`.
   *
   * The point of the whole ticket is in the URL: asking for a package's
   * document adds a parameter to the connection this tab already holds
   * rather than opening a second one.
   */
  it('asks for one package on the same connection, and reads its revision', async () => {
    const fake = fakeSource();
    const seen: { slug: string; digest: string }[] = [];
    const client = clientFor(fake);
    client.watchCatalogue(() => {});
    client.watchWorkflow('billing', (change) => seen.push(change));
    await settled();

    expect(fake.urls).toEqual(['http://rt/api/events?slug=billing']);

    fake.emit('workflow.changed', JSON.stringify({ slug: 'billing', digest: 'sha-2' }));
    fake.emit('workflow.changed', JSON.stringify({ slug: 'someone-else', digest: 'sha-9' }));

    expect(seen).toEqual([{ slug: 'billing', digest: 'sha-2' }]);
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

describe('WorkflowFileClient.examples', () => {
  const entry = {
    slug: 'nested-mounts',
    name: 'Nested Mounts',
    summary: 'Composition depth for its own sake.',
    pattern: 'composition depth',
    requires: ['nested-mounts', 'nested-mounts-mid', 'chained-summarizer'],
  };

  it('reads the shipped gallery, and what each example will cost to take', async () => {
    const stub = stubFetch(jsonResponse([entry]));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.examples();

    expect(stub.calls[0]?.url).toBe('http://rt/api/examples');
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toEqual([entry]);
  });

  it('treats an example that names no dependencies as needing only itself', async () => {
    const stub = stubFetch(jsonResponse([{ slug: 'chained-summarizer' }]));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.examples();

    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value[0]?.requires).toEqual(['chained-summarizer']);
  });

  it('reports a backend too old to know the endpoint rather than throwing', async () => {
    const stub = stubFetch(jsonResponse({ detail: 'Not Found' }, 404));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    expect((await client.examples()).ok).toBe(false);
  });
});

describe('WorkflowFileClient.copyExample', () => {
  it('posts to the example and returns every slug the copy wrote', async () => {
    const stub = stubFetch(
      jsonResponse({ slug: 'nested-mounts', copied: ['nested-mounts', 'nested-mounts-mid'] }, 201),
    );
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.copyExample('nested-mounts');

    expect(stub.calls[0]?.url).toBe('http://rt/api/examples/nested-mounts/copy');
    expect(stub.calls[0]?.init?.method).toBe('POST');
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.value).toEqual(['nested-mounts', 'nested-mounts-mid']);
  });

  it('surfaces the refusal when a package of that name is already there', async () => {
    const stub = stubFetch(jsonResponse({ detail: 'already exists' }, 409));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    const result = await client.copyExample('chained-summarizer');

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain('already exists');
  });

  it('refuses to report a copy it cannot name', async () => {
    const stub = stubFetch(jsonResponse({ slug: 'x', copied: [] }, 201));
    const client = new WorkflowFileClient('http://rt', stub.fetch);

    expect((await client.copyExample('x')).ok).toBe(false);
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
