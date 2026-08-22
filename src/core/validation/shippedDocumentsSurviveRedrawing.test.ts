import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';
import { maxConnectionsOf } from '@core/model/contracts/ports';

/**
 * Every document this repository ships must be one its own editor can express.
 *
 * The defect this pins (`workflow-gallery/13`): `templates/routed-qa` wired two
 * edges into `out1/result`, a port whose `maxConnections` is 1. Nothing on the
 * load path enforces capacity, so the document opened and compiled — and then
 * `capacityRule` resolved the second link by *replacing* the first. The
 * scaffolded workflow worked exactly once: redraw either branch in the editor
 * and the other silently vanished, looking for all the world like the editor
 * ate the user's link.
 *
 * The check is deliberately run through the **real rule chain** rather than by
 * counting edges against the generated port catalogue. Counting would restate
 * `capacityRule`'s arithmetic in a second place and stay green if the rule
 * changed; asking the validator whether it would *replace* something is the
 * question a user's mouse asks, and dynamic ports (a router's `branch:<slug>`
 * outputs) resolve themselves because the real node models are the ones
 * answering.
 */

const REPO = join(__dirname, '..', '..', '..');

/**
 * Where a shipped document lives. `templates/` and `examples/` ship inside the
 * Python distribution, so everything under them counts. `workflows/` is also a
 * working directory — a developer's own packages and the editor's autosaves
 * land there — so only the ones this repository *tracks* are shipped, and an
 * untracked local package must not be able to turn this suite red.
 */
const SHIPPED_ROOTS = [
  { label: 'templates', dir: join(REPO, 'backend', 'openstategraph', 'templates'), trackedOnly: false },
  { label: 'examples', dir: join(REPO, 'backend', 'openstategraph', 'examples'), trackedOnly: false },
  { label: 'workflows', dir: join(REPO, 'workflows'), trackedOnly: true },
];

/** The `workflow.json` paths git knows about, or `null` outside a checkout. */
function trackedDocuments(): Set<string> | null {
  try {
    const out = execFileSync('git', ['ls-files', '-z', '*/workflow.json'], {
      cwd: REPO,
      encoding: 'utf8',
    });
    return new Set(out.split('\0').filter(Boolean).map((rel) => join(REPO, rel)));
  } catch {
    return null;
  }
}

const TRACKED = trackedDocuments();

/**
 * Known violations, each with the ticket that owns it. **This list may only
 * shrink.** A document on it is asserted to *still* violate at exactly these
 * ports, so an entry cannot rot into a permanent exemption for something
 * already fixed, and a second violation appearing on a listed document is
 * still a failure.
 *
 * **It is empty, and getting there is `workflow-gallery/64`'s account of
 * itself.** It held four entries in two families:
 *
 * - `out1/result` on `concierge` and `chinook-assistant` — ticket 13's shape,
 *   whose answer was one `output.formatted` per exclusive branch, carried by
 *   ticket 63.
 * - `grader1/candidate` on `examples/support-triage` and `agent-chat/prompt`
 *   on `chinook-assistant` — where that answer would have duplicated a
 *   grader's rubric or an agent's system prompt, which is duplication of
 *   *knowledge* and the thing DRY actually forbids.
 *
 * All four came off in one move, and none of the four documents changed a
 * line. The defect was never in them: `capacityRule` was counting **edges
 * drawn** where the ambiguity a cap exists to forbid is **producers that can
 * arrive in the same run**. A router takes one branch, so its branches cannot
 * race, however many of them converge — see `concurrentProducers.ts`. Which
 * also retires 63: the two packages it was going to edit are expressible as
 * they stand.
 *
 * So an entry appearing here again is a regression, not a backlog item.
 */
const KNOWN_VIOLATIONS: Record<string, readonly string[]> = {};

interface Doc {
  readonly key: string;
  readonly document: { nodes: { id: string; type: string }[]; edges: unknown[] };
  readonly text: string;
}

function discover(): Doc[] {
  const found: Doc[] = [];
  for (const { label, dir, trackedOnly } of SHIPPED_ROOTS) {
    if (!existsSync(dir)) continue;
    for (const slug of readdirSync(dir).sort()) {
      const file = join(dir, slug, 'workflow.json');
      if (!existsSync(file)) continue;
      if (trackedOnly && TRACKED && !TRACKED.has(file)) continue;
      const raw = JSON.parse(readFileSync(file, 'utf8')) as Record<string, unknown>;
      // Packages saved by the product carry an envelope; hand-written
      // templates are the bare document. Reading only the bare shape is how a
      // first sweep of this defect saw one violation where there were five.
      const document = (raw['document'] ?? raw) as Doc['document'];
      if (!Array.isArray(document?.nodes)) continue;
      found.push({ key: `${label}/${slug}`, document, text: JSON.stringify(document) });
    }
  }
  return found;
}

const DOCUMENTS = discover();

/**
 * The gesture: delete one link and draw it again — the ordinary way a person
 * re-points a wire. Validating an edge that is *still* in the model answers
 * "these ports are already connected" and tells us nothing, so each edge is
 * lifted out of a freshly loaded document before its own endpoints are asked.
 * Anything the validator then offers to replace is a *different* link about to
 * lose its place without the user asking.
 */
function overCapacityPorts(doc: Doc): string[] {
  const probe = makeWorkbench();
  if (!probe.serializer.loadFromText(probe.model, doc.text).ok) return [];
  const edges = probe.model.edges().map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
  }));

  const over = new Set<string>();
  for (const edge of edges) {
    const workbench = makeWorkbench();
    workbench.serializer.loadFromText(workbench.model, doc.text);
    workbench.model.removeEdge(edge.id);
    const verdict = workbench.connectionValidator.validate(edge.source, edge.target);
    if (!verdict.ok) continue;
    if (verdict.replaces.length > 0) over.add(`${edge.target.nodeId}/${edge.target.portId}`);
  }
  return [...over].sort();
}

describe('shipped documents survive being redrawn', () => {
  it('finds the shipped documents at all', () => {
    // A discovery bug here would make every assertion below vacuously green.
    expect(DOCUMENTS.length).toBeGreaterThan(20);
    expect(DOCUMENTS.map((d) => d.key)).toContain('templates/routed-qa');
  });

  for (const doc of DOCUMENTS) {
    const expected = [...(KNOWN_VIOLATIONS[doc.key] ?? [])].sort();

    it(`${doc.key} wires no more links into a port than it allows`, () => {
      expect(overCapacityPorts(doc)).toEqual(expected);
    });
  }

  it('the capacity cap on a formatted output is still one', () => {
    // The premise the whole sweep rests on. If this port ever became an
    // unlimited fan-in (option 2, rejected), every assertion above would pass
    // for the wrong reason and nobody would be told.
    const workbench2 = makeWorkbench();
    const node = addNode(workbench2, 'output.formatted');
    const result = node.port('result');
    expect(result).toBeDefined();
    expect(maxConnectionsOf(result!)).toBe(1);
  });
});
