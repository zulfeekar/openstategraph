import { describe, expect, it } from 'vitest';

import { moduleBrief } from './moduleBrief';

/**
 * `every-workflow-green` 34 — the door for a gap nothing in the library covers.
 */
describe('moduleBrief', () => {
  const brief = moduleBrief('a tool that can query the GitHub API', 'ops-desk');

  it("names what is missing, in the run's own words", () => {
    expect(brief).toContain('a tool that can query the GitHub API');
  });

  it("asks the owner's four questions before any code", () => {
    expect(brief).toMatch(/what it does/i);
    expect(brief).toMatch(/which kind of module/i);
    expect(brief).toMatch(/state, context, memory/i);
    expect(brief).toMatch(/close to the business logic/i);
  });

  it('scopes it to this workflow and rules out the shipped package', () => {
    expect(brief).toContain('ops-desk');
    expect(brief).toMatch(/never in the installed package/i);
  });

  it('does not hardcode the workflows directory', () => {
    // `workflows/` is only the **convention**. The root is resolved per call
    // from five sources — `OPENSTATEGRAPH_WORKFLOWS_ROOT`, `workflows_dir:` in
    // `openstategraph.yaml`, the checkout, then `./workflows` — so a brief
    // naming a literal `workflows/…` path is wrong for anyone who configured
    // one, and wrong in an installed wheel, which is exactly the failure
    // `workflows_root.py` was written to end.
    //
    // The package's own folder is the anchor that holds everywhere: `tools/`
    // sits beside its `workflow.json`, whatever the root is called.
    expect(brief).not.toMatch(/\bworkflows\//);
    expect(brief).toMatch(/beside its workflow\.json/i);
  });

  it('names the seams this installation actually has', () => {
    // This assertion used to read `/through ToolRuntime, not around it/` and
    // was green for a day while `ToolRuntime` existed nowhere in the product —
    // a LangChain construct we do not surface, recorded in
    // `docs/decisions/special-agents-2026-08.md` as "flagged, not decided".
    // A tool here gets its validated `Args` and nothing else.
    //
    // The real gate is `backend/tests/test_a_generated_module_is_checkable.py`,
    // which resolves every symbol a clause names against this installation.
    // Asserting the words here is fine as long as nobody mistakes it for that.
    expect(brief).toMatch(/configure\(data\)/);
    expect(brief).toMatch(/langgraph\.config\.get_config\(\)/);
    expect(brief).toMatch(/get_store\(\)/);
    expect(brief).toMatch(/cannot read graph state/i);
    expect(brief).not.toMatch(/ToolRuntime/);
  });

  it('requires the ladder and the declarations the gates read', () => {
    expect(brief).toMatch(/concrete leaf/i);
    expect(brief).toMatch(/implements _execute/);
    expect(brief).toMatch(/declares its card fields in node_fields/i);
  });

  it('never lets a credential value into the document', () => {
    expect(brief).toMatch(/environment variable, never a value/i);
  });

  it('still reads sensibly with no slug and no gap text', () => {
    const bare = moduleBrief('', null);
    expect(bare).toContain('this workflow');
    expect(bare).toMatch(/a capability this workflow does not have/);
  });
});
