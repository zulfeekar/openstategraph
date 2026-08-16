import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  MCP_SERVER_TYPE,
  createMcpServerNode,
  mcpServerExecutor,
  mcpServerNode,
  type McpServerNodeModel,
} from './McpServerNode';
import {
  AUTH_BEARER,
  AUTH_NONE,
  DEFAULT_MCP_SERVER_NAMES,
  MCP_FIELD,
  MCP_GROUPING_GUIDE,
  MCP_LOCKED_NOTE,
  TRANSPORT_HTTP,
  TRANSPORT_SSE,
  mcpServerFields,
  mcpServerRowFields,
  parseToolFilter,
  validateEnvVarName,
} from './mcpServerFields';
import { CATEGORY, PORT } from '../vocabulary';
import { defaultsFrom, resolveOptions } from '@core/model/contracts/fields';
import { mcpServerCatalogue } from '@core/runtime/mcpServerCatalogue';
import type { McpServer } from '@core/runtime/McpRegistryClient';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * `tool.mcp` — mcp-connect ticket 02, built through `skills/atom-forge` as
 * its third live client; N servers per card since ticket 04.
 *
 * What these tests pin is the **seam** and the **rules that only exist here**:
 * the id string `prebuilt_mcp.py` is keyed by, the keys its `configure()`
 * reads — three on the node and seven inside a row — the port, and the
 * promises the card makes about credentials and about what a second row costs.
 * Everything the atom *does* — discovery, filtering, the failure sentences,
 * which row a warning names — is asserted in
 * `backend/tests/test_prebuilt_mcp.py`, where the connection is; asserting it
 * twice in two languages is the duplication this repository's DRY rule names.
 */
/** A node-level field. Everything describing a *server* is a row field now. */
const field = (key: string) => mcpServerNode.fields.find((f) => f.key === key);

const serversField = () => {
  const schema = field(MCP_FIELD.servers);
  if (schema?.kind !== 'repeatable-group') throw new Error('tool.mcp has no server rows');
  return schema;
};

/** One row's control, by key — the shared field set, in its row container. */
const rowField = (key: string) => serversField().fields.find((f) => f.key === key);

/** Node data as the card writes it: N server rows. */
const withRows = (...rows: Array<Record<string, unknown>>) => ({
  [MCP_FIELD.servers]: rows.map((row, index) => ({ id: `r${index}`, ...row })),
});

/** Every data key this node owns — graph-assembly overrides subtracted. */
const GRAPH_ASSEMBLY_KEYS = ['maxRetries', 'timeoutSeconds'];
const ownFieldKeys = () =>
  Object.keys(defaultsFrom(mcpServerNode.fields)).filter(
    (key) => !GRAPH_ASSEMBLY_KEYS.includes(key),
  );

const placed = (data: Record<string, unknown> = {}) => {
  const workbench = makeWorkbench();
  workbench.controller.nodes.add(MCP_SERVER_TYPE, { x: 0, y: 0 });
  const node = workbench.model
    .nodes()
    .find((n) => n.type === MCP_SERVER_TYPE) as McpServerNodeModel;
  for (const [key, value] of Object.entries(data)) {
    workbench.controller.nodes.setField(node.id, key, value as never);
  }
  return workbench.model.nodes().find((n) => n.id === node.id) as McpServerNodeModel;
};

describe('the seam the Python tool is keyed by', () => {
  it('answers to the one node type the registry holds', () => {
    expect(MCP_SERVER_TYPE).toBe('tool.mcp');
    expect(mcpServerNode.id).toBe(MCP_SERVER_TYPE);
  });

  it('declares exactly the keys the node itself carries', () => {
    // A `data` key no field declares reads "" forever, silently. The Python
    // side pins the same three in `MCP_NODE_KEYS`, and
    // `test_mcp_field_contract.py` compares the two lists.
    //
    // `maxRetries` and `timeoutSeconds` are subtracted because `defineNode`
    // puts them on *every* node: they are `StateGraph.add_node` parameters,
    // which CLAUDE.md places on the workflow rather than on any family, so
    // they are not this atom's to declare or to mirror.
    expect(ownFieldKeys().sort()).toEqual(
      [MCP_FIELD.servers, MCP_FIELD.guide, MCP_FIELD.note].sort(),
    );
  });

  it('describes a server inside a row, in the seven keys Python reads there', () => {
    expect(
      serversField()
        .fields.map((f) => f.key)
        .sort(),
    ).toEqual(
      [
        MCP_FIELD.authHeaderName,
        MCP_FIELD.authKind,
        MCP_FIELD.authTokenEnv,
        MCP_FIELD.server,
        MCP_FIELD.tools,
        MCP_FIELD.transport,
        MCP_FIELD.url,
      ].sort(),
    );
  });

  it('is a tool atom with one tool port', () => {
    expect(mcpServerNode.category).toBe(CATEGORY.tools);
    const ports = mcpServerNode.ports(defaultsFrom(mcpServerNode.fields));
    expect(ports.map((p) => p.id)).toEqual(['tool']);
    expect(ports[0]?.type).toBe(PORT.tool);
    expect(ports[0]?.direction).toBe('out');
  });

  it('leaves cardinality to the agent’s bus, declaring none of its own', () => {
    // How many agents one MCP node may serve is the *bus's* maxConnections.
    // A node-level flag here would be a second answer to a question the port
    // rules already settle.
    const [tool] = mcpServerNode.ports(defaultsFrom(mcpServerNode.fields));
    expect(tool?.maxConnections).toBeUndefined();
  });

  it('starts with one empty row, defaulting to HTTP with no authentication', () => {
    // One row rather than zero: a placed card is something to fill in, not
    // something you must first discover has a button.
    const [row] = defaultsFrom(mcpServerNode.fields)[MCP_FIELD.servers] as Array<
      Record<string, unknown>
    >;
    expect(row?.[MCP_FIELD.transport]).toBe(TRANSPORT_HTTP);
    expect(row?.[MCP_FIELD.authKind]).toBe(AUTH_NONE);
    expect(row?.[MCP_FIELD.tools]).toBe('');
    expect(row?.id).toBeTruthy();
  });
});

describe('the field set is shared, not fused into this card', () => {
  it('is a factory the app-level panel can call for itself', () => {
    // Ticket 03 renders the same controls for a project-wide server. Two
    // hand-built copies of "what an MCP server is" is duplicated knowledge,
    // and it drifts the first time a fourth auth type appears.
    const panelFields = mcpServerFields({ includeServerPicker: false });
    expect(panelFields.map((f) => f.key)).not.toContain(MCP_FIELD.server);
    expect(panelFields.map((f) => f.key)).toContain(MCP_FIELD.authTokenEnv);
  });

  it('renders each row from the panel’s own schemas, control for control', () => {
    // Not "the same keys" — the same schemas, options, hints and validators.
    // A row is the panel's field set in a different container, so a fourth
    // auth type or a reworded hint reaches both places or neither. Compared
    // by value rather than by reference only because the factory deliberately
    // mints fresh objects per call (its options resolve lazily); a copied
    // declaration would still fail here the moment either side changed.
    const panel = new Map(mcpServerFields().map((schema) => [schema.key, schema]));
    for (const rowSchema of mcpServerRowFields()) {
      // The one control that cannot travel as it is: a `repeatable-group`
      // inside a row would be a table inside a table.
      if (rowSchema.key === MCP_FIELD.tools) continue;
      expect(rowSchema, `row field ${rowSchema.key} is not the panel's own`).toEqual(
        panel.get(rowSchema.key),
      );
    }
  });

  it('spells the tool filter as one line in a row and a table in the panel', () => {
    expect(mcpServerFields().find((f) => f.key === MCP_FIELD.tools)?.kind).toBe('repeatable-group');
    expect(rowField(MCP_FIELD.tools)?.kind).toBe('text');
    // Both are read as the same thing, in both languages.
    expect(parseToolFilter('search_docs, get_symbol')).toEqual(['search_docs', 'get_symbol']);
    expect(parseToolFilter([{ name: 'search_docs' }, { name: '  ' }])).toEqual(['search_docs']);
    expect(parseToolFilter('  ,  ')).toEqual([]);
  });

  describe('the picker offers what the panel registered', () => {
    // The assertion that used to live here — `toEqual([...DEFAULT_MCP_SERVER_NAMES])`
    // against the default declaration — was green while the picker showed the
    // same two names in every project on every install, including after one of
    // the two had been deleted in the panel. It was pinning the fallback and
    // calling it the behaviour (mcp-connect ticket 07).
    const server = (name: string): McpServer => ({
      name,
      url: `https://${name}.test/mcp`,
      transport: 'streamable_http',
      auth: { kind: 'none', headerName: '', tokenEnv: '' },
      origin: 'project',
      credentialConfigured: false,
    });
    const offered = () =>
      resolveOptions(rowField(MCP_FIELD.server) as never, {}).map((o) => o.value);

    afterEach(() => mcpServerCatalogue.reset());

    it('falls back to the built-ins only until the registry has answered', () => {
      expect(rowField(MCP_FIELD.server)?.kind).toBe('combobox');
      expect(offered()).toEqual([...DEFAULT_MCP_SERVER_NAMES]);
    });

    it('offers a server registered in the panel, on the registered declaration', () => {
      // The one the ticket was filed against: register `Needs auth`, drop a
      // card, open the picker. Read off `mcpServerNode` — the definition
      // `nodes/index.ts` actually registers — because the factory taking an
      // explicit thunk was always correct and never called.
      mcpServerCatalogue.set([server('LangChain docs'), server('Needs auth')]);
      expect(offered()).toEqual(['LangChain docs', 'Needs auth']);
    });

    it('stops offering a built-in the panel tombstoned', () => {
      mcpServerCatalogue.set([server('LangChain API reference')]);
      expect(offered()).not.toContain('LangChain docs');
    });

    it('an empty registry is empty, not the two defaults again', () => {
      mcpServerCatalogue.set([]);
      expect(offered()).toEqual([]);
    });

    it('tells the renderer which store to redraw on', () => {
      // Without this the list is only right when the inspector happens to
      // re-render for some other reason — which is "needs a reload" wearing a
      // different hat.
      const picker = rowField(MCP_FIELD.server);
      const notify = vi.fn();
      const stop = (picker as { subscribe?: (n: () => void) => () => void }).subscribe?.(notify);
      mcpServerCatalogue.set([server('Needs auth')]);
      expect(notify).toHaveBeenCalled();
      stop?.();
    });
  });

  it('resolves a live server list lazily, so a new one needs no reload', () => {
    let registered = ['Internal wiki'];
    const definition = createMcpServerNode(() =>
      registered.map((name) => ({ value: name, label: name })),
    );
    const group = definition.fields.find((f) => f.key === MCP_FIELD.servers);
    const picker =
      group?.kind === 'repeatable-group'
        ? group.fields.find((f) => f.key === MCP_FIELD.server)
        : undefined;

    expect(resolveOptions(picker as never, {}).map((o) => o.value)).toEqual(['Internal wiki']);
    registered = ['Internal wiki', 'Vendor API'];
    expect(resolveOptions(picker as never, {}).map((o) => o.value)).toHaveLength(2);
  });

  it('lets a name be typed that is not registered yet', () => {
    // Combobox rather than select: drafting the card before registering the
    // server is a real order of work, and a listbox would outlaw it.
    expect(rowField(MCP_FIELD.server)?.kind).toBe('combobox');
  });

  it('offers HTTP and a labelled-deprecated SSE, and nothing that cannot carry a credential', () => {
    const options = resolveOptions(rowField(MCP_FIELD.transport) as never, {});
    expect(options.map((o) => o.value)).toEqual([TRANSPORT_HTTP, TRANSPORT_SSE]);
    expect(options.find((o) => o.value === TRANSPORT_SSE)?.label).toMatch(/deprecated/i);
    // WebSocket has no headers field at all; stdio names an executable.
    expect(options.map((o) => o.value)).not.toContain('websocket');
    expect(options.map((o) => o.value)).not.toContain('stdio');
  });

  it('offers a custom header as well as a bearer token', () => {
    // Both are load-bearing: LangSmith's own server wants LANGSMITH-API-KEY.
    const kinds = resolveOptions(rowField(MCP_FIELD.authKind) as never, {}).map((o) => o.value);
    expect(kinds).toEqual([AUTH_NONE, AUTH_BEARER, 'header']);
  });
});

describe('a credential can never be typed into this card', () => {
  it('accepts a variable name', () => {
    expect(validateEnvVarName('MY_MCP_TOKEN')).toBeNull();
    expect(validateEnvVarName('_private')).toBeNull();
    expect(validateEnvVarName('')).toBeNull();
  });

  it('refuses what a pasted credential looks like', () => {
    for (const pasted of [
      'sk-live-abcdef123456',
      'ghp_aaaaaaaaaaaaaaaaaaaa',
      'xoxb-1234-5678-abcd',
      '9f3a-c81e-4b2d-a0f1',
      'Bearer abc123',
    ]) {
      expect(validateEnvVarName(pasted), pasted).not.toBeNull();
    }
  });

  it('says what to do instead, not merely that it is wrong', () => {
    expect(validateEnvVarName('sk-live-abc')).toMatch(/\.env/);
  });

  it('has no field a credential value belongs in, at either level', () => {
    const keys = [
      ...mcpServerNode.fields.map((f) => f.key),
      ...serversField().fields.map((f) => f.key),
    ];
    for (const forbidden of ['token', 'apiKey', 'secret', 'password', 'authToken']) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it('refuses a pasted key inside a row, exactly as the flat field does', () => {
    // The row renderer runs the schema's own `validate`, so this is the same
    // function in a different container — not a second rule that can drift.
    const credential = rowField(MCP_FIELD.authTokenEnv);
    expect(credential?.kind).toBe('text');
    expect(credential?.validate?.('ghp_aaaaaaaaaaaaaaaaaaaa' as never)).toMatch(/\.env/);
    expect(credential?.validate?.('MY_MCP_TOKEN' as never)).toBeNull();
  });
});

describe('the machinery is shown, never pre-filled into an editable box', () => {
  it('carries the locked note read-only', () => {
    const note = field(MCP_FIELD.note);
    expect(note?.kind).toBe('readonly');
    expect(note?.defaultValue).toBe(MCP_LOCKED_NOTE);
  });

  it('says the three things the card itself cannot show', () => {
    // Where the credential lives, what an empty filter means, and that half
    // of every call is the handshake. Each is a support thread otherwise.
    expect(MCP_LOCKED_NOTE).toMatch(/environment variable/);
    expect(MCP_LOCKED_NOTE).toMatch(/now and later/);
    expect(MCP_LOCKED_NOTE).toMatch(/0\.8 seconds/);
  });
});

describe('the card says only what the document knows', () => {
  it('reads as unconfigured before anything is picked', () => {
    expect(placed().subtitle).toMatch(/No server yet/);
    expect(placed().rows).toEqual([]);
  });

  it('names the registered server and that nothing is filtered out', () => {
    expect(placed(withRows({ [MCP_FIELD.server]: 'LangChain docs' })).subtitle).toBe(
      'LangChain docs · every tool it offers',
    );
  });

  it('falls back to the URL when a row names no server', () => {
    expect(placed(withRows({ [MCP_FIELD.url]: 'https://vendor.test/mcp' })).subtitle).toBe(
      'https://vendor.test/mcp · every tool it offers',
    );
  });

  it('counts the filter, and never a discovered tool list', () => {
    const node = placed(
      withRows({
        [MCP_FIELD.server]: 'LangChain docs',
        [MCP_FIELD.tools]: 'search_docs, get_symbol',
      }),
    );
    // The number here is the document's, not the server's. A count of what
    // the server offers needs a round trip, so a card showing one would be
    // claiming something it cannot know before a run.
    expect(node.subtitle).toBe('LangChain docs · 2 tools only');
  });

  it('counts the servers once there is more than one, and names the first two', () => {
    const node = placed(
      withRows(
        { [MCP_FIELD.server]: 'LangChain docs' },
        { [MCP_FIELD.server]: 'LangChain API reference' },
        { [MCP_FIELD.url]: 'https://internal.test/mcp' },
      ),
    );
    expect(node.subtitle).toBe('3 servers · LangChain docs, LangChain API reference +1 more');
  });

  it('ignores a row nobody has filled in yet', () => {
    // The card ships with one empty row. It is not a server, and a subtitle
    // that counted it would say "1 server" about nothing.
    const node = placed(withRows({ [MCP_FIELD.server]: 'LangChain docs' }, {}));
    expect(node.rows).toHaveLength(1);
    expect(node.subtitle).toBe('LangChain docs · every tool it offers');
  });

  it('drops blank filter entries in both languages alike', () => {
    const node = placed(
      withRows({ [MCP_FIELD.server]: 'LangChain docs', [MCP_FIELD.tools]: ' , search_docs' }),
    );
    expect(node.rows[0]?.tools).toEqual(['search_docs']);
  });

  it('reads a workflow saved before the card went plural', () => {
    // Compatibility, not migration: opening an old document must neither
    // rewrite it nor lose the server it names. `prebuilt_mcp._server_rows`
    // reads the same two shapes.
    const node = placed({
      [MCP_FIELD.server]: 'LangChain docs',
      [MCP_FIELD.tools]: [{ name: 'search_docs' }],
    });
    expect(node.rows.map((row) => row.target)).toEqual(['LangChain docs']);
    expect(node.rows[0]?.tools).toEqual(['search_docs']);
    expect(node.subtitle).toBe('LangChain docs · 1 tool only');
  });
});

describe('one node per group of servers that share a consumer', () => {
  it('says so on the card, where the second row is added', () => {
    const guide = field(MCP_FIELD.guide);
    expect(guide?.kind).toBe('readonly');
    expect(guide?.onCard ?? true).toBe(true);
    expect(MCP_GROUPING_GUIDE).toMatch(/share a consumer/);
    // The two halves of the trade: what rows buy, and when to use two nodes.
    expect(MCP_GROUPING_GUIDE).toMatch(/two of these nodes/);
  });

  it('offers each row its own live check', () => {
    // The panel's Validate button, per row — same route, same four verdicts.
    expect(serversField().rowProbe?.label).toBe('Check');
  });

  it('keeps the rows off the card and in the inspector', () => {
    // Seven controls times three rows is taller than the canvas. What the
    // card shows is the subtitle and the guidance.
    expect(serversField().onCard).toBe(false);
  });
});

describe('the browser preview refuses rather than being skipped', () => {
  it('registers an executor at all', () => {
    // A node with none is *silently skipped* by the preview engine: the run
    // looks successful and did less than you think. That is the worst
    // available outcome for a docs server, whose job is to stop an agent
    // answering from parametric knowledge.
    expect(mcpServerExecutor.id).toBe(MCP_SERVER_TYPE);
  });

  it('names where the answer actually lives', async () => {
    const result = await mcpServerExecutor.execute({
      node: placed(),
      log: () => {},
    } as never);
    expect(result.ok).toBe(true);
  });

  it('refuses the tool call itself, and says why', async () => {
    const invoke = (mcpServerExecutor as unknown as { invokeTool: () => Promise<unknown> })
      .invokeTool;
    const result = (await invoke()) as { ok: boolean; error: string };
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/browser preview has no connection/);
  });
});
