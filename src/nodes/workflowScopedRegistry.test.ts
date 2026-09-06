import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { defineNode } from '@core/model/ModelRegistry';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { Ok, type Result } from '@core/kernel/Result';
import type { INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
import {
  registerNodeTypesForRawDocument,
  syncWorkflowScopedNodes,
  workflowScopedFamilies,
} from './workflowScoped';

/**
 * A second workflow-scoped family costs no engine edit — ship-it ticket 03.
 *
 * `docs/building-an-atom.md` told a contributor to "add `DICE_NODES` to
 * `syncWorkflowScopedNodes`". That function had nothing to add it to: it named
 * `CHINOOK_NODES` in its own body, and so did `registerNodeTypesForRawDocument`
 * and `registerScopedFamily` — three places, one hardcoded family.
 *
 * That is the **O** in this project's own SOLID list, broken in the one place
 * it is broken: *extend by registering, never by editing the engine.* Node
 * types, executors, providers, connection rules, validation rules, canvas
 * features and card bodies are all a `Registry<T>`; this was a named import.
 *
 * The useful signal was that the guide **could not be written correctly**,
 * because there was nothing correct to describe. The documentation failed
 * because the seam was missing, not because the sentence was sloppy — so this
 * file registers a family exactly the way the guide now says to, and would
 * fail if that stopped working.
 *
 * The second family below is deliberately built here rather than imported:
 * a test that used a family the engine already knows about could pass while
 * the seam stayed closed.
 */
class DiceModel extends AbstractNodeModel {}

const DICE_NODES = [1, 2].map((n) => {
  const definition = defineNode(
    {
      id: `tool.dice-${n}`,
      category: 'tools',
      label: `Dice ${n}`,
      description: 'A second workflow-scoped family, invented by this test.',
      iconId: 'node-tool',
      accent: 'violet',
      defaultSize: { width: 200, height: 100 },
      scope: 'workflow',
      fields: [],
      ports: [],
    },
    DiceModel,
  );
  const executor: INodeExecutor = {
    id: definition.id,
    execute: (): Promise<Result<PortOutputs, string>> => Promise.resolve(Ok({})),
  };
  return { definition, executor };
});

/** Registers the test family and returns the undo, so no test leaks into another. */
function withDice(): () => void {
  workflowScopedFamilies.register({ id: 'dice', nodes: DICE_NODES });
  return () => workflowScopedFamilies.unregister('dice');
}

const diceIds = DICE_NODES.map((n) => n.definition.id);
const chinookIds = CHINOOK_NODES.map((n) => n.definition.id);
const documentWith = (type: string) => ({ nodes: [{ id: 'n1', type }], edges: [] });

describe('a second workflow-scoped family, added by registering it', () => {
  it('is not in a fresh palette, exactly like the first', () => {
    const undo = withDice();
    try {
      const workbench = new Workbench();
      for (const id of diceIds) expect(workbench.registry.nodeTypes.get(id)).toBeUndefined();
    } finally {
      undo();
    }
  });

  it('registers from a document that uses it, before that document is imported', () => {
    // The load-order rule this module exists for: `WorkflowSerializer`
    // silently skips a node whose type is unregistered, so a family that is
    // only registered *after* the import can never arrive at all. The guide
    // never mentioned this second call site, so a contributor following it
    // would have shipped a family that vanished on every load.
    const undo = withDice();
    try {
      const workbench = new Workbench();
      registerNodeTypesForRawDocument(
        documentWith(diceIds[0]!),
        workbench.registry,
        workbench.engine.executors,
      );
      for (const id of diceIds) expect(workbench.registry.nodeTypes.get(id)).toBeDefined();
    } finally {
      undo();
    }
  });

  it('registers the whole family when the open document uses one of it', () => {
    const undo = withDice();
    try {
      const workbench = new Workbench();
      registerNodeTypesForRawDocument(
        documentWith(diceIds[0]!),
        workbench.registry,
        workbench.engine.executors,
      );
      workbench.controller.document.importJSON(JSON.stringify(documentWith(diceIds[0]!)));
      syncWorkflowScopedNodes(workbench.model, workbench.registry, workbench.engine.executors);
      for (const id of diceIds) expect(workbench.registry.nodeTypes.get(id)).toBeDefined();
    } finally {
      undo();
    }
  });

  it('unregisters again when the document stops using it', () => {
    const undo = withDice();
    try {
      const workbench = new Workbench();
      registerNodeTypesForRawDocument(
        documentWith(diceIds[0]!),
        workbench.registry,
        workbench.engine.executors,
      );
      workbench.controller.document.importJSON(JSON.stringify({ nodes: [], edges: [] }));
      syncWorkflowScopedNodes(workbench.model, workbench.registry, workbench.engine.executors);
      for (const id of diceIds) expect(workbench.registry.nodeTypes.get(id)).toBeUndefined();
    } finally {
      undo();
    }
  });

  it('is stamped workflow-scoped, so it stays out of the always-available palette', () => {
    const undo = withDice();
    try {
      const workbench = new Workbench();
      registerNodeTypesForRawDocument(
        documentWith(diceIds[0]!),
        workbench.registry,
        workbench.engine.executors,
      );
      expect(workbench.registry.nodeTypes.get(diceIds[0]!)?.scope).toBe('workflow');
    } finally {
      undo();
    }
  });

  it('leaves the other family alone in both directions', () => {
    // Two families must be independent, or the registry is a list with extra
    // steps: a document using one must not drag the other into the palette.
    const undo = withDice();
    try {
      const workbench = new Workbench();
      registerNodeTypesForRawDocument(
        documentWith(diceIds[0]!),
        workbench.registry,
        workbench.engine.executors,
      );
      for (const id of chinookIds) expect(workbench.registry.nodeTypes.get(id)).toBeUndefined();

      const other = new Workbench();
      registerNodeTypesForRawDocument(
        documentWith(chinookIds[0]!),
        other.registry,
        other.engine.executors,
      );
      for (const id of diceIds) expect(other.registry.nodeTypes.get(id)).toBeUndefined();
    } finally {
      undo();
    }
  });
});

describe('the built-in family is registered, not imported', () => {
  it('Chinook is an entry in the registry like any other', () => {
    // The claim that makes the guide true: nothing about Chinook is special
    // any more except that it ships registered.
    expect(workflowScopedFamilies.get('chinook')?.nodes).toBe(CHINOOK_NODES);
  });
});
