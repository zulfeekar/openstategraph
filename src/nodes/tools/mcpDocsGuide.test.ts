import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  MCP_FIELD,
  MCP_GROUPING_GUIDE,
  MCP_LOCKED_NOTE,
  MCP_ONE_HEADER_LIMIT,
  mcpServerFields,
} from './mcpServerFields';

/**
 * mcp-connect ticket 04's "Done when" shipped in `e87d0ce`/`5549a35`: one
 * `tool.mcp` card, N server rows, per-row validation. What did not ship with
 * it was the docs half the ticket also promised — "one node per group of
 * servers that share a consumer", on the card *and* in the docs.
 *
 * `docs/mcp.md` is the only page that talks about MCP at all, so it is the
 * page that has to carry this. Rather than let the doc restate the guidance
 * in its own words (and drift from the card's), it quotes `MCP_GROUPING_GUIDE`
 * verbatim — this test is the pin that keeps the quote honest.
 */
const REPO = new URL('../../../', import.meta.url);
const mcpDoc = readFileSync(fileURLToPath(new URL('docs/mcp.md', REPO)), 'utf8');

describe('docs/mcp.md carries the one-card-many-servers guidance', () => {
  it("quotes the card's own grouping guide verbatim, not a paraphrase", () => {
    expect(mcpDoc).toContain(MCP_GROUPING_GUIDE);
  });

  it('names the cost the guidance trades against — per-server routing', () => {
    expect(mcpDoc).toMatch(/tool\.mcp/);
    expect(mcpDoc.toLowerCase()).toMatch(/routing/);
  });
});

/**
 * `scale-and-adopt/22`. The owner opened the card, saw `Header name` and
 * `Credential variable` empty, and asked the two questions this block pins the
 * answers to: whether empty is correct, and what happens when a server needs
 * more than one header.
 *
 * Empty is correct under `none` and under `bearer`; under `header` it is a row
 * that will bind nothing, and the card never says so while you type. One
 * header is the limit in the node **and** in `mcp_servers:`, so a project
 * whose gateway wants a key and a tenant id cannot express it here at all —
 * the honest answer, and therefore an answer that has to be written where
 * somebody configuring a server would meet it rather than only in a ticket.
 *
 * The sentence lives once, in `MCP_ONE_HEADER_LIMIT`, and both the card's
 * read-only block and `docs/mcp.md` carry that one copy.
 */
describe('the single-header limit is stated where a reader would meet it', () => {
  it('is one sentence, carried by the card rather than restated on it', () => {
    expect(MCP_LOCKED_NOTE).toContain(MCP_ONE_HEADER_LIMIT);
  });

  it('is quoted verbatim in docs/mcp.md, not paraphrased', () => {
    expect(mcpDoc).toContain(MCP_ONE_HEADER_LIMIT);
  });

  it('says the limit, the branch that needs a value, and what to do instead', () => {
    expect(MCP_ONE_HEADER_LIMIT).toMatch(/exactly one header/i);
    // The `header` branch is the one where empty is a defect rather than a
    // default, and the whole of the owner's first question.
    expect(MCP_ONE_HEADER_LIMIT).toMatch(/empty/i);
    // "it cannot" is only an acceptable answer when it comes with the thing
    // to do instead (CLAUDE.md, and this ticket's own brief).
    expect(MCP_ONE_HEADER_LIMIT).toMatch(/in front of it|of your own/i);
  });

  it('says the project config carries the same one header, not a way around it', () => {
    expect(mcpDoc).toMatch(/mcp_servers/);
    expect(MCP_ONE_HEADER_LIMIT).toMatch(/mcp_servers|project config/i);
  });

  it('tells a reader on the field itself that `header` auth needs the box filled', () => {
    const headerField = mcpServerFields().find((f) => f.key === MCP_FIELD.authHeaderName);
    expect(headerField?.hint).toMatch(/required/i);
  });
});
