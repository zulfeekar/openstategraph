import type { FieldValue, RowProbe, RowVerdict } from '@core/model/contracts/fields';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import { summariseMcpValidation } from '@core/runtime/McpRegistryClient';
import { MCP_FIELD } from './mcpServerFields';

/**
 * One row of the MCP card, shaken hands with.
 *
 * The panel has had a Validate button since ticket 03, and a card row needs
 * exactly the same answer for a different reason: the panel asks *is this
 * server definition right*, and a row asks *will this node bind anything when
 * the workflow runs*. Same route, same taxonomy, same words — which is why the
 * verdict is summarised by `summariseMcpValidation` in the runtime client
 * rather than translated again here.
 *
 * **Its own module, not a closure inside the field set.** `mcpServerFields` is
 * read with no browser at all — `npm run generate:ports` imports the whole node
 * catalogue under Node to emit the port table — so a field declaration must not
 * drag an HTTP client behind it. Here the client is constructed inside `run`,
 * which happens only when somebody presses the button.
 *
 * **Never a credential.** The request carries the row's variable *name*, as
 * every other MCP request in this repository does; the runtime reads the value
 * from its own environment at bind time and the browser never holds one.
 */
const text = (row: Readonly<Record<string, FieldValue>>, key: string): string => {
  const value = row[key];
  return typeof value === 'string' ? value.trim() : '';
};

export async function checkMcpServerRow(
  row: Readonly<Record<string, FieldValue>>,
): Promise<RowVerdict> {
  const server = text(row, MCP_FIELD.server);
  const url = text(row, MCP_FIELD.url);
  if (!server && !url) {
    // Refuse rather than ask the runtime about nothing: a round trip that
    // could only ever answer "unreachable" would blame the network for an
    // empty row.
    return { ok: false, label: 'no server', detail: 'Pick a registered server, or type a URL.' };
  }

  const result = await new RuntimeClient().mcp.validate(
    // A registered name is checked *as a name*, so the runtime resolves it
    // through the same catalogue the compile will — checking the URL a card
    // happens to remember would validate something the run never uses.
    server
      ? { server }
      : {
          url,
          transport: text(row, MCP_FIELD.transport),
          auth: {
            kind: text(row, MCP_FIELD.authKind) || 'none',
            headerName: text(row, MCP_FIELD.authHeaderName),
            tokenEnv: text(row, MCP_FIELD.authTokenEnv),
          },
        },
  );

  if (!result.ok) {
    // The request never reached the runtime, which is a different failure from
    // any verdict — and saying "unreachable" here would point at the server.
    return { ok: false, label: 'no runtime', detail: result.error };
  }
  const summary = summariseMcpValidation(result.value);
  return { ok: summary.ok, label: summary.label, detail: summary.detail };
}

export const mcpRowProbe: RowProbe = { label: 'Check', run: checkMcpServerRow };
