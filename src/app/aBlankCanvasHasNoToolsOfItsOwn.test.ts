import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import type { ToolCapability } from '@core/runtime/WorkflowFileClient';
import { clearOpenSlug, setOpenSlug } from '@app/openWorkflow';
import {
  capabilityBackedTypeIds,
  forgetCapabilityBackedTypeIds,
  packageScopedNodes,
  registerDiscoveredCapabilities,
} from '@nodes/workflowScoped';
import {
  followOpenPackage,
  forgetKnownCapabilities,
  refreshWorkflowCapabilities,
} from '@app/capabilityRefresh';

/**
 * production-ready/75 — a blank canvas offering the last package's tools as
 * its own.
 *
 * The palette's "This workflow" section promises *"From this workflow's own
 * package"*. A document that has no package therefore has nothing to put
 * there, and **New** produces exactly that document: `createNewWorkflow`
 * calls `clearOpenSlug()`, and from then on there is no slug for anyone to
 * ask the backend about. Nothing used to answer that announcement, so the set
 * `registerDiscoveredCapabilities` recorded while the *previous* package was
 * open stayed standing, and its discovered tool was still offered for
 * placement — into a document where its type id resolves to nothing.
 *
 * The assertions below are deliberately about the palette's own answer
 * (`packageScopedNodes`) rather than about the store, because a store that
 * empties is not the same fact as a section that stops offering another
 * package's tool.
 */
const bespoke: ToolCapability = {
  id: 'bespoke/tools.BespokeThingTool',
  name: 'bespoke_thing',
  description: 'Echo back whatever it is given.',
  argsSchema: {},
  nodeType: '',
};

function offered(workbench: Workbench): string[] {
  return packageScopedNodes(workbench.registry.paletteSections(), capabilityBackedTypeIds()).map(
    (definition) => definition.id,
  );
}

describe('a document with no package has no tools of its own', () => {
  beforeEach(() => {
    forgetCapabilityBackedTypeIds();
    forgetKnownCapabilities();
    clearOpenSlug();
  });

  it('stops offering the last package’s discovered tool once the slug is gone', () => {
    const workbench = new Workbench();
    setOpenSlug('bespoke');
    const stop = followOpenPackage();
    registerDiscoveredCapabilities(
      [bespoke],
      workbench.registry,
      workbench.engine.executors,
    );
    expect(offered(workbench)).toEqual([bespoke.id]);

    clearOpenSlug(); // what `createNewWorkflow` does, through the real channel

    expect(offered(workbench)).toEqual([]);
    // Registration is untouched on purpose: CLAUDE.md's `code → canvas` rule
    // requires a package-scoped node to load as its real card wherever the
    // type is known, and `add0e6e` settled that registered-and-unbacked is a
    // correct state. Only the *offer* is withdrawn.
    expect(workbench.registry.nodeTypes.get(bespoke.id)).toBeDefined();
    stop();
  });

  it('keeps the standing answer while another package is being opened', () => {
    const workbench = new Workbench();
    setOpenSlug('bespoke');
    const stop = followOpenPackage();
    registerDiscoveredCapabilities([bespoke], workbench.registry, workbench.engine.executors);

    // Opening another package announces its slug before its capabilities have
    // been fetched. That is an in-flight state, not an answer, and it must not
    // read the same as having no package at all — otherwise every load would
    // blank the section and refill it, and a fetch that never resolves would
    // be indistinguishable from a blank canvas.
    setOpenSlug('other-package');

    expect(offered(workbench)).toEqual([bespoke.id]);
    stop();
  });

  it('empties the section when a refresh is asked for with no slug to ask about', async () => {
    const workbench = new Workbench();
    registerDiscoveredCapabilities([bespoke], workbench.registry, workbench.engine.executors);

    const outcome = await refreshWorkflowCapabilities(
      null,
      workbench.registry,
      workbench.engine.executors,
      {
        capabilities: () => {
          throw new Error('a document with no slug must not be fetched for');
        },
      } as never,
    );

    expect(outcome).toEqual({ kind: 'no-workflow' });
    expect(offered(workbench)).toEqual([]);
    expect(workbench.registry.nodeTypes.get(bespoke.id)).toBeDefined();
  });
});

describe('the rule is actually installed', () => {
  /**
   * A source assertion, for the reason `restoreRefreshesCapabilities.test.ts`
   * records: this is a wiring fact between two modules, and the suite runs in
   * `node` with no DOM, so nothing else would notice the subscription going
   * missing. The rule above can be perfectly green while the palette is never
   * told — which is precisely the shape of the defect being fixed.
   */
  const context = readFileSync(
    fileURLToPath(new URL('./WorkbenchContext.tsx', import.meta.url)),
    'utf8',
  );

  it('subscribes for the whole session, beside the draft-key listener', () => {
    expect(context).toContain('followOpenPackage()');
    expect(context).toMatch(/import \{[^}]*followOpenPackage[^}]*\} from '\.\/capabilityRefresh'/s);
  });
});
