import { describe, expect, it } from 'vitest';
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
  MCP_LOCKED_NOTE,
  TRANSPORT_HTTP,
  TRANSPORT_SSE,
  mcpServerFields,
  validateEnvVarName,
} from './mcpServerFields';
import { CATEGORY, PORT } from '../vocabulary';
import { defaultsFrom, resolveOptions } from '@core/model/contracts/fields';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * `tool.mcp` — mcp-connect ticket 02, built through `skills/atom-forge` as
 * its third live client.
 *
 * What these tests pin is the **seam** and the **rules that only exist here**:
 * the id string `prebuilt_mcp.py` is keyed by, the eight field keys its
 * `configure()` reads, the port, and the two promises the card makes about
 * credentials. Everything the atom *does* — discovery, filtering, the six
 * failure sentences — is asserted in `backend/tests/test_prebuilt_mcp.py`,
 * where the connection is; asserting it twice in two languages is the
 * duplication this repository's DRY rule names.
 */
const field = (key: string) => mcpServerNode.fields.find((f) => f.key === key);

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

  it('declares exactly the keys `configure()` reads', () => {
    // A `data` key no field declares reads "" forever, silently. The Python
    // side pins the same eight in `MCP_FIELD_KEYS`, and
    // `test_mcp_field_contract.py` compares the two lists.
    //
    // `maxRetries` and `timeoutSeconds` are subtracted because `defineNode`
    // puts them on *every* node: they are `StateGraph.add_node` parameters,
    // which CLAUDE.md places on the workflow rather than on any family, so
    // they are not this atom's to declare or to mirror.
    expect(ownFieldKeys().sort()).toEqual(
      [
        MCP_FIELD.authHeaderName,
        MCP_FIELD.authKind,
        MCP_FIELD.authTokenEnv,
        MCP_FIELD.note,
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

  it('defaults to HTTP with no authentication', () => {
    const defaults = defaultsFrom(mcpServerNode.fields);
    expect(defaults[MCP_FIELD.transport]).toBe(TRANSPORT_HTTP);
    expect(defaults[MCP_FIELD.authKind]).toBe(AUTH_NONE);
    expect(defaults[MCP_FIELD.tools]).toEqual([]);
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

  it('suggests the two built-in servers when nothing is registered', () => {
    const picker = field(MCP_FIELD.server);
    expect(picker?.kind).toBe('combobox');
    const options = resolveOptions(picker as never, {});
    expect(options.map((o) => o.value)).toEqual([...DEFAULT_MCP_SERVER_NAMES]);
  });

  it('resolves a live server list lazily, so a new one needs no reload', () => {
    let registered = ['Internal wiki'];
    const definition = createMcpServerNode(() =>
      registered.map((name) => ({ value: name, label: name })),
    );
    const picker = definition.fields.find((f) => f.key === MCP_FIELD.server);

    expect(resolveOptions(picker as never, {}).map((o) => o.value)).toEqual(['Internal wiki']);
    registered = ['Internal wiki', 'Vendor API'];
    expect(resolveOptions(picker as never, {}).map((o) => o.value)).toHaveLength(2);
  });

  it('lets a name be typed that is not registered yet', () => {
    // Combobox rather than select: drafting the card before registering the
    // server is a real order of work, and a listbox would outlaw it.
    expect(field(MCP_FIELD.server)?.kind).toBe('combobox');
  });

  it('offers HTTP and a labelled-deprecated SSE, and nothing that cannot carry a credential', () => {
    const options = resolveOptions(field(MCP_FIELD.transport) as never, {});
    expect(options.map((o) => o.value)).toEqual([TRANSPORT_HTTP, TRANSPORT_SSE]);
    expect(options.find((o) => o.value === TRANSPORT_SSE)?.label).toMatch(/deprecated/i);
    // WebSocket has no headers field at all; stdio names an executable.
    expect(options.map((o) => o.value)).not.toContain('websocket');
    expect(options.map((o) => o.value)).not.toContain('stdio');
  });

  it('offers a custom header as well as a bearer token', () => {
    // Both are load-bearing: LangSmith's own server wants LANGSMITH-API-KEY.
    const kinds = resolveOptions(field(MCP_FIELD.authKind) as never, {}).map((o) => o.value);
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

  it('has no field a credential value belongs in', () => {
    const keys = mcpServerNode.fields.map((f) => f.key);
    for (const forbidden of ['token', 'apiKey', 'secret', 'password', 'authToken']) {
      expect(keys).not.toContain(forbidden);
    }
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
  });

  it('names the registered server and that nothing is filtered out', () => {
    expect(placed({ [MCP_FIELD.server]: 'LangChain docs' }).subtitle).toBe(
      'LangChain docs · every tool it offers',
    );
  });

  it('falls back to the URL when no server is named', () => {
    expect(placed({ [MCP_FIELD.url]: 'https://vendor.test/mcp' }).subtitle).toBe(
      'https://vendor.test/mcp · every tool it offers',
    );
  });

  it('counts the filter, and never a discovered tool list', () => {
    const node = placed({
      [MCP_FIELD.server]: 'LangChain docs',
      [MCP_FIELD.tools]: [{ name: 'search_docs' }, { name: 'get_symbol' }],
    });
    // The number here is the document's, not the server's. A count of what
    // the server offers needs a round trip, so a card showing one would be
    // claiming something it cannot know before a run.
    expect(node.subtitle).toBe('LangChain docs · 2 tools only');
  });

  it('drops blank filter rows in both languages alike', () => {
    const node = placed({
      [MCP_FIELD.server]: 'LangChain docs',
      [MCP_FIELD.tools]: [{ name: '  ' }, { name: 'search_docs' }],
    });
    expect(node.selectedTools).toEqual(['search_docs']);
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
