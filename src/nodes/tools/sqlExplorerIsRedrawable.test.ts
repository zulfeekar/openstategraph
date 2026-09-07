import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';

/**
 * The SQL Explorer family can be drawn, wired and saved from the palette
 * (`workflow-gallery/30`).
 *
 * The ticket's complaint was that `workflows/sql-qa` "was written by hand and
 * cannot be redrawn". The declarations landed under `production-ready/61`, so
 * the interesting question is no longer *are they registered* — a registration
 * test stays green against a node whose ports refuse every wire and whose
 * fields the serializer drops. It is: **can a user build that document?**
 *
 * So this drives the real `Workbench`: the palette lists the three types, the
 * real `ConnectionValidator` answers the question a mouse asks when a tool is
 * dragged onto an agent's bus, and the real serializer is asked whether the
 * `database` path a user typed survives a save. The Python half — that the
 * document which results compiles — is
 * `openstategraph/examples/sql-qa/tests/test_sql_qa_document.py`, and the node
 * types are compared against that shipped document here so the two halves
 * cannot drift into describing different graphs.
 */

const SQL_TOOLS = ['tool.sql-list-tables', 'tool.sql-get-schema', 'tool.sql-query'] as const;

const SHIPPED = join(
  __dirname,
  '..',
  '..',
  '..',
  'backend',
  'openstategraph',
  'examples',
  'sql-qa',
  'workflow.json',
);

/** A saved package wraps its document in an envelope; the gallery ships bare. */
function shippedDocument(): { nodes: { type: string; data?: Record<string, unknown> }[] } {
  const raw = JSON.parse(readFileSync(SHIPPED, 'utf8'));
  return raw.document ?? raw;
}

describe('the SQL Explorer family is drawable', () => {
  it.each(SQL_TOOLS)('%s is in the palette, not merely in the registry', (id) => {
    const workbench = makeWorkbench();
    const listed = workbench.registry.nodeTypes.list().map((d) => d.id);
    expect(listed).toContain(id);
  });

  it('accepts all three onto one agent’s tools bus, through the real validator', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, 'agent.llm');

    for (const id of SQL_TOOLS) {
      const tool = addNode(workbench, id, { data: { database: 'sql-qa/data/business.sqlite' } });
      const port = tool.definition.ports(tool.data).find((p) => p.type === 'tool');
      expect(port, `${id} offers no tool port`).toBeDefined();

      const verdict = workbench.connectionValidator.validate(
        { nodeId: tool.id, portId: port!.id },
        { nodeId: agent.id, portId: 'tools' },
      );
      // The bus is what makes three tools on one agent legal at all. If this
      // ever answers `replaces`, the family became undrawable a second way.
      expect(verdict.ok, `${id} refused: ${'reason' in verdict ? verdict.reason : ''}`).toBe(true);
      if (verdict.ok) expect(verdict.replaces ?? []).toHaveLength(0);
    }
  });

  it('offers a card for every key the shipped document actually sets', () => {
    // The claim a user would recognise: open `sql-qa`, click a SQL node, and
    // the path it was configured with is *editable*. A data key no field
    // declares is a value the inspector cannot show and the user cannot
    // change — the node looks configured and offers no way to reconfigure it.
    //
    // Derived from the shipped document rather than restated here, so this
    // cannot agree with itself: it fails if either side moves.
    const workbench = makeWorkbench();
    const injected = new Set(['maxRetries', 'timeoutSeconds']);

    let checked = 0;
    for (const node of shippedDocument().nodes) {
      if (!node.type.startsWith('tool.sql-')) continue;
      const definition = workbench.registry.nodeTypes.require(node.type);
      const declared = new Set((definition.fields ?? []).map((f) => f.key));
      for (const key of Object.keys(node.data ?? {})) {
        if (injected.has(key)) continue;
        expect(declared, `${node.type} sets ${key}, which no card declares`).toContain(key);
        checked += 1;
      }
    }
    expect(checked, 'the sql-qa nodes carry no configuration at all').toBeGreaterThan(0);
  });

  it('keeps that configuration across a save and reload', () => {
    // `WorkflowSerializer.load` silently drops nodes whose type is
    // unregistered — the load-order hazard `PlatformToolsNode` was written to
    // close, and the one that would destroy a user's document on re-save.
    const workbench = makeWorkbench();
    addNode(workbench, 'tool.sql-query', {
      data: { database: 'sql-qa/data/business.sqlite', maxRows: '25' },
    });

    const reopened = makeWorkbench();
    reopened.serializer.load(reopened.model, workbench.serializer.serialize(workbench.model));

    const node = reopened.model.nodes().find((n) => n.type === 'tool.sql-query');
    expect(node, 'the node did not survive a save and reload').toBeDefined();
    expect(node!.data['database']).toBe('sql-qa/data/business.sqlite');
  });

  it('covers every SQL node type the shipped sql-qa document actually uses', () => {
    const workbench = makeWorkbench();
    const listed = new Set(workbench.registry.nodeTypes.list().map((d) => d.id));
    const used = shippedDocument()
      .nodes.map((n) => n.type)
      .filter((t) => t.startsWith('tool.sql-'));

    expect(used.length, 'sql-qa stopped using the SQL explorers').toBeGreaterThan(0);
    for (const type of used) expect(listed, `${type} is not placeable`).toContain(type);
  });
});
