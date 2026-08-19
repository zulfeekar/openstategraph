import { describe, expect, it } from 'vitest';

import { moduleBrief } from './moduleBrief';

/**
 * `every-workflow-green` 34 — the door for a gap nothing in the library covers.
 */
describe('moduleBrief', () => {
  const brief = moduleBrief('a tool that can query the GitHub API', 'ops-desk');

  it('names what is missing, in the run\'s own words', () => {
    expect(brief).toContain('a tool that can query the GitHub API');
  });

  it('asks the owner\'s four questions before any code', () => {
    expect(brief).toMatch(/what it does/i);
    expect(brief).toMatch(/which kind of module/i);
    expect(brief).toMatch(/state, context, memory/i);
    expect(brief).toMatch(/close to the business logic/i);
  });

  it('scopes it to this workflow and rules out the shipped package', () => {
    expect(brief).toContain('workflows/ops-desk/tools/');
    expect(brief).toMatch(/never in the installed package/i);
  });

  it('requires the ToolRuntime seam rather than reaching around it', () => {
    // `.scratch/the-atom-has-no-context/` exists because this had no answer.
    expect(brief).toMatch(/through ToolRuntime, not around it/i);
  });

  it('requires the ladder and the declarations the gates read', () => {
    expect(brief).toMatch(/concrete leaf/i);
    expect(brief).toMatch(/declares its card fields and its data keys/i);
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
