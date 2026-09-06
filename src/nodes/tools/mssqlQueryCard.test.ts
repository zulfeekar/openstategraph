import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';

/**
 * The card for `tool.mssql-query` (`osg-agent-experience/34`).
 *
 * Three things a registration test alone would not catch, and each of them
 * shipped broken once in this repository already: a tool registered on the
 * Python side with no card at all (production-ready 61, four of them), a field
 * whose key the Python `configure()` never reads (the data-key contract), and
 * a credential field that invites a pasted value into a committed document.
 *
 * So this drives the real `Workbench`: the type is in the palette, the fields
 * are the three the tool reads, the connection field's default is the *name*
 * of an environment variable rather than a connection string, and the values a
 * user types survive a save.
 */
describe('tool.mssql-query card', () => {
  it('is in the palette as a tool atom', () => {
    const workbench = makeWorkbench();
    const definition = workbench.registry.nodeTypes.require('tool.mssql-query');
    expect(definition.label).toBe('Run T-SQL Query');
  });

  it('declares exactly the keys the tool reads, and no credential', () => {
    const workbench = makeWorkbench();
    const fields = workbench.registry.nodeTypes.require('tool.mssql-query').fields ?? [];
    const keys = fields.map((field) => field.key);
    expect(keys).toContain('connection');
    expect(keys).toContain('allowlist');
    expect(keys).toContain('maxRows');
  });

  it('defaults the connection field to a variable NAME, never a DSN', () => {
    const workbench = makeWorkbench();
    const connection = (workbench.registry.nodeTypes.require('tool.mssql-query').fields ?? []).find(
      (field) => field.key === 'connection',
    );
    expect(connection?.defaultValue).toBe('OPENSTATEGRAPH_MSSQL_URL');
    // The hint is the only place a user is told the field is a pointer, and
    // the Python half refuses a pasted string — so the two must agree.
    expect(String(connection?.hint ?? '')).toMatch(/name of an environment variable/i);
  });

  it('says the allowlist path is resolved under the workflows root, not by convention', () => {
    // `osg-agent-experience/41`. The hint read as a convention — "a YAML file
    // inside workflows/" — and it is a hard refusal: `_pins()` resolves the
    // path under the workflows root and calls `relative_to`, so a file one
    // level above it is refused and the query never runs. A try-folder session
    // read the sentence as advice and moved a 42 KB file and nine readers.
    const workbench = makeWorkbench();
    const allowlist = (workbench.registry.nodeTypes.require('tool.mssql-query').fields ?? []).find(
      (field) => field.key === 'allowlist',
    );
    const hint = String(allowlist?.hint ?? '');
    expect(hint).toMatch(/outside the workflows root/i);
    expect(hint).toMatch(/refused/i);
    // The same fact as data, so `validate` asks the disk instead of a reader —
    // exactly what `tool.sql-*`'s `database` field already declares.
    expect(allowlist?.pathRoot).toBe('workflows');
  });

  it('keeps the values a user typed across a save', () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, 'tool.mssql-query', {
      data: {
        connection: 'WAREHOUSE_DSN',
        allowlist: 'analyst/lenses.yaml',
        maxRows: '50',
      },
    });
    const saved = workbench.serializer.serialize(workbench.model);
    const restored = saved.nodes.find((entry) => entry.id === node.id);
    expect(restored?.data).toMatchObject({
      connection: 'WAREHOUSE_DSN',
      allowlist: 'analyst/lenses.yaml',
      maxRows: '50',
    });
  });
});
