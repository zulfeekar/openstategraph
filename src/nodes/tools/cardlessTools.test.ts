import { describe, expect, it } from 'vitest';
import { PLATFORM_TOOL_NODES } from './PlatformToolsNode';
import { EXECUTION_OVERRIDE_KEYS } from '../../core/model/ModelRegistry';

/**
 * **Every tool the runtime can bind must be drawable, or must stop claiming to
 * be** (production-ready 61).
 *
 * The palette reported five tools with no editor card. The warning was right —
 * `docs/decisions/gap-register.md` already names four of them as "true
 * positives on the first run, which is the point" — and one was worse than the
 * message said: `tool.validate-workflow` is **already wired on a shipped
 * canvas** (`workflows/workflow-architect/workflow.json`, node `t-validate`),
 * so a package this repository ships contained a node type its own editor
 * could not render.
 *
 * The three SQL tools were unusable for a second reason: they read
 * `data["database"]` in `configure()`, and only a card can supply it. A tool
 * with per-node config and no card is a tool nobody can point at a file.
 *
 * These assertions are the editor half of the seam. The Python half — that
 * every key read here is a key the tool declares — is
 * `backend/tests/test_sql_explorer_field_contract.py`, in the shape
 * `test_mcp_field_contract.py` established, because `test_data_key_contract.py`
 * deliberately does not cover a tool's `configure()`.
 */
const byId = new Map(PLATFORM_TOOL_NODES.map((n) => [n.definition.id, n.definition]));

const NEWLY_DRAWABLE = [
  'tool.sql-list-tables',
  'tool.sql-get-schema',
  'tool.sql-query',
  'tool.validate-workflow',
] as const;

describe('the tools that had no card', () => {
  it.each(NEWLY_DRAWABLE)('%s is registered as a platform tool', (id) => {
    expect(byId.has(id)).toBe(true);
  });

  it.each(NEWLY_DRAWABLE)('%s offers exactly one tool port, outward', (id) => {
    const ports = byId.get(id)?.ports({}) ?? [];
    expect(ports).toHaveLength(1);
    expect(ports[0]?.direction).toBe('out');
    expect(ports[0]?.type).toBe('tool');
  });

  describe('the SQL explorers', () => {
    const SQL = ['tool.sql-list-tables', 'tool.sql-get-schema', 'tool.sql-query'] as const;

    it.each(SQL)('%s can be pointed at a database file', (id) => {
      // The whole reason a card was needed: `configure()` reads `database`,
      // and without a field there is no way to set it.
      const field = byId.get(id)?.fields?.find((f) => f.key === 'database');
      expect(field, `${id} has no database field`).toBeDefined();
      expect(field?.defaultValue).toBe('');
    });

    it('marks the database required, because the tool refuses without it', () => {
      // `prebuilt_sql._refusal()` — "No readable database at '(unset)'". A
      // required field with no value is knowable before the run.
      for (const id of SQL) {
        const field = byId.get(id)?.fields?.find((f) => f.key === 'database');
        expect(field && 'required' in field ? field.required : undefined).toBe(true);
      }
    });

    it('gives the query tool its row cap, and nothing else gets one', () => {
      // `SqlQueryTool.configure` reads `maxRows`; the other two do not.
      expect(byId.get('tool.sql-query')?.fields?.some((f) => f.key === 'maxRows')).toBe(true);
      expect(byId.get('tool.sql-list-tables')?.fields?.some((f) => f.key === 'maxRows')).toBe(
        false,
      );
      expect(byId.get('tool.sql-get-schema')?.fields?.some((f) => f.key === 'maxRows')).toBe(false);
    });
  });

  it('gives the validator no configuration of its own, because it reads none', () => {
    // `ValidateWorkflowTool` overrides no `configure()`. A card with controls
    // the tool ignores is a card that lies — honesty gate 7's shape, one
    // direction along.
    //
    // "Of its own" is load-bearing, and this test asserted `length === 0`
    // until it went red: `defineNode` injects the per-node retry and timeout
    // overrides into every `standard` node, because those are graph-assembly
    // parameters available to every node of every family. They are not the
    // tool's configuration and must not be counted as it.
    const own = (byId.get('tool.validate-workflow')?.fields ?? []).filter(
      (field) => !EXECUTION_OVERRIDE_KEYS.includes(field.key),
    );
    expect(own).toHaveLength(0);
  });
});
