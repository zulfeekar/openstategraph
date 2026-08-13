import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { Ok, type Result } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { forgetKnownSavedAt, getKnownSavedAt } from '@app/workflowFileWatch';
import { parseMountAddress } from '@core/model/MountAddress';
import { loadMountIntoEditor } from './loadWorkflowIntoEditor';

/**
 * Adversarial: the compare-and-set guard on an instance save (QA pass,
 * 2026-08-13).
 *
 * `WorkflowManager.handleSave` (instance branch) writes the WHOLE retained
 * parent document back to `address.root`, guarded by a compare-and-set on the
 * parent's `savedAt` — `getKnownSavedAt(address.root)`. The guard's own
 * comment says why: this save "would silently revert someone else's parent
 * edit".
 *
 * `loadMountIntoEditor` used to baseline only the CLASS slug. Nothing recorded
 * a baseline for `address.root`, so on a fresh deep link to
 * `?w=concierge/wf-music` the `baseline &&` short-circuit disabled the guard
 * and the first save of an override overwrote any parent edit made since the
 * instance was opened.
 *
 * **Fixed 2026-08-13**: both are baselined, and both tests below now pass —
 * the class because it backs what is on screen, the root because it is the
 * file an instance save actually writes. Keep both assertions: dropping either
 * baseline is a silent regression in a different failure mode.
 */

const CHILD_EFFECTIVE = {
  version: 2,
  name: 'chinook-assistant',
  nodes: [{ id: 'agent-sql', type: 'agent.llm', position: { x: 0, y: 0 }, data: {} }],
  edges: [],
};

const PARENT = {
  version: 2,
  name: 'concierge',
  nodes: [
    { id: 'wf-music', type: 'workflow.subgraph', data: { workflow: 'chinook-assistant' } },
  ],
  edges: [],
};

const client: IWorkflowFileClient = {
  load: (): Promise<Result<unknown, string>> => Promise.resolve(Ok(PARENT)),
  loadMount: () =>
    Promise.resolve(
      Ok({
        root: 'concierge',
        slug: 'chinook-assistant',
        mountPath: ['wf-music'],
        document: CHILD_EFFECTIVE,
        warnings: [],
      }),
    ),
  capabilities: () => Promise.resolve(Ok({ tools: [], pluginTools: [], warnings: [] })),
  summary: (slug: string) =>
    Promise.resolve(Ok({ slug, name: slug, savedAt: '2026-08-13T00:00:00Z', nodeCount: 1 })),
} as unknown as IWorkflowFileClient;

describe('instance-open baselines and the parent save guard', () => {
  beforeEach(() => {
    forgetKnownSavedAt('concierge');
    forgetKnownSavedAt('chinook-assistant');
  });

  it('baselines the class slug, as documented', async () => {
    const outcome = await loadMountIntoEditor(parseMountAddress('concierge/wf-music')!, client, new Workbench());
    expect(outcome.ok).toBe(true);
    expect(getKnownSavedAt('chinook-assistant')).toBe('2026-08-13T00:00:00Z');
  });

  // FIXED 2026-08-13. Was `it.fails`: no baseline was recorded for the PARENT
  // the save guard checks, so on a fresh deep link the compare-and-set in
  // `WorkflowManager.handleSave` short-circuited on `baseline && …` and the
  // first instance save could clobber a concurrent edit to the parent.
  it('also baselines the parent root the save guard compares against', async () => {
    await loadMountIntoEditor(parseMountAddress('concierge/wf-music')!, client, new Workbench());
    expect(getKnownSavedAt('concierge')).toBe('2026-08-13T00:00:00Z');
  });
});
