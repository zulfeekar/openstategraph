import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';

interface StoredNode {
  readonly id: string;
  readonly type: string;
}
interface StoredEdge {
  readonly source: { readonly nodeId: string; readonly portId: string };
  readonly target: { readonly nodeId: string; readonly portId: string };
}
interface StoredDocument {
  readonly nodes: readonly StoredNode[];
  readonly edges: readonly StoredEdge[];
}

const endpointKey = (edge: StoredEdge): string =>
  `${edge.source.nodeId}/${edge.source.portId} -> ${edge.target.nodeId}/${edge.target.portId}`;

/**
 * The invariant, asserted against the real corpus rather than a fixture.
 *
 * Ticket 20 was found on `workflow-architect`: the backend serves 7 nodes and
 * 7 edges, the editor rendered 6 and 6, and pressing Save wrote the missing
 * ones out of the file for good — the one workflow that demonstrates the
 * platform's own tooling could not survive a round trip through the product's
 * own editor.
 *
 * A hand-written fixture would not have caught it, because the node that went
 * missing (`tool.validate-workflow`) is exactly the kind nobody thinks to put
 * in one: a Python tool with no TypeScript card. So the shipped files *are*
 * the fixture, and a new backend-only tool cannot quietly reopen the hole —
 * binding one in a shipped workflow would fail here.
 *
 * Each file is a package envelope (`version`, `name`, `savedAt`, `document`);
 * the editor round-trips the inner document, which is what these read.
 *
 * ## This gate only works because a lossy load is no longer written back
 *
 * It is half of a pair, and the half that fails loudly. The other half is
 * `loadWasFaithful` (`every-workflow-green` 22): a load that could not place
 * every link withholds the disk-autosave baseline, so the file keeps what it
 * has.
 *
 * Without that, this test is **worse than useless** — it certifies the damage.
 * A hand-written `ops-desk` lost four of twelve links on open, the editor saved
 * the eight that survived, and by the time this ran the file matched the model
 * perfectly and every case was green. The loss had already happened and the
 * evidence was gone.
 *
 * Verified as a pair: a workflow whose file contains a link to a port that
 * does not exist now **fails here**, because the file still contains it.
 * Delete either half and the other stops meaning anything.
 */
describe('shipped workflows round-trip without losing a node or a link', () => {
  const root = join(process.cwd(), 'workflows');
  const slugs = existsSync(root)
    ? readdirSync(root, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .filter((slug) => existsSync(join(root, slug, 'workflow.json')))
    : [];

  it('finds the shipped corpus', () => {
    expect(slugs.length).toBeGreaterThan(0);
  });

  it.each(slugs)('%s', (slug) => {
    const envelope = JSON.parse(readFileSync(join(root, slug, 'workflow.json'), 'utf8')) as Record<
      string,
      unknown
    > & { document?: StoredDocument };
    const stored = (envelope.document ?? (envelope as unknown as StoredDocument)) as StoredDocument;

    const workbench = new Workbench();
    // The same pre-registration the load path performs, so a workflow whose
    // own hand-authored family exists is measured against its real cards
    // rather than against the unknown-node placeholder.
    registerNodeTypesForRawDocument(stored, workbench.registry, workbench.engine.executors);
    const outcome = workbench.controller.document.importJSON(JSON.stringify(stored));
    expect(outcome.ok).toBe(true);

    const exported = workbench.controller.document.exportJSON();
    const written = JSON.parse(exported) as StoredDocument;

    // Every node, by id *and* type — a placeholder that round-tripped under
    // the wrong type would be a subtler loss than dropping it outright.
    expect(written.nodes.map((node) => `${node.id}:${node.type}`).sort()).toEqual(
      stored.nodes.map((node) => `${node.id}:${node.type}`).sort(),
    );
    // Every link, by its endpoints — the id is not written to the file.
    expect(written.edges.map(endpointKey).sort()).toEqual(stored.edges.map(endpointKey).sort());

    // And the bytes are stable: re-importing what we just wrote reproduces it
    // exactly, so a save loop can never drift a file it did not change.
    const second = new Workbench();
    registerNodeTypesForRawDocument(written, second.registry, second.engine.executors);
    second.controller.document.importJSON(exported);
    expect(second.controller.document.exportJSON()).toBe(exported);
  });
});
