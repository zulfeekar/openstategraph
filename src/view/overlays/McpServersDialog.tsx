import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plug, RotateCcw, Trash2, TriangleAlert } from 'lucide-react';
import { Badge, Button, Field, Icon, IconTile, TextInput } from '@design/primitives';
import type { FieldValue } from '@core/model/contracts/fields';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import {
  summariseMcpValidation,
  type McpServer,
  type McpServerDraft,
  type McpValidation,
} from '@core/runtime/McpRegistryClient';
import { MCP_FIELD, mcpServerFields } from '@nodes/tools/mcpServerFields';
import { Dialog } from './Dialog';
import { McpServerFieldSet } from './McpServerFieldSet';
import { McpStatusMemory, mcpStatusTone } from './mcpServerStatus';
import './overlays.css';

/**
 * MCP servers — the app-level panel, a peer of the credentials dialog.
 *
 * Reached the same way (an icon in the toolbar's right-hand group) because it
 * answers the same class of question: what does *this project* have available,
 * as opposed to what does this document say. A server registered here is
 * nameable from any workflow's `tool.mcp` card.
 *
 * **The controls are not written here.** Every field below the name comes from
 * `mcpServerFields()` — the factory ticket 02 extracted for this exact reuse —
 * so which transports exist, which auth types exist, what a valid credential
 * variable looks like, and what the machinery does are stated in one module
 * and rendered in two places. There is no MCP literal in this file, and
 * `mcpPanelSurface.test.ts` fails if one appears.
 *
 * **Two things a row can say, and they are different questions.** *Registered*
 * is what the project's config declares; *live* is what happened when we last
 * shook hands with it. A server can be registered, correctly spelled, and
 * down — so the badge is a network fact with a timestamp, held in this
 * browser (`mcpServerStatus`), never written back to the committed file, and
 * re-checked every time this dialog opens.
 */
export function McpServersDialog({ onClose }: { onClose: () => void }) {
  const client = useMemo(() => new RuntimeClient(), []);
  const memory = useMemo(() => new McpStatusMemory(), []);

  const [servers, setServers] = useState<readonly McpServer[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [checking, setChecking] = useState<readonly string[]>([]);
  /** Bumped whenever a verdict is remembered, since the memory is not React state. */
  const [, setVerdictVersion] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);

  const record = useCallback(
    (name: string, verdict: McpValidation) => {
      memory.remember(name, {
        status: verdict.status,
        message: verdict.message,
        tools: verdict.tools,
        checkedAt: Date.now(),
      });
      setVerdictVersion((version) => version + 1);
    },
    [memory],
  );

  const check = useCallback(
    async (name: string) => {
      setChecking((current) => [...current, name]);
      const result = await client.mcp.validate({ server: name });
      setChecking((current) => current.filter((entry) => entry !== name));
      if (result.ok) record(name, result.value);
      else setProblem(result.error);
    },
    [client, record],
  );

  /** Load the list, then re-check every row. */
  useEffect(() => {
    let live = true;
    void client.mcp.servers().then((result) => {
      if (!live) return;
      if (!result.ok) {
        setProblem(result.error);
        setServers([]);
        return;
      }
      setServers(result.value);
      // On open, not on demand: a badge that is only ever as fresh as the
      // last time somebody pressed a button is the badge that misleads.
      for (const server of result.value) void check(server.name);
    });
    return () => {
      live = false;
    };
  }, [client, check]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setProblem(null);
    const result = await client.mcp.save(asDraftPayload(draft));
    setSaving(false);
    if (!result.ok) {
      setProblem(result.error);
      return;
    }
    setServers(result.value);
    setDraft(null);
    void check(draft.name.trim());
  };

  const remove = async (name: string) => {
    const result = await client.mcp.remove(name);
    if (!result.ok) {
      setProblem(result.error);
      return;
    }
    setServers(result.value);
    // Otherwise a re-registered server of the same name would inherit a badge
    // earned by a different URL.
    memory.forget(name);
    setVerdictVersion((version) => version + 1);
  };

  return (
    <Dialog
      title="MCP servers"
      subtitle="Tools an agent can call, from a server this project registers. A workflow names one; the project says what that name reaches."
      icon={Plug}
      onClose={onClose}
      footer={
        <>
          <Button
            icon={<Icon glyph={RotateCcw} size="sm" />}
            onClick={() => {
              for (const server of servers ?? []) void check(server.name);
            }}
          >
            Re-check all
          </Button>
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </>
      }
    >
      <p className="dialog__warning">
        <Icon glyph={TriangleAlert} size="sm" />
        <span>
          A server's credential never enters this page or any document. Name the environment
          variable that holds it, and set the value in <code>.env</code> on the runtime — the same
          file its provider keys live in.
        </span>
      </p>

      {problem ? <p className="provider__hint">{problem}</p> : null}

      {servers === null ? (
        <p className="provider__hint">Asking the runtime what is registered…</p>
      ) : null}

      {(servers ?? []).map((server) => {
        const verdict = memory.recall(server.name);
        // The badge word and the sentence under it, from the one place that
        // decides them — the same function a `tool.mcp` row's own check reads,
        // so a card and this panel never disagree about what "live" looks like.
        const summary = verdict
          ? summariseMcpValidation({
              status: verdict.status,
              message: verdict.message,
              serverName: '',
              serverVersion: '',
              tools: verdict.tools,
              elapsedSeconds: 0,
            })
          : null;
        const busy = checking.includes(server.name);

        return (
          <section key={server.name} className="provider">
            <div className="provider__head">
              <IconTile glyph={Plug} size="sm" iconSize="xs" />
              <span className="provider__name">{server.name}</span>
              <Badge>{server.origin === 'built-in' ? 'default' : 'project'}</Badge>
              {busy ? (
                <Badge>checking…</Badge>
              ) : verdict && summary ? (
                <Badge tone={mcpStatusTone(verdict.status)}>{summary.label}</Badge>
              ) : null}
            </div>

            <span className="provider__models">{server.url}</span>

            {summary ? <p className="provider__hint">{summary.detail}</p> : null}

            {server.auth.kind !== 'none' ? (
              <p className="provider__hint">
                {server.credentialConfigured
                  ? `Credential: ${server.auth.tokenEnv} is set on the runtime ✓`
                  : `Credential: set ${server.auth.tokenEnv || 'its variable'} in .env`}
              </p>
            ) : null}

            <div className="mcp-row__actions">
              <Button onClick={() => void check(server.name)} disabled={busy}>
                {busy ? 'Checking…' : 'Validate'}
              </Button>
              <Button onClick={() => setDraft(draftOf(server))}>Edit</Button>
              <Button
                variant="danger"
                icon={<Icon glyph={Trash2} size="sm" />}
                onClick={() => void remove(server.name)}
              >
                Delete
              </Button>
            </div>
          </section>
        );
      })}

      {draft ? (
        <section className="provider">
          <div className="provider__head">
            <IconTile glyph={Plug} size="sm" iconSize="xs" />
            <span className="provider__name">
              {draft.original ? `Edit ${draft.original}` : 'New server'}
            </span>
          </div>

          {/* The one field the card does not have: a card PICKS a server by
              name, and this panel is where a name comes from. */}
          <Field
            label="Name"
            hint="What a workflow's MCP card will name. Saving over an existing name replaces it."
          >
            <TextInput
              value={draft.name}
              placeholder="Internal docs"
              autoComplete="off"
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </Field>

          <McpServerFieldSet
            fields={PANEL_FIELDS}
            values={draft.values}
            onChange={(key, value) =>
              setDraft({ ...draft, values: { ...draft.values, [key]: value } })
            }
          />

          <div className="mcp-row__actions">
            <Button variant="primary" onClick={() => void save()} disabled={saving}>
              {saving ? 'Saving…' : 'Save server'}
            </Button>
            <Button onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </section>
      ) : (
        <Button onClick={() => setDraft(emptyDraft())}>Add a server</Button>
      )}
    </Dialog>
  );
}

/**
 * The same field set the `tool.mcp` card renders, minus two controls.
 *
 * The **picker** is off by the factory's own option: the card offers *pick a
 * registered server, or configure one inline*, and this panel **is** where a
 * registered server comes from, so a picker here would offer to name the thing
 * being defined.
 *
 * The **tool filter** is dropped by key, and the reason is a scope one rather
 * than a taste one: a filter is a property of one node's wiring — which tools
 * *this agent* gets — so it lives in `workflow.json`, and `McpServerConfig`
 * has nowhere to put it. Rendering it here would be a control that silently
 * writes nothing, which is the failure the panel exists to avoid, not commit.
 */
const PANEL_FIELDS = mcpServerFields({ includeServerPicker: false }).filter(
  (schema) => schema.key !== MCP_FIELD.tools,
);

interface Draft {
  /** The name this will be saved under. */
  readonly name: string;
  /** The name it had before an edit, so a rename is visible in the heading. */
  readonly original: string | null;
  readonly values: Readonly<Record<string, FieldValue>>;
}

const defaults = (): Record<string, FieldValue> =>
  Object.fromEntries(
    PANEL_FIELDS.map((schema) => [
      schema.key,
      (schema.kind === 'repeatable-group' ? [] : schema.defaultValue) as FieldValue,
    ]),
  );

const emptyDraft = (): Draft => ({ name: '', original: null, values: defaults() });

const draftOf = (server: McpServer): Draft => ({
  name: server.name,
  original: server.name,
  values: {
    ...defaults(),
    [MCP_FIELD.url]: server.url,
    [MCP_FIELD.transport]: server.transport,
    [MCP_FIELD.authKind]: server.auth.kind,
    [MCP_FIELD.authHeaderName]: server.auth.headerName,
    [MCP_FIELD.authTokenEnv]: server.auth.tokenEnv,
  },
});

const text = (values: Readonly<Record<string, FieldValue>>, key: string): string => {
  const value = values[key];
  return typeof value === 'string' ? value.trim() : '';
};

/**
 * A draft as the runtime takes it.
 *
 * The tool filter is **not** sent: it is a property of one node's wiring, not
 * of the server — which is why `research/01-adapters.md` puts it in
 * `workflow.json` and the server definition in project config. Editing it here
 * would write it somewhere no node reads.
 */
const asDraftPayload = (draft: Draft): McpServerDraft => ({
  name: draft.name.trim(),
  url: text(draft.values, MCP_FIELD.url),
  transport: text(draft.values, MCP_FIELD.transport),
  auth: {
    kind: text(draft.values, MCP_FIELD.authKind) || 'none',
    headerName: text(draft.values, MCP_FIELD.authHeaderName),
    tokenEnv: text(draft.values, MCP_FIELD.authTokenEnv),
  },
});
