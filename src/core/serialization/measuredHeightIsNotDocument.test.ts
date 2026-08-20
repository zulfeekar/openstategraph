import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * A measured pixel height is not part of a workflow (`production-ready` 69).
 *
 * Opening `?w=chinook-assistant` and pressing Save — no node touched, no
 * keystroke — rewrote five node heights, four by exactly 25 and one by 245.
 * Nobody authored any of it: the card bodies got shorter in a build shipped
 * since that file was last saved, and the browser measured them at save time.
 * A change to card styling silently rewrote every saved workflow the next
 * time it was opened and saved.
 *
 * ## Which part of `size` is authored, established against the code
 *
 * Both parts are, and that is why `size` stays in the document rather than
 * leaving it:
 *
 *  - **width** — nothing measures it. `NodeCard` reports its height with the
 *    *existing* width, so a width only ever comes from an authoring gesture:
 *    an assembly sizing the node it creates (`assemblies/starter.ts` builds a
 *    300-wide agent), `Arrange` refitting a frame, or the resize grip.
 *  - **height** — measured on every layout for every card but a container's
 *    frame, whose height is model-driven.
 *
 * So the split is not by node kind but by *where the value came from*, which
 * is what `SizeOrigin` names. An authored size is document state; a measured
 * one moves the card and stops there. The model still carries the measured
 * size — the minimap, `Arrange`, grouping and "where does the next node go"
 * all need the height that is really on screen.
 */
describe('a measured height is not document state', () => {
  it('leaves the exported document byte-identical when a card re-measures', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent, { at: { x: 40, y: 200 } });

    const before = workbench.controller.document.exportJSON();

    // Exactly what `NodeCard` does after layout: the DOM's height, the
    // existing width. A build that made the card 25px shorter looks like this.
    workbench.controller.nodes.applyMeasuredSize(agent.id, {
      width: agent.size.width,
      height: agent.size.height - 25,
    });

    expect(workbench.controller.document.exportJSON()).toBe(before);
  });

  it('still moves the card on screen, which is what the measurement is for', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent, { at: { x: 40, y: 200 } });
    const rendered = agent.size.height + 120;

    workbench.controller.nodes.applyMeasuredSize(agent.id, {
      width: agent.size.width,
      height: rendered,
    });

    expect(workbench.model.node(agent.id)?.size.height).toBe(rendered);
  });

  it('keeps a width an assembly authored, which no measurement ever touches', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent, { at: { x: 40, y: 200 } });
    const authoredHeight = agent.size.height;
    workbench.controller.nodes.resize(agent.id, { width: 300, height: authoredHeight });
    workbench.controller.nodes.applyMeasuredSize(agent.id, { width: 300, height: 1241 });

    const json = workbench.controller.document.exportJSON();
    expect(JSON.parse(json).nodes[0].size).toEqual({ width: 300, height: authoredHeight });
  });

  it('records a grip resize, which is the gesture the split exists to keep', () => {
    const workbench = makeWorkbench();
    const group = addNode(workbench, TYPE.group, { at: { x: 0, y: 0 } });
    workbench.controller.nodes.resize(group.id, { width: 640, height: 480 });

    const json = workbench.controller.document.exportJSON();
    expect(JSON.parse(json).nodes[0].size).toEqual({ width: 640, height: 480 });

    const reloaded = makeWorkbench();
    reloaded.controller.document.importJSON(json);
    expect(reloaded.model.node(group.id)?.size).toEqual({ width: 640, height: 480 });
  });

  it('round-trips a stored size a previous build measured, rather than restating it', () => {
    // The heights already in every saved package were measured by whatever
    // build last saved them. They are the document's now: loaded, laid out,
    // and written back unchanged — so this fix costs no file a diff.
    const first = makeWorkbench();
    const agent = addNode(first, TYPE.agent, { at: { x: 40, y: 200 } });
    const document = JSON.parse(first.controller.document.exportJSON()) as {
      nodes: [Record<string, unknown>];
    };
    document.nodes[0].size = { width: 280, height: 1241 };
    const stored = JSON.stringify(document);

    const reloaded = makeWorkbench();
    reloaded.controller.document.importJSON(stored);
    reloaded.controller.nodes.applyMeasuredSize(agent.id, { width: 280, height: 996 });

    expect(JSON.parse(reloaded.controller.document.exportJSON()).nodes[0].size).toEqual({
      width: 280,
      height: 1241,
    });
  });
});
