import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  CENSUS_GROUPS,
  type ICompositionTerm,
  countsAsContent,
  termFor,
} from './compositionVocabulary';

/**
 * The mechanism, with no node type in sight.
 *
 * `compositionSummary` held a `VOCABULARY` table hardcoding
 * `orchestrate.supervisor`, `agent.`, `route.grader` and eight more — inside
 * `core/`, which CLAUDE.md's open/closed rule forbids in as many words: *"a
 * new capability must not require touching `core/`"* (reviews-2026-08-14
 * ticket 13).
 *
 * Splitting it took three decisions, and each is a test below.
 *
 * **Order is declared, not emergent.** The table's own comment said *"Order
 * here is the order on the card: the actors first, then what closes the loop,
 * then what they hold."* A registry ordered by insertion would make the card's
 * reading order depend on module import order — wrong intermittently instead
 * of wrong visibly. So a term names a **group**, `core/` owns the group order,
 * and registration order decides only within a group. That is the same shape
 * as the middleware slot table, for the same reason CLAUDE.md gives: never
 * expose a raw ordering number, because it lets someone express an invalid
 * order silently.
 *
 * **A type nobody registered a word for is counted, not skipped.** The old
 * table skipped it, so a card reading "1 agent" for a child holding one agent
 * and three unregistered nodes was a lie of omission — the same shape as every
 * other defect this map has been fixing. It falls back to the family segment
 * of the type, which is also what removes the load-order hazard the ticket
 * feared: an empty vocabulary degrades to "1 agent · 1 route · 3 tool" rather
 * than to nothing.
 *
 * **Not-counted is declared, and says which kind.** Entry and exit are the
 * mount's *own* ports, drawn on the parent canvas, so counting them inside the
 * box describes the same wire twice. Annotations are not machinery at all.
 * Both are excluded and the two reasons are different, so they are two groups.
 */
const term = (over: Partial<ICompositionTerm> & { id: string }): ICompositionTerm => ({
  group: 'held',
  one: 'thing',
  many: 'things',
  ...over,
});

describe('resolving a node type to its word', () => {
  it('prefers an exact type over its family', () => {
    const vocabulary = [
      term({ id: 'orchestrate.', one: 'orchestrator', many: 'orchestrators' }),
      term({ id: 'orchestrate.worker', one: 'worker', many: 'workers' }),
    ];

    expect(termFor('orchestrate.worker', vocabulary).one).toBe('worker');
    expect(termFor('orchestrate.supervisor', vocabulary).one).toBe('orchestrator');
  });

  it('does not depend on the order the two were declared in', () => {
    // The old table was a `find` over an ordered list, so which entry won was
    // a property of where somebody had put it.
    const exact = term({ id: 'agent.deep', one: 'deep agent', many: 'deep agents' });
    const family = term({ id: 'agent.', one: 'agent', many: 'agents' });

    expect(termFor('agent.deep', [exact, family]).one).toBe('deep agent');
    expect(termFor('agent.deep', [family, exact]).one).toBe('deep agent');
  });

  it('falls back to the family of a type nothing registered', () => {
    const resolved = termFor('analytics.chart', []);

    expect(resolved.one).toBe('analytics');
    expect(countsAsContent(resolved)).toBe(true);
  });

  it('falls back to the whole id when a type has no family', () => {
    expect(termFor('mystery', []).one).toBe('mystery');
  });

  it('never returns nothing, so a census cannot silently under-count', () => {
    for (const type of ['', 'a.b', 'weird..thing']) {
      expect(termFor(type, [])).toBeTruthy();
    }
  });
});

describe('what the card counts', () => {
  it('counts the actors, the control and what they hold', () => {
    for (const group of ['actor', 'control', 'held'] as const) {
      expect(countsAsContent(term({ id: 'x.', group }))).toBe(true);
    }
  });

  it('excludes the mount’s own ports and things that are not machinery', () => {
    expect(countsAsContent(term({ id: 'input.', group: 'boundary' }))).toBe(false);
    expect(countsAsContent(term({ id: 'annotate.', group: 'ignored' }))).toBe(false);
  });

  it('reads in a declared order that puts the actors first', () => {
    // The property the whole split exists to protect.
    expect(CENSUS_GROUPS.indexOf('actor')).toBeLessThan(CENSUS_GROUPS.indexOf('control'));
    expect(CENSUS_GROUPS.indexOf('control')).toBeLessThan(CENSUS_GROUPS.indexOf('held'));
  });
});

/**
 * The guard, and the actual point of the ticket.
 *
 * Splitting the table once is worth little if the next node family that needs
 * a word gets one added back here, which is the cheapest possible fix at the
 * moment somebody is looking at a card missing a count. The rule is
 * CLAUDE.md's, not this file's: *"a new capability must not require touching
 * `core/`."*
 */
describe('no node type is named in core', () => {
  const read = (name: string): string =>
    readFileSync(fileURLToPath(new URL(`./${name}`, import.meta.url)), 'utf8');

  /**
   * Node type ids are `<family>.<name>`. Comments are stripped first, because
   * explaining *why* a type id no longer appears here necessarily mentions
   * one — a guard that fires on its own reasoning is a guard someone deletes.
   */
  const codeOf = (source: string): string =>
    source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*/g, '');

  it.each(['compositionSummary.ts', 'compositionVocabulary.ts'])('%s names none', (file) => {
    const quoted = [...codeOf(read(file)).matchAll(/'([a-z]+)\.([a-z][a-z-]*)'/g)].map(
      (match) => match[0],
    );

    expect(quoted, 'register the word in src/nodes/vocabulary.ts instead').toEqual([]);
  });
});
