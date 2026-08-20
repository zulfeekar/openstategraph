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
 * **Two fixtures, and the split is the point** (production-ready 64). This
 * file used to assert an exact census — `3 agents · 1 router · 1 grader ·
 * 5 tools` — against `workflows/chinook-assistant/workflow.json`, which is
 * the **board**: what `?w=chinook-assistant` opens and what pressing Save
 * rewrites. Adding one node to the flagship in the editor, the most ordinary
 * edit there is, turned two unit tests red, and the words were never what had
 * changed.
 *
 * So the words are pinned against a **hand-written document**, where a count
 * is a fact somebody wrote down on purpose, and the real saved package is
 * still read — for the one thing a fixture genuinely cannot prove, which is
 * that the envelope the editor writes is the envelope the census reads. Every
 * assertion made against it survives adding, removing and reordering nodes,
 * because none of those change what the catalogue calls anything.
 */
const readBoard = (slug: string): unknown =>
  JSON.parse(
    readFileSync(
      fileURLToPath(new URL(`../../workflows/${slug}/workflow.json`, import.meta.url)),
      'utf8',
    ),
  );

/**
 * The shape the flagship has: a router in front of three agents, the tools
 * they hold between them, and the grader that closes the analyst's retry loop.
 *
 * Written out rather than read, so that the counts below are a statement about
 * the *vocabulary* and not about whatever somebody last saved.
 */
const ROUTED_TRIO = {
  version: 1,
  name: 'Routed trio',
  document: {
    version: 3,
    nodes: [
      { id: 'in', type: 'input.text' },
      { id: 'router', type: 'route.classifier' },
      { id: 'agent-sql', type: 'agent.llm' },
      { id: 'agent-web', type: 'agent.llm' },
      { id: 'agent-chat', type: 'agent.llm' },
      { id: 'grader', type: 'route.grader' },
      { id: 'tool-schema', type: 'tool.sql_schema' },
      { id: 'tool-query', type: 'tool.sql_query' },
      { id: 'tool-search', type: 'tool.web_search' },
      { id: 'tool-fetch', type: 'tool.web_fetch' },
      { id: 'tool-knowledge', type: 'tool.knowledge' },
      { id: 'out', type: 'output.text' },
      { id: 'note', type: 'annotate.note' },
    ],
    edges: [{ source: { nodeId: 'grader', portId: 'revise' }, target: { nodeId: 'agent-sql' } }],
  },
};

/** The group each catalogue word belongs to, singular and plural alike. */
const GROUP_OF_LABEL = new Map(
  CENSUS_TERMS.flatMap((term) => [
    [term.one, term.group] as const,
    [term.many, term.group] as const,
  ]),
);

const census = (document: unknown) => summarizeComposition(document, { vocabulary: CENSUS_TERMS });

describe('the shipped census words', () => {
  it('counts a routed trio into the atomic vocabulary', () => {
    const summary = census(ROUTED_TRIO);

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
    const labels = census(ROUTED_TRIO)!.parts.map((part) => part.label);

    expect(labels).toEqual(['agents', 'router', 'grader', 'tools']);
  });

  it('reaches the census through the registry a plugin also writes to', () => {
    const registry = new ModelRegistry();
    registry.censusTerms.registerAll(CENSUS_TERMS);

    const summary = summarizeComposition(ROUTED_TRIO, {
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

describe('the census against a package a user can save over', () => {
  /**
   * What a hand-written fixture cannot prove, and the only thing this reads
   * the board for: the envelope the editor writes — `{ version, name,
   * document }`, with each node's `type` at the top level rather than inside
   * `data` — is the envelope `summarizeComposition` unwraps. A saver that
   * moved either would empty every mount card, and no fixture would notice
   * because a fixture is written to whatever the reader expects.
   *
   * Nothing here is a count. Adding, removing or reordering nodes on the
   * flagship is ordinary use of the product, and ordinary use must not turn a
   * unit test red.
   */
  const board = readBoard('chinook-assistant');

  it('unwraps the saved envelope rather than reading an empty card', () => {
    const summary = census(board);

    expect(summary).not.toBeNull();
    expect(summary!.parts.length).toBeGreaterThan(0);
    for (const part of summary!.parts) {
      expect(part.count).toBeGreaterThan(0);
      expect(part.label).not.toBe('');
    }
  });

  it('reads its groups in order, whatever the document contains', () => {
    // The same reading order as above, as a property rather than a list: a
    // label the catalogue does not claim falls back to its family segment,
    // which `termFor` groups as `held` and the sort puts last.
    const groups = census(board)!.parts.map(
      (part) => GROUP_OF_LABEL.get(part.label) ?? ('held' as const),
    );
    const ranks = groups.map((group) => CENSUS_GROUPS.indexOf(group));

    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
  });
});
