import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';

/**
 * The card for `tool.databricks-query` (`osg-agent-experience/40`).
 *
 * The same three things `mssqlQueryCard.test.ts` guards — a Python tool with no
 * card at all, a field key the Python `configure()` never reads, and a
 * credential field that invites a pasted value into a committed document — plus
 * one this leaf is the first to have: it names **three** variables rather than
 * one, and each of the three is a separate chance to ship a key nothing reads.
 *
 * The defaults are Databricks' own documented variable names, not ours. That is
 * the decision worth pinning: a machine already configured for
 * `databricks-sql-connector` works with no card edits, and the alternative was a
 * second name for a variable the developer has already exported.
 */
describe('tool.databricks-query card', () => {
  it('is in the palette as a tool atom', () => {
    const workbench = makeWorkbench();
    const definition = workbench.registry.nodeTypes.require('tool.databricks-query');
    expect(definition.label).toBe('Run Databricks Query');
  });

  it('declares exactly the keys the tool reads, and no credential value', () => {
    const workbench = makeWorkbench();
    const fields = workbench.registry.nodeTypes.require('tool.databricks-query').fields ?? [];
    const keys = fields.map((field) => field.key);
    expect(keys).toEqual(
      expect.arrayContaining(['serverHostname', 'httpPath', 'token', 'allowlist', 'maxRows']),
    );
  });

  it('defaults each connection field to a variable NAME the vendor documents', () => {
    const workbench = makeWorkbench();
    const fields = workbench.registry.nodeTypes.require('tool.databricks-query').fields ?? [];
    const byKey = Object.fromEntries(fields.map((field) => [field.key, field]));
    expect(byKey.serverHostname?.defaultValue).toBe('DATABRICKS_SERVER_HOSTNAME');
    expect(byKey.httpPath?.defaultValue).toBe('DATABRICKS_HTTP_PATH');
    expect(byKey.token?.defaultValue).toBe('DATABRICKS_TOKEN');
    // The hint is the only place a user is told the field is a pointer, and the
    // Python half refuses a pasted value — so the two must agree, on all three.
    for (const key of ['serverHostname', 'httpPath', 'token']) {
      expect(String(byKey[key]?.hint ?? '')).toMatch(/name of an environment variable/i);
    }
  });

  it('says the allowlist path is resolved under the workflows root, not by convention', () => {
    // `osg-agent-experience/41`, inherited: the sentence read as a convention
    // and it is a hard refusal. The warehouse rung is shared, so the wording is
    // asserted here too rather than assumed from the T-SQL sibling.
    const workbench = makeWorkbench();
    const allowlist = (
      workbench.registry.nodeTypes.require('tool.databricks-query').fields ?? []
    ).find((field) => field.key === 'allowlist');
    const hint = String(allowlist?.hint ?? '');
    expect(hint).toMatch(/outside the workflows root/i);
    expect(hint).toMatch(/refused/i);
    expect(allowlist?.pathRoot).toBe('workflows');
  });

  it('keeps the values a user typed across a save', () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, 'tool.databricks-query', {
      data: {
        serverHostname: 'WAREHOUSE_HOST',
        httpPath: 'WAREHOUSE_HTTP_PATH',
        token: 'WAREHOUSE_TOKEN',
        allowlist: 'analyst/lenses.yaml',
        maxRows: '50',
      },
    });
    const saved = workbench.serializer.serialize(workbench.model);
    const restored = saved.nodes.find((entry) => entry.id === node.id);
    expect(restored?.data).toMatchObject({
      serverHostname: 'WAREHOUSE_HOST',
      httpPath: 'WAREHOUSE_HTTP_PATH',
      token: 'WAREHOUSE_TOKEN',
      allowlist: 'analyst/lenses.yaml',
      maxRows: '50',
    });
  });
});
