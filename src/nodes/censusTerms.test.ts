import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { ModelRegistry } from '@core/model/ModelRegistry';
import { formatComposition, summarizeComposition } from '@core/runtime/compositionSummary';
import { CENSUS_GROUPS } from '@core/runtime/compositionVocabulary';
import { CENSUS_TERMS } from './vocabulary';

/**
 * The catalogue's own words, against the documents a mount card is handed.
 *
 * These assertions used to live in `src/core/runtime/compositionSummary.test.ts`
 * beside the mechanism, which is part of why the word table looked like it
 * belonged in `core/` — a `core/` test that knows `route.grader` counts as
 * "grader" is a `core/` test that has an opinion about the catalogue
 * (reviews-2026-08-14 ticket 13). The mechanism is tested there with a local
 * vocabulary; the words are tested here, where they are declared.
 *
 * A real saved package, read from disk — a hand-written fixture would drift
 * from the document the card actually receives. `chinook-assistant` is the one
 * visible example: a router in front of three agents, the SQL tools and web
 * tools they hold between them, and the grader that closes the analyst's retry
 * loop. It is what the gateway mounts.
 */
const readWorkflow = (slug: string): unknown =>
  JSON.parse(
    readFileSync(
      fileURLToPath(new URL(`../../workflows/${slug}/workflow.json`, import.meta.url)),
      'utf8',
    ),
  );

const census = (document: unknown) => summarizeComposition(document, { vocabulary: CENSUS_TERMS });

describe('the shipped census words', () => {
  it('counts the real mounted example into the atomic vocabulary', () => {
    const summary = census(readWorkflow('chinook-assistant'));

    expect(summary).not.toBeNull();
    expect(formatComposition(summary!)).toBe(
      '3 agents · 1 router · 1 grader · 5 tools — loops until its grader passes',
    );
  });

  it('reads actors first, then control, then what they hold', () => {
    // The property the group mechanism exists to protect, asserted on the
    // real words rather than on the group table: agents (actor) precede the
    // router and grader (control), which precede the tools (held). Declaring
    // the terms in a different order must not change this line.
    const labels = census(readWorkflow('chinook-assistant'))!.parts.map((part) => part.label);

    expect(labels).toEqual(['agents', 'router', 'grader', 'tools']);
  });

  it('reaches the census through the registry a plugin also writes to', () => {
    const registry = new ModelRegistry();
    registry.censusTerms.registerAll(CENSUS_TERMS);

    const summary = summarizeComposition(readWorkflow('chinook-assistant'), {
      vocabulary: registry.censusTerms.list(),
    });

    expect(formatComposition(summary!)).toContain('3 agents');
  });

  it('is already registered on a workbench, before any card renders', () => {
    // The load-order question the ticket raised, answered where it can be
    // checked rather than reasoned about. `CompositionBody` reads
    // `workbench.registry.censusTerms` during render; if `registerNodeCatalogue`
    // did not run first, every card would quietly fall back to family words —
    // legible, but not what the catalogue says.
    const workbench = new Workbench();

    expect(workbench.registry.censusTerms.list()).toHaveLength(CENSUS_TERMS.length);
  });

  it('gives a family nobody registered a word for a legible one anyway', () => {
    // The open/closed payoff, and the load-order safety net in one: a node
    // family this build has never heard of is counted under its own family
    // name rather than skipped, so the card cannot quietly under-report what
    // a mounted document contains.
    const document = {
      nodes: [
        { id: 'a', type: 'agent.llm' },
        { id: 'c1', type: 'analytics.chart' },
        { id: 'c2', type: 'analytics.table' },
      ],
    };

    expect(formatComposition(census(document)!)).toBe('1 agent · 2 analytics');
  });

  it('declares every group it uses', () => {
    // A typo in a group name would silently sort that term first, because
    // `indexOf` returns -1 for something not in the list.
    for (const term of CENSUS_TERMS) {
      expect(CENSUS_GROUPS, `${term.id} names an unknown group`).toContain(term.group);
    }
  });

  it('registers each term once, so the registry cannot reject the catalogue', () => {
    const ids = CENSUS_TERMS.map((term) => term.id);

    expect(new Set(ids).size).toBe(ids.length);
  });
});
