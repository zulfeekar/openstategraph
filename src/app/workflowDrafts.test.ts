import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import { newWriteGuard, saveWorkflow, type KeyValueStore } from '@app/workflowStore';
import { discardDraftAfterDelete, draftIdForSlug, restoreDraftFor } from '@app/workflowDrafts';

/** An in-memory `Storage`, so this runs in the node environment like `core/`. */
class FakeStore implements KeyValueStore {
  private readonly map = new Map<string, string>();
  get length(): number {
    return this.map.size;
  }
  key(index: number): string | null {
    return [...this.map.keys()][index] ?? null;
  }
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
  poison(key: string, value: string): void {
    this.map.set(key, value);
  }
}

/**
 * Ticket 23 — opening another workflow threw away unsaved edits, silently.
 *
 * The reproduction, in one paragraph: edit `chinook-assistant` without saving,
 * navigate to `concierge`, navigate back. The edit is gone, the only feedback
 * is a neutral "Opened: Chinook Assistant" toast, and there is no undo entry
 * to recover it from. A plain *reload* preserved the same draft, which is what
 * made the behaviour impossible to predict — the draft was keyed on the tab,
 * so it survived anything except pointing that tab at a second document.
 */
describe('per-slug drafts', () => {
  let store: FakeStore;

  const editorHolding = (workflowName: string): Workbench => {
    const workbench = new Workbench();
    workbench.model.setName(workflowName);
    return workbench;
  };

  beforeEach(() => {
    store = new FakeStore();
  });

  it('gives each workflow its own key, so one draft cannot overwrite another', () => {
    expect(draftIdForSlug('chinook-assistant')).not.toBe(draftIdForSlug('concierge'));
  });

  it('restores the unsaved edit made before the user opened another workflow', () => {
    // 1. Editing chinook-assistant: a node is added and autosaved.
    const editing = editorHolding('Chinook Assistant');
    addNode(editing, TYPE.markdownFile, { at: { x: 40, y: 40 } });
    const saved = saveWorkflow(
      store,
      draftIdForSlug('chinook-assistant'),
      editing.model,
      editing.serializer,
      newWriteGuard(),
    );
    expect(saved.ok).toBe(true);
    const draftedJSON = editing.controller.document.exportJSON();

    // 2. …then the file is opened again in a fresh session — a second
    //    workflow was opened in between, so nothing is in memory any more.
    const reopened = editorHolding('Chinook Assistant');
    const fileOnly = reopened.controller.document.exportJSON();
    const outcome = restoreDraftFor('chinook-assistant', reopened, store);

    expect(outcome.restored).toBe(true);
    expect(reopened.controller.document.exportJSON()).toBe(draftedJSON);
    expect(reopened.controller.document.exportJSON()).not.toBe(fileOnly);
  });

  it('says nothing, and changes nothing, when the draft matches the file', () => {
    // The ordinary case straight after a save. A toast here would train people
    // to ignore the one that matters.
    const workbench = editorHolding('Concierge');
    addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });
    saveWorkflow(
      store,
      draftIdForSlug('concierge'),
      workbench.model,
      workbench.serializer,
      newWriteGuard(),
    );

    // The file on the backend is the same document that was drafted — which
    // is the state straight after a Save, and the common case.
    const reopened = editorHolding('Concierge');
    reopened.controller.document.importJSON(workbench.controller.document.exportJSON());
    const before = reopened.controller.document.exportJSON();

    expect(restoreDraftFor('concierge', reopened, store).restored).toBe(false);
    expect(reopened.controller.document.exportJSON()).toBe(before);
  });

  it('leaves the file in place when this browser has no draft of that workflow', () => {
    const workbench = editorHolding('Workflow Architect');
    addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });
    const fromFile = workbench.controller.document.exportJSON();

    expect(restoreDraftFor('never-edited-here', workbench, store).restored).toBe(false);
    expect(workbench.controller.document.exportJSON()).toBe(fromFile);
  });

  it('keeps the file rather than a draft it cannot read', () => {
    // An unreadable draft is a recovery problem, not a reason to hand the user
    // an empty canvas in place of the workflow they asked for.
    const workbench = editorHolding('Chinook Assistant');
    addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });
    const fromFile = workbench.controller.document.exportJSON();
    store.poison(`openstategraph-workflow-${draftIdForSlug('chinook-assistant')}`, '{ not json');

    expect(restoreDraftFor('chinook-assistant', workbench, store).restored).toBe(false);
    expect(workbench.controller.document.exportJSON()).toBe(fromFile);
  });

  it('does not hand one workflow the draft of another', () => {
    // The defect stated directly: with a per-tab key, this is exactly what
    // happened — the second workflow opened on top of the first one's entry.
    const editing = editorHolding('Chinook Assistant');
    addNode(editing, TYPE.markdownFile, { at: { x: 40, y: 40 } });
    saveWorkflow(
      store,
      draftIdForSlug('chinook-assistant'),
      editing.model,
      editing.serializer,
      newWriteGuard(),
    );

    const other = editorHolding('Concierge');
    const fromFile = other.controller.document.exportJSON();

    expect(restoreDraftFor('concierge', other, store).restored).toBe(false);
    expect(other.controller.document.exportJSON()).toBe(fromFile);
  });

  it('drops this browser draft when the backend workflow is deleted, so a later same-slug workflow cannot adopt it', () => {
    const editing = editorHolding('Chinook Assistant');
    addNode(editing, TYPE.markdownFile, { at: { x: 40, y: 40 } });
    saveWorkflow(
      store,
      draftIdForSlug('chinook-assistant'),
      editing.model,
      editing.serializer,
      newWriteGuard(),
    );
    expect(store.getItem(`openstategraph-workflow-${draftIdForSlug('chinook-assistant')}`)).not.toBe(
      null,
    );

    discardDraftAfterDelete('chinook-assistant', store);

    expect(store.getItem(`openstategraph-workflow-${draftIdForSlug('chinook-assistant')}`)).toBe(
      null,
    );

    // A workflow later re-created under the same slug (e.g. the same title)
    // must not inherit a stranger's draft.
    const recreated = editorHolding('Chinook Assistant');
    const fromFile = recreated.controller.document.exportJSON();
    expect(restoreDraftFor('chinook-assistant', recreated, store).restored).toBe(false);
    expect(recreated.controller.document.exportJSON()).toBe(fromFile);
  });
});
