import type {
  FieldOption,
  FieldSchema,
  FieldValue,
  RepeatableGroupSchema,
  RowProbe,
} from '@core/model/contracts/fields';
import { mcpServerCatalogue } from '@core/runtime/mcpServerCatalogue';

/**
 * The MCP-server field set, declared **once** and rendered in two places.
 *
 * Two scopes want the same widget — URL, transport, auth type, the variable
 * name, the tool filter. It appears inline on the `tool.mcp` card, for a
 * server this one workflow uses, and it appears in the app-level panel beside
 * the credentials dialog, for a server the whole project registers. The map's
 * interview settled that as *two scopes, one field-set*, and this module is
 * that decision expressed as code: a factory returning `FieldSchema[]` rather
 * than a literal fused into a node definition.
 *
 * The alternative — the panel hand-building its own controls — is the
 * duplication CLAUDE.md's DRY rule is actually about. It is duplicated
 * *knowledge*: what an MCP server is, which transports are offered, what a
 * valid variable name looks like. Two copies drift the first time a fourth
 * auth type is added, and the drift is invisible until somebody configures a
 * server in one place that the other cannot express.
 *
 * The shape follows `modelField(providers)` — a factory rather than a
 * constant, because the list of registered servers is runtime state (it comes
 * from `GET /api/mcp/servers`) and not a literal.
 */

/**
 * Keys, in two containers. Mirrored by `prebuilt_mcp.MCP_NODE_KEYS` and
 * `MCP_ROW_KEYS`, which `test_mcp_field_contract.py` compares against this
 * declaration.
 *
 * `servers`, `mcpGuide` and `mcpNote` are the node's own; the rest describe
 * **one server**, and since ticket 04 they live inside a row on the card and
 * flat in the app-level panel. One vocabulary, two containers — a panel entry
 * and a card row are the same seven questions asked in different places.
 */
export const MCP_FIELD = {
  servers: 'servers',
  server: 'server',
  url: 'url',
  transport: 'transport',
  authKind: 'authKind',
  authHeaderName: 'authHeaderName',
  authTokenEnv: 'authTokenEnv',
  tools: 'tools',
  guide: 'mcpGuide',
  note: 'mcpNote',
} as const;

/**
 * The `StreamableHttpConnection` literal, stored and labelled *HTTP*.
 *
 * Three spellings alias to one branch in the library (`streamable_http`,
 * `streamable-http`, `http`); exactly one is written to a document, so a
 * reader comparing two documents is comparing the same thing.
 */
export const TRANSPORT_HTTP = 'streamable_http';
export const TRANSPORT_SSE = 'sse';

/**
 * Two transports, and the two that are missing are decisions rather than
 * omissions.
 *
 * **WebSocket** carries no headers, no auth and no timeout — its connection
 * type has no field a credential could travel in — so it cannot satisfy this
 * project's secrets rule at all. **stdio** is a local process rather than a
 * URL: it spawns a subprocess per call under the stateless client, and it
 * would let a canvas document name an arbitrary executable, which is a
 * security posture question and not a dropdown entry.
 */
export const MCP_TRANSPORT_OPTIONS: readonly FieldOption[] = [
  { value: TRANSPORT_HTTP, label: 'HTTP' },
  // Labelled, not hidden: the MCP spec deprecates it and legacy servers still
  // speak it, so a developer needs to be able to pick it and to see why they
  // would rather not.
  { value: TRANSPORT_SSE, label: 'SSE (deprecated)' },
];

export const AUTH_NONE = 'none';
export const AUTH_BEARER = 'bearer';
export const AUTH_HEADER = 'header';

/**
 * Three auth types, and **both** of the credential-bearing ones are
 * load-bearing.
 *
 * Shipping bearer alone looks sufficient and is not: LangSmith's own MCP
 * server documents a `LANGSMITH-API-KEY` header, so the vendor most likely to
 * be configured first is the one bearer cannot reach.
 *
 * OAuth is a genuine client capability that v1 declines, because an
 * `httpx.Auth` is a Python object and a document may not carry host-language
 * code. It becomes a fourth value later with no change to what is stored.
 */
export const MCP_AUTH_OPTIONS: readonly FieldOption[] = [
  { value: AUTH_NONE, label: 'None' },
  { value: AUTH_BEARER, label: 'Bearer token' },
  { value: AUTH_HEADER, label: 'Custom header' },
];

/** The two servers every project starts with, by name. */
export const DEFAULT_MCP_SERVER_NAMES = ['LangChain docs', 'LangChain API reference'] as const;

/**
 * Value prefixes that are unambiguously credentials.
 *
 * Mirrors `config_file.SECRET_VALUE_PREFIXES`, and
 * `backend/tests/test_mcp_field_contract.py` fails if the two lists diverge —
 * a guard that runs in one language and not the other is half a guard, and
 * the half that is missing is always the one somebody hits.
 *
 * A prefix list rather than an entropy heuristic, for the reason the Python
 * side records: a model id is long and opaque too, and a false positive here
 * refuses a legitimate value.
 */
export const SECRET_VALUE_PREFIXES = [
  'sk-',
  'sk_',
  'pk-',
  'ghp_',
  'gho_',
  'github_pat_',
  'gsk_',
  'xai-',
  'hf_',
  'r8_',
  'AIza',
  'ya29.',
  'Bearer ',
  'AKIA',
] as const;

/**
 * A POSIX environment variable name, and not a credential wearing one.
 *
 * The field's label says *name*, and somebody will paste a key into it. Two
 * checks, because **one is provably not enough**: the shape check catches
 * everything with a hyphen or a leading digit (`sk-…`, `xoxb-…`, a UUID), and
 * the prefix check catches what the shape check cannot — `ghp_aaaa…` is a
 * perfectly legal variable name and a GitHub token, and this validator
 * accepted it until a test tried it.
 *
 * The backend refuses the same two shapes independently, because a validator
 * that only runs in a browser is a suggestion.
 */
export const validateEnvVarName = (value: FieldValue): string | null => {
  const text = String(value ?? '').trim();
  if (text === '') return null;
  const advice =
    'This is the NAME of an environment variable, not the credential. Put the value in .env.';
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(text)) return advice;
  return SECRET_VALUE_PREFIXES.some((prefix) => text.startsWith(prefix)) ? advice : null;
};

/**
 * What the machinery already does, shown read-only beside what you own.
 *
 * Not a pre-filled editable box — that was the original `RouterNode` bug. The
 * three facts here are the ones a developer cannot discover from the card and
 * would otherwise learn from a support thread: where the credential lives,
 * that an empty filter keeps following the server, and that the connection is
 * held open rather than rebuilt per call.
 *
 * That last sentence used to say the opposite — "each call reconnects, which
 * costs roughly 0.8 seconds" — and it was true of a defect rather than of MCP.
 * `backend/openstategraph/mcp_sessions.py` holds one session per server for
 * the life of the process, so the handshake is paid once at compile.
 */
export const MCP_LOCKED_NOTE =
  'The tools this server offers are discovered fresh every time the workflow ' +
  'compiles, so a server that grows a tool needs no edit here. Leave the tool ' +
  'filter empty to bind all of them, now and later; naming even one freezes ' +
  'this node to that list. The credential is read at bind time from the ' +
  'environment variable you name — the name is saved in this workflow, the ' +
  'value never is. A server that is unreachable, that rejects the credential, ' +
  'or that does not speak MCP costs this agent its tools and says so in the ' +
  'run’s warnings; it never fails the compile. The connection is opened once ' +
  'and held open, so a call costs what the server takes and no handshake.';;

/**
 * The one sentence a developer needs before adding a second row, on the card
 * where the decision is made.
 *
 * N servers on one node give up per-server **routing** — the card has one
 * output, so every row's tools travel to the same place. That is a cost of
 * zero when the servers share a consumer (three services, one agent choosing
 * per task) and a wall when they do not, and nothing about the card says which
 * situation you are in. So it says it here rather than in a support thread.
 */
export const MCP_GROUPING_GUIDE =
  'One node per group of servers that share a consumer. Every row’s tools land ' +
  'on the same bus, so an agent wired here can call all of them and choose per ' +
  'task; two agents that need different servers want two of these nodes. Narrow ' +
  'a thirty-tool server with that row’s own filter rather than by splitting it out.';

export interface McpFieldSetOptions {
  /**
   * Registered servers to suggest, resolved lazily so a server added in the
   * panel appears without a reload — the same reason `modelField` resolves
   * its options on each render.
   */
  readonly servers?: () => readonly FieldOption[];
  /**
   * Whether to include the *pick a registered server* control. The card has
   * it (pick one, or configure inline); the app-level panel is *defining* a
   * server, so it renders the same set without it.
   */
  readonly includeServerPicker?: boolean;
  /** Inspector section these fields group under. */
  readonly group?: string;
}

/**
 * What the picker offers when nobody handed it a list: the live registry.
 *
 * The thunk was always the right shape and nothing ever passed one, so every
 * caller got the two built-in names — in every project, on every install,
 * including after one of those two was deleted in the panel (mcp-connect
 * ticket 07). `mcpServerCatalogue` is what the panel's own client publishes
 * into, so the card and the panel now read one answer.
 *
 * The built-ins survive as the **pre-answer** fallback only. `null` means the
 * registry has not been reached — a project that has configured nothing does
 * have exactly these two, so offering them is true rather than merely
 * convenient. An empty *answer* is honoured as empty; that is the deletion
 * case, and rounding it back to the defaults would restore the ghost entry.
 */
const registeredServers = (): readonly FieldOption[] => {
  const known = mcpServerCatalogue.list() ?? DEFAULT_MCP_SERVER_NAMES;
  return known.map((name) => ({ value: name, label: name }));
};

/**
 * Module-level, not an inline arrow.
 *
 * The card's row schemas are compared **by value** against the panel's own —
 * that is the test keeping one field set from becoming two — and a fresh
 * closure per call is a fresh identity per call, which fails that comparison
 * for a difference nobody made.
 */
const subscribeToRegistry = (notify: () => void): (() => void) =>
  mcpServerCatalogue.onChange(notify);

/**
 * The field set, in the order a developer fills it in.
 *
 * Server first, because picking one makes the rest unnecessary; then the
 * inline definition; then auth; then the filter, which is the only part that
 * needs the server to have answered first.
 */
export function mcpServerFields(options: McpFieldSetOptions = {}): readonly FieldSchema[] {
  const { servers = registeredServers, includeServerPicker = true, group = 'MCP server' } = options;

  const picker: readonly FieldSchema[] = includeServerPicker
    ? [
        {
          // Combobox, not select: the same reasoning as mounting a package
          // you have not built yet. A listbox would make it impossible to
          // name a server you are about to register, and drafting in that
          // order is a real way to work.
          kind: 'combobox',
          key: MCP_FIELD.server,
          label: 'Server',
          options: servers,
          // Redraw when the panel registers or deletes one, which is what the
          // thunk's own comment above has promised since ticket 04.
          subscribe: subscribeToRegistry,
          defaultValue: '',
          placeholder: 'Pick one, or configure below',
          emptyHint: 'No servers registered yet — give this one a URL below.',
          hint: 'A registered server, by name. Leave empty to configure one just for this workflow.',
          group,
        },
      ]
    : [];

  return [
    ...picker,
    {
      kind: 'text',
      key: MCP_FIELD.url,
      label: 'URL',
      mono: true,
      defaultValue: '',
      placeholder: 'https://docs.langchain.com/mcp',
      hint: 'Used when no registered server is named above.',
      group,
    },
    {
      kind: 'select',
      key: MCP_FIELD.transport,
      label: 'Transport',
      options: MCP_TRANSPORT_OPTIONS,
      defaultValue: TRANSPORT_HTTP,
      onCard: false,
      group,
    },
    {
      kind: 'select',
      key: MCP_FIELD.authKind,
      label: 'Authentication',
      options: MCP_AUTH_OPTIONS,
      defaultValue: AUTH_NONE,
      onCard: false,
      group,
    },
    {
      kind: 'text',
      key: MCP_FIELD.authHeaderName,
      label: 'Header name',
      mono: true,
      defaultValue: '',
      placeholder: 'LANGSMITH-API-KEY',
      hint: 'Custom-header authentication only — the header the vendor documents.',
      onCard: false,
      advanced: true,
      group,
    },
    {
      // The whole secrets rule lands on this one field, which is why its
      // label, its placeholder, its hint and its validator all say the same
      // thing four different ways.
      kind: 'text',
      key: MCP_FIELD.authTokenEnv,
      label: 'Credential variable',
      mono: true,
      defaultValue: '',
      placeholder: 'MY_MCP_TOKEN',
      hint: 'The NAME of an environment variable. The value stays in .env and never enters this workflow.',
      validate: validateEnvVarName,
      onCard: false,
      advanced: true,
      group,
    },
    {
      // A repeatable group rather than a multi-select, because the names come
      // from the server and the card cannot ask it: discovery is a network
      // call, and a control that renders an empty list before validation
      // would read as "this server has no tools".
      kind: 'repeatable-group',
      key: MCP_FIELD.tools,
      label: 'Only these tools',
      addLabel: 'Add tool',
      fields: [{ kind: 'text', key: 'name', defaultValue: '', placeholder: 'search_docs' }],
      defaultValue: [],
      hint: 'Leave empty for every tool this server offers, now and later.',
      onCard: false,
      advanced: true,
      group,
    },
    {
      kind: 'readonly',
      key: MCP_FIELD.note,
      label: 'What the machinery already does',
      defaultValue: MCP_LOCKED_NOTE,
      onCard: false,
      group,
    },
  ];
}

/**
 * The same field set, shaped for **one row** of the card's server table.
 *
 * Derived from `mcpServerFields()` rather than written again: every control
 * that survives is the *identical object* the panel renders, so a fourth auth
 * type or a changed hint appears in both places or in neither.
 *
 * Two schemas cannot travel into a row as they are, and both exclusions are
 * mechanical rather than editorial:
 *
 * - **The read-only notes** are facts about the machinery, not about a server.
 *   They belong to the node, once, and repeating them per row would be the
 *   same paragraph three times on one card.
 * - **The tool filter** is a `repeatable-group`, and a row cannot contain a
 *   table. It becomes one comma-separated line under the same key, and both
 *   spellings are read by `parseToolFilter` here and `_tool_filter` in
 *   `prebuilt_mcp.py` — so an old document, the panel's field set and a card
 *   row all mean the same thing by "only these tools".
 */
export function mcpServerRowFields(options: McpFieldSetOptions = {}): readonly FieldSchema[] {
  return mcpServerFields(options).flatMap((schema): FieldSchema[] => {
    if (schema.kind === 'readonly') return [];
    if (schema.key !== MCP_FIELD.tools) return [schema];
    return [
      {
        kind: 'text',
        key: MCP_FIELD.tools,
        label: schema.label,
        mono: true,
        defaultValue: '',
        placeholder: 'search_docs, get_symbol',
        hint: schema.hint,
        group: schema.group,
      },
    ];
  });
}

export interface McpServerRowsOptions extends McpFieldSetOptions {
  /**
   * The per-row live check. Optional because a field set is a declaration and
   * a probe opens a socket: the app-level panel has its own Validate button,
   * and a generated port table must not acquire an HTTP client to be read.
   */
  readonly probe?: RowProbe;
}

/** A row as the card writes it, with the stable id every row group carries. */
const emptyRow = (): Record<string, FieldValue> => ({
  id: 'mcp1',
  [MCP_FIELD.server]: '',
  [MCP_FIELD.url]: '',
  [MCP_FIELD.transport]: TRANSPORT_HTTP,
  [MCP_FIELD.authKind]: AUTH_NONE,
  [MCP_FIELD.authHeaderName]: '',
  [MCP_FIELD.authTokenEnv]: '',
  [MCP_FIELD.tools]: '',
});

/**
 * The card's server table: N rows of the shared field set.
 *
 * One row by default, not zero — a placed card is something to fill in rather
 * than something you must first discover has a button. The Guardrail's policy
 * table seeds its rows for the same reason.
 *
 * **Not on the card itself.** Seven controls times three rows is taller than
 * the canvas; the card carries the subtitle and the guidance, and the rows are
 * edited in the inspector. That is the only difference from the Guardrail's
 * table, whose three short controls genuinely do read at a glance.
 */
export function mcpServersField(options: McpServerRowsOptions = {}): RepeatableGroupSchema {
  const { probe, ...fieldOptions } = options;
  return {
    kind: 'repeatable-group',
    key: MCP_FIELD.servers,
    label: 'Servers',
    addLabel: 'Add server',
    defaultValue: [emptyRow()],
    fields: mcpServerRowFields(fieldOptions),
    hint: 'Each row is one server. All of their tools reach whatever this node is wired to.',
    onCard: false,
    group: 'MCP servers',
    ...(probe ? { rowProbe: probe } : {}),
  };
}

/**
 * A row's tool filter, as names — typed on a line, or the panel's row list.
 *
 * The mirror of `prebuilt_mcp._tool_filter`, and blank entries are dropped in
 * both: somebody who types a comma and stops must not silently bind nothing.
 */
export function parseToolFilter(value: FieldValue | undefined): string[] {
  if (typeof value === 'string') {
    return value
      .split(/[,\n]/)
      .map((name) => name.trim())
      .filter((name) => name !== '');
  }
  if (!Array.isArray(value)) return [];
  return value
    .map((row) => String((row as Record<string, unknown>)['name'] ?? '').trim())
    .filter((name) => name !== '');
}
