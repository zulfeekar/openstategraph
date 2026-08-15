import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  MCP_AUTH_OPTIONS,
  MCP_TRANSPORT_OPTIONS,
  mcpServerFields,
} from '@nodes/tools/mcpServerFields';

/**
 * mcp-connect ticket 03 — a source assertion, for the reason
 * `topbarSurface.test.ts` gives: placement and reuse have no seam a `node`
 * environment can exercise, and they are exactly what a later tidy-up undoes
 * without noticing.
 *
 * The thing being pinned is the map's own decision. *Two scopes, one
 * field-set* is worth nothing if the panel quietly grows its own copy of what
 * an MCP server is — and it would, one field at a time, each addition looking
 * local and reasonable. So: the panel may not contain a transport name, an
 * auth kind, or the hint text explaining where a credential lives. If it
 * needs one, it takes it from `mcpServerFields()`.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const panel = read('./McpServersDialog.tsx');
const fieldSet = read('./McpServerFieldSet.tsx');
const topbar = read('../topbar/TopBar.tsx');
const shell = read('../AppShell.tsx');

describe('the MCP panel is a projection of the card’s field set', () => {
  it('renders the factory rather than hand-built controls', () => {
    expect(panel).toContain('mcpServerFields(');
    expect(panel).toContain('includeServerPicker: false');
    expect(panel).toContain('McpServerFieldSet');
  });

  it('names no transport of its own', () => {
    // `streamable_http` / `sse` appear once in this repository's UI layer, in
    // the factory. A second spelling here is the drift that makes a fourth
    // transport configurable in one place and not the other.
    // Quoted, because these are short strings: "pressed" contains `sse`, and
    // a test that reports prose as drift is a test somebody deletes.
    for (const option of MCP_TRANSPORT_OPTIONS) {
      expect(panel, `the panel spells out ${option.value}`).not.toContain(`'${option.value}'`);
      expect(fieldSet).not.toContain(`'${option.value}'`);
    }
  });

  it('names no auth kind of its own beyond the one it must branch on', () => {
    // `none` is the exception and it is a *display* branch, not a definition:
    // a row only shows a credential line when it has one to show.
    for (const option of MCP_AUTH_OPTIONS) {
      if (option.value === 'none') continue;
      expect(panel, `the panel spells out ${option.value}`).not.toContain(`'${option.value}'`);
      expect(fieldSet).not.toContain(`'${option.value}'`);
    }
  });

  it('restates none of the field set’s own copy', () => {
    // The hints are where the secrets rule is actually taught. Two copies of
    // that sentence is two sentences to update when the rule changes, and the
    // one that goes stale is the one nobody is looking at.
    for (const schema of mcpServerFields({ includeServerPicker: false })) {
      if (!schema.hint) continue;
      expect(panel, `the panel restates the hint for ${schema.key}`).not.toContain(schema.hint);
    }
  });

  it('drives the field set generically, with no MCP key of its own', () => {
    // The renderer is a `FieldSchema` renderer that happens to be used for
    // MCP. If it ever mentions a key, it has stopped being one.
    expect(fieldSet).not.toContain('MCP_FIELD');
    expect(fieldSet).not.toContain('authTokenEnv');
    expect(fieldSet).not.toContain("'transport'");
    // The panel does address keys — it has to build a payload — and it does
    // so through the factory's own constants rather than by spelling them.
    expect(panel).toContain('MCP_FIELD.');
  });
});

describe('the panel’s place in the app', () => {
  it('is a peer of the credentials dialog, reached from the same group', () => {
    expect(topbar).toContain('onOpenMcpServers');
    expect(topbar).toMatch(/label="MCP servers"/);
    expect(shell).toContain('McpServersDialog');
  });

  it('re-checks every registered server when it opens', () => {
    // The map's decision that validation saves with a badge only holds if the
    // badge is fresh; a stored verdict with no re-check is a claim about a
    // network from whenever somebody last pressed a button.
    expect(panel).toMatch(/for \(const server of result\.value\) void check\(server\.name\)/);
  });

  it('offers Delete on every row, defaults included', () => {
    // The two seeded servers are the first two rows a new project has. If
    // Delete were conditional on `origin`, they would be the only undeletable
    // entries in the list, which reads as a bug rather than as a policy.
    expect(panel).toMatch(/>\s*Delete\s*</);
    expect(panel).not.toMatch(/origin\s*[!=]==\s*'built-in'\s*\?[^:]*Delete/);
  });

  it('forgets a deleted server’s badge rather than leaving it to be inherited', () => {
    expect(panel).toContain('memory.forget(name)');
  });
});
