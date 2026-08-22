import { describe, expect, it } from 'vitest';
import {
  RESERVED_RUN_CONTEXT_KEYS,
  RUN_CONTEXT_SETTING,
  RUN_CONTEXT_TYPES,
  runContextProblems,
} from '@core/model/contracts/workflow';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * `settings.context` — a workflow declares what its runs carry.
 *
 * `organisms-first-class/67`, step 1 of `docs/decisions/runtime-context.md`.
 * Nothing consumes the declaration yet: no schema is minted, no value is
 * supplied and nothing reads one. So the assertions here are all about a
 * document — that a declaration survives the editor's own round trip, that a
 * document without one is untouched by the feature existing, and that a
 * mistake is named with the key that made it.
 */
const THREE_FIELDS = [
  { key: 'tenant', type: 'string', label: 'Tenant', required: true },
  { key: 'caseId', type: 'string', label: 'Case id' },
  { key: 'maxRefunds', type: 'number', label: 'Refund ceiling', default: 3 },
];

describe('run context declaration', () => {
  it('has three types and no more', () => {
    expect(RUN_CONTEXT_TYPES).toEqual(['string', 'number', 'boolean']);
  });

  it('round-trips a declaration through export and import, in order', () => {
    const workbench = makeWorkbench();
    workbench.controller.document.setSetting(RUN_CONTEXT_SETTING, THREE_FIELDS);

    const reloaded = makeWorkbench();
    const outcome = reloaded.controller.document.importJSON(
      workbench.controller.document.exportJSON(),
    );

    expect(outcome.ok).toBe(true);
    expect(reloaded.model.settings[RUN_CONTEXT_SETTING]).toEqual(THREE_FIELDS);
  });

  it('leaves a document that declares none byte-identical', () => {
    // The inverse that matters most: an existing document must not gain a key,
    // and must not lose its bytes, because a feature it does not use shipped.
    const workbench = makeWorkbench();
    workbench.model.setSettings({ model: 'ollama:gpt-oss:120b-cloud' });
    const before = workbench.controller.document.exportJSON();

    const reloaded = makeWorkbench();
    reloaded.controller.document.importJSON(before);

    expect(reloaded.controller.document.exportJSON()).toBe(before);
    expect(reloaded.model.settings).not.toHaveProperty(RUN_CONTEXT_SETTING);
  });

  it('preserves an empty list rather than helpfully dropping it', () => {
    const workbench = makeWorkbench();
    workbench.controller.document.setSetting(RUN_CONTEXT_SETTING, []);
    const parsed = JSON.parse(workbench.controller.document.exportJSON()) as {
      settings: Record<string, unknown>;
    };
    expect(parsed.settings[RUN_CONTEXT_SETTING]).toEqual([]);
    // Preserved in the file, and identical in meaning to absence: nothing is
    // declared either way, so neither is a problem.
    expect(runContextProblems({ [RUN_CONTEXT_SETTING]: [] })).toEqual([]);
    expect(runContextProblems({})).toEqual([]);
    expect(runContextProblems(undefined)).toEqual([]);
  });

  it('accepts a well-formed declaration silently', () => {
    expect(runContextProblems({ [RUN_CONTEXT_SETTING]: THREE_FIELDS })).toEqual([]);
  });

  it('names the key when the type is not one of the three', () => {
    const [problem] = runContextProblems({
      [RUN_CONTEXT_SETTING]: [{ key: 'tenant', type: 'object' }],
    });
    expect(problem).toContain("'tenant'");
  });

  it('names the key that was declared twice', () => {
    expect(
      runContextProblems({
        [RUN_CONTEXT_SETTING]: [
          { key: 'tenant', type: 'string' },
          { key: 'tenant', type: 'number' },
        ],
      }),
    ).toEqual([
      "Run context declares 'tenant' more than once — each key may appear only once.",
    ]);
  });

  it('refuses a non-finite default', () => {
    const [problem] = runContextProblems({
      [RUN_CONTEXT_SETTING]: [{ key: 'maxRefunds', type: 'number', default: Infinity }],
    });
    expect(problem).toContain('finite');
  });

  it('refuses a default of the wrong declared type', () => {
    const [problem] = runContextProblems({
      [RUN_CONTEXT_SETTING]: [{ key: 'maxRefunds', type: 'number', default: 'three' }],
    });
    expect(problem).toContain("'maxRefunds'");
  });

  it('refuses a mapping, because order is the rendering contract', () => {
    const [problem] = runContextProblems({ [RUN_CONTEXT_SETTING]: { tenant: 'string' } });
    expect(problem).toContain('list');
  });

  for (const key of [
    'thread_id',
    'threadId',
    'THREAD_ID',
    'Thread-Id',
    'session_id',
    'sessionId',
    'user_email',
    'userEmail',
    'workflow_slug',
    'workflowSlug',
    'WORKFLOW-SLUG',
  ]) {
    it(`refuses the reserved key spelled ${key}`, () => {
      const [problem] = runContextProblems({
        [RUN_CONTEXT_SETTING]: [{ key, type: 'string' }],
      });
      expect(problem).toContain('reserved');
      expect(problem).toContain(`'${key}'`);
    });
  }

  it('leaves a key that merely resembles a reserved one alone', () => {
    for (const key of ['threading', 'user_email_address', 'slug', 'thread']) {
      expect(runContextProblems({ [RUN_CONTEXT_SETTING]: [{ key, type: 'string' }] })).toEqual([]);
    }
  });

  it('lists the four identity keys and nothing else', () => {
    expect([...RESERVED_RUN_CONTEXT_KEYS].sort()).toEqual([
      'session_id',
      'thread_id',
      'user_email',
      'workflow_slug',
    ]);
  });
});
