import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { MCP_GROUPING_GUIDE } from './mcpServerFields';

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
