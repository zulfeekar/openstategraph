import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * Naming semantics.
 *
 * The model normalises names on write: titles are trimmed, a blank title falls
 * back to the node type's label, and a blank workflow name falls back to
 * "Untitled workflow". That is right for *stored* data — trailing whitespace in
 * `workflow.json` is diff noise, and a blank header renders as nothing.
 *
 * These tests exist because that normalisation is also a trap for the view. A
 * fully controlled input that writes every keystroke reads the normalised value
 * straight back, so typing a space produces `"My "`, gets `"My"` back, and the
 * space vanishes — making a two-word name untypeable. The fix is the draft
 * buffer in `useDraftValue`, **not** removing the normalisation. Anyone tempted
 * to delete a `.trim()` here to "fix typing" should read this file first: these
 * assertions are the contract, and the buffering belongs in the editor.
 */
describe('node titles', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('falls back to the type label when no title is set', () => {
    const node = addNode(workbench, TYPE.agent);
    expect(node.title).toBe(node.definition.label);
  });

  it('uses an explicit title once set', () => {
    const node = addNode(workbench, TYPE.agent);
    workbench.controller.nodes.setTitle(node.id, 'Trend analyst');
    expect(workbench.model.node(node.id)?.title).toBe('Trend analyst');
  });

  it('trims surrounding whitespace, so it never reaches the document', () => {
    const node = addNode(workbench, TYPE.agent);
    workbench.controller.nodes.setTitle(node.id, '  Trend analyst  ');
    expect(workbench.model.node(node.id)?.title).toBe('Trend analyst');
  });

  it('preserves interior spaces — a multi-word name is a normal name', () => {
    const node = addNode(workbench, TYPE.agent);
    workbench.controller.nodes.setTitle(node.id, 'SQL query planner');
    expect(workbench.model.node(node.id)?.title).toBe('SQL query planner');
  });

  it('reverts to the type label when cleared', () => {
    const node = addNode(workbench, TYPE.agent);
    workbench.controller.nodes.setTitle(node.id, 'Trend analyst');
    workbench.controller.nodes.setTitle(node.id, '');

    // The consequence the view must absorb: clearing the field does not leave
    // the title blank, it makes `title` report the label again.
    expect(workbench.model.node(node.id)?.title).toBe(node.definition.label);
  });

  it('is undoable as one step per burst, not per keystroke', () => {
    const node = addNode(workbench, TYPE.agent);
    workbench.controller.nodes.setTitle(node.id, 'T');
    workbench.controller.nodes.setTitle(node.id, 'Tr');
    workbench.controller.nodes.setTitle(node.id, 'Trend');

    workbench.controller.history.undo();

    expect(workbench.model.node(node.id)?.title).toBe(node.definition.label);
  });

  it('survives a round trip through JSON', () => {
    const node = addNode(workbench, TYPE.agent);
    workbench.controller.nodes.setTitle(node.id, 'Trend analyst');

    const reloaded = makeWorkbench();
    reloaded.controller.document.importJSON(workbench.controller.document.exportJSON());

    expect(reloaded.model.node(node.id)?.title).toBe('Trend analyst');
  });

  it('does not write a title that is only the fallback', () => {
    addNode(workbench, TYPE.agent);
    const document = JSON.parse(workbench.controller.document.exportJSON()) as {
      nodes: Record<string, unknown>[];
    };
    // Storing the label as a title would freeze it — renaming the node type
    // later would leave every existing node showing the old label.
    for (const serialized of document.nodes) expect(serialized).not.toHaveProperty('title');
  });
});

describe('workflow name', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('trims and keeps interior spaces', () => {
    workbench.controller.document.setName('  Chinook explorer  ');
    expect(workbench.model.name).toBe('Chinook explorer');
  });

  it('falls back rather than allowing a nameless document', () => {
    workbench.controller.document.setName('Chinook explorer');
    workbench.controller.document.setName('   ');
    expect(workbench.model.name).toBe('Untitled workflow');
  });
});
