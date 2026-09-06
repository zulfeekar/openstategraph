import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';
import { AbstractNodeModel } from './AbstractNodeModel';

/**
 * A node's geometry can never hold `NaN` or `Infinity` (ticket 46, item 1).
 *
 * `EdgeModel.clean` has enforced this for waypoints since it was written, and
 * its comment calls itself *"the one door they can come through"* — while
 * `write.position` / `write.size` assigned `{...position}` verbatim from
 * canvas drags, and the loader passed `serialized.position` straight through.
 * Two more doors, and the second is the one a hand-edited file walks in by.
 *
 * The cost is CLAUDE.md's standing rule arriving through the route its own
 * worked example documents: `JSON.stringify(NaN)` is `"null"`, so the number
 * would leave as `"x": null`, reload as a node at nowhere, and nothing
 * anywhere would report the loss. Production-ready 42 established that the
 * canvas does reach the file on disk, which is what makes this reachable
 * rather than theoretical.
 *
 * **The policy is per-axis fallback, not rejection.** A node must have a
 * position, so there is nothing to drop — an edge can lose a waypoint and
 * still be an edge. Keeping the last good value for the bad axis is the only
 * outcome that leaves the document writable and the node where the user can
 * still see it.
 */

const TEXT_INPUT = 'input.text';

describe('a node write', () => {
  it('keeps the last good coordinate when handed a NaN', () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, TEXT_INPUT, { at: { x: 100, y: 200 } });

    workbench.model.moveNode(node.id, { x: Number.NaN, y: 260 });

    expect(node.position).toEqual({ x: 100, y: 260 });
  });

  it('refuses an infinite coordinate too', () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, TEXT_INPUT, { at: { x: 100, y: 200 } });

    workbench.model.moveNode(node.id, { x: 40, y: Number.POSITIVE_INFINITY });

    expect(node.position).toEqual({ x: 40, y: 200 });
  });

  it('keeps the last good size when handed a non-finite one', () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, TEXT_INPUT);
    const before = node.size;

    workbench.model.resizeNode(node.id, { width: Number.NaN, height: 400 });

    expect(node.size).toEqual({ width: before.width, height: 400 });
  });

  it('lets an ordinary move through untouched', () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, TEXT_INPUT, { at: { x: 0, y: 0 } });

    workbench.model.moveNode(node.id, { x: -32, y: 16.5 });

    expect(node.position).toEqual({ x: -32, y: 16.5 });
  });

  it('never lets one out through the serializer', () => {
    // The consequence, stated as the rule states it: a non-finite number is
    // not representable in JSON, so this is what "unwritable document" means.
    const workbench = makeWorkbench();
    const node = addNode(workbench, TEXT_INPUT, { at: { x: 10, y: 10 } });

    workbench.model.moveNode(node.id, { x: Number.NaN, y: Number.NaN });

    const written = JSON.parse(JSON.stringify(node.toJSON())) as {
      position: { x: unknown; y: unknown };
    };

    // Not "contains no null" — `parentId` is legitimately one. The claim is
    // about the numbers: a `NaN` here would have come back as `null`.
    expect(written.position).toEqual({ x: 10, y: 10 });
  });

  it('closes the loader door as well', () => {
    // A hand-edited or truncated file. `definition.create` is what the
    // serializer calls, so guarding the constructor guards the load.
    const workbench = makeWorkbench();
    const definition = workbench.registry.nodeTypes.require(TEXT_INPUT);

    const node = definition.create({
      position: { x: Number.NaN, y: 12 },
      size: { width: Number.POSITIVE_INFINITY, height: 80 },
    }) as AbstractNodeModel;

    expect(node.position).toEqual({ x: 0, y: 12 });
    expect(node.size).toEqual({ width: definition.defaultSize.width, height: 80 });
  });

  it('lands a node with no position at all at the origin', () => {
    // `NodeInit` says `position` is there; a file is under no obligation to
    // agree, and the serializer forwards whatever it read. This used to spread
    // to `{x: undefined}` — not a number, not a null, and not something any
    // later code checked for.
    const workbench = makeWorkbench();
    const definition = workbench.registry.nodeTypes.require(TEXT_INPUT);

    const node = definition.create({} as Parameters<typeof definition.create>[0]);

    expect(node.position).toEqual({ x: 0, y: 0 });
    expect(node.size).toEqual(definition.defaultSize);
  });
});
