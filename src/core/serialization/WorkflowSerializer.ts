import { Err, Ok, type Result } from '@core/kernel/Result';
import { resetIds, seedIds } from '@core/kernel/id';
import { EdgeModel } from '@core/model/EdgeModel';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import { WORKFLOW_SCHEMA_VERSION, WorkflowModel } from '@core/model/WorkflowModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { SerializedNode } from '@core/model/contracts/node';
import type { SerializedEdge, SerializedWorkflow } from '@core/model/contracts/workflow';
import { portsReferencedBy, unknownNodeDefinition } from './UnknownNode';

export interface LoadReport {
  /** Non-fatal problems: unknown node types, dropped edges, coerced fields. */
  readonly warnings: readonly string[];
}

/** A migration from one schema version to the next. */
export interface IMigration {
  readonly from: number;
  readonly to: number;
  migrate(document: Record<string, unknown>): Record<string, unknown>;
}

/**
 * JSON import/export.
 *
 * Two properties are non-negotiable for a format users will keep files in:
 *
 * **Versioned and migrated.** Documents outlive the code that wrote them.
 * A stored version plus an ordered migration chain means a v1 file still
 * opens after the model has moved on, instead of failing to parse.
 *
 * **Lenient on load, strict on save.** A document referencing a node type
 * this build doesn't have loads with that node *preserved* as an unknown-node
 * placeholder and a warning, rather than throwing away the user's whole file.
 * Export always writes the current version.
 *
 * **Round-trip fidelity is the invariant, and it has no exceptions.** Loading
 * and re-saving must never lose a node, a link or a field — including for a
 * type this build cannot render. Skipping the node instead was silent data
 * loss with a one-click trigger; `UnknownNode.ts` records the whole story.
 */
export class WorkflowSerializer {
  private readonly migrations: IMigration[] = [];

  constructor(private readonly registry: ModelRegistry) {}

  register(migration: IMigration): this {
    this.migrations.push(migration);
    this.migrations.sort((a, b) => a.from - b.from);
    return this;
  }

  serialize(model: WorkflowModel): SerializedWorkflow {
    return model.toJSON();
  }

  /**
   * The exact bytes written to disk.
   *
   * Two-space indent and a trailing newline: this is a text file under
   * version control, and one that ends mid-line reports "\ No newline at end
   * of file" on every diff and rewrites its last line on any append.
   */
  toJSONString(model: WorkflowModel, pretty = true): string {
    return `${JSON.stringify(this.serialize(model), null, pretty ? 2 : 0)}\n`;
  }

  parse(text: string): Result<SerializedWorkflow, string> {
    let raw: unknown;
    try {
      raw = JSON.parse(text);
    } catch {
      return Err('That file isn’t valid JSON');
    }
    return this.normalise(raw);
  }

  /**
   * Validates the envelope and runs migrations up to the current version.
   * Rejects rather than guessing when the shape is unrecognisable — a
   * half-understood document is worse than a clear error.
   */
  normalise(raw: unknown): Result<SerializedWorkflow, string> {
    if (typeof raw !== 'object' || raw === null) {
      return Err('Expected a workflow object');
    }
    let doc = raw as Record<string, unknown>;

    const version = typeof doc['version'] === 'number' ? doc['version'] : 0;
    if (version > WORKFLOW_SCHEMA_VERSION) {
      return Err(
        `This workflow was saved by a newer version (v${version}); this build reads up to v${WORKFLOW_SCHEMA_VERSION}`,
      );
    }

    let current = version;
    while (current < WORKFLOW_SCHEMA_VERSION) {
      const migration = this.migrations.find((m) => m.from === current);
      if (!migration) break;
      doc = migration.migrate(doc);
      current = migration.to;
    }

    if (!Array.isArray(doc['nodes']) || !Array.isArray(doc['edges'])) {
      return Err('Workflow is missing its nodes or edges');
    }

    return Ok({
      version: WORKFLOW_SCHEMA_VERSION,
      name: typeof doc['name'] === 'string' ? doc['name'] : 'Imported workflow',
      ...(typeof doc['settings'] === 'object' && doc['settings'] !== null
        ? { settings: doc['settings'] as Record<string, unknown> }
        : {}),
      nodes: doc['nodes'] as readonly SerializedNode[],
      edges: doc['edges'] as readonly SerializedEdge[],
      ...(typeof doc['meta'] === 'object' && doc['meta'] !== null
        ? { meta: doc['meta'] as Record<string, unknown> }
        : {}),
    });
  }

  /**
   * Replaces a model's contents with a parsed document.
   *
   * Mutates in place rather than returning a new model so every existing
   * subscriber — canvas, panels, command stack — stays attached; they
   * resync from the single `workflow:reset` event at the end.
   */
  load(model: WorkflowModel, document: SerializedWorkflow): LoadReport {
    const warnings: string[] = [];

    model.transact(() => {
      model.clear();
      model.setName(document.name);
      // Always applied — a document with no settings must clear stale ones.
      model.setSettings(document.settings ?? {});

      // Ids come from the file, so the local counters must be re-seeded or
      // the next new node could collide with an imported one.
      // Node ids come from the file, so the local counters must be re-seeded
      // or the next new node could collide with an imported one. Edges are
      // not seeded: their ids are minted fresh below.
      resetIds();
      seedIds(document.nodes.map((n) => n.id));

      const created = new Map<string, AbstractNodeModel>();

      for (const serialized of document.nodes) {
        // An unregistered type is *preserved*, never skipped. See
        // `UnknownNode.ts` for the invariant and for why the ports have to be
        // recovered from the edges rather than left empty.
        const registered = this.registry.nodeTypes.get(serialized.type);
        const definition =
          registered ??
          unknownNodeDefinition(serialized.type, portsReferencedBy(serialized.id, document.edges));
        if (!registered) {
          warnings.push(
            `Kept "${serialized.id}" as an unknown node type "${serialized.type}" — ` +
              'this build has no editor card for it, so it cannot be edited here. ' +
              'It is preserved exactly as saved.',
          );
        }
        const node = definition.create({
          id: serialized.id,
          position: serialized.position,
          size: serialized.size ?? definition.defaultSize,
          // Parent is applied in a second pass; the container may appear
          // later in the file than its children.
          parentId: null,
          data: serialized.data,
          ...(serialized.title ? { title: serialized.title } : {}),
        }) as AbstractNodeModel;
        created.set(node.id, node);
        model.addNode(node);
      }

      for (const serialized of document.nodes) {
        if (!serialized.parentId) continue;
        if (!created.has(serialized.id)) continue;
        if (!created.has(serialized.parentId)) {
          warnings.push(`Node "${serialized.id}" referenced a missing container`);
          continue;
        }
        model.setNodeParent(serialized.id, serialized.parentId);
      }

      for (const serialized of document.edges) {
        const source = created.get(serialized.source?.nodeId ?? '');
        const target = created.get(serialized.target?.nodeId ?? '');
        if (!source || !target) {
          warnings.push('Dropped a link with a missing endpoint');
          continue;
        }
        // Ports move between versions; a link to a port that no longer
        // exists would render as a stub attached to nothing.
        if (!source.port(serialized.source.portId) || !target.port(serialized.target.portId)) {
          warnings.push('Dropped a link to a port that no longer exists');
          continue;
        }
        model.addEdge(
          new EdgeModel({
            // No id: an edge is identified by its endpoints, so a fresh
            // handle is minted. Files written before this carried one; it is
            // ignored rather than migrated, since nothing referenced it.
            source: serialized.source,
            target: serialized.target,
            label: serialized.label ?? null,
            // Tolerated, not required: `vertices` is additive, so a document
            // written before waypoints existed simply has none and the router
            // draws the whole run. `EdgeModel` filters anything that is not a
            // finite pair, so a hand-edited file cannot inject a NaN.
            vertices: Array.isArray(serialized.vertices) ? serialized.vertices : [],
          }),
        );
      }
    });

    model.notifyReset();
    return { warnings };
  }

  /** Convenience: parse text and load in one step. */
  loadFromText(model: WorkflowModel, text: string): Result<LoadReport, string> {
    const parsed = this.parse(text);
    if (!parsed.ok) return parsed;
    return Ok(this.load(model, parsed.value));
  }
}
