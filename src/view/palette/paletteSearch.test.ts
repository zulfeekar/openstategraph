import { describe, expect, it } from 'vitest';
import { CATEGORY } from '@nodes/vocabulary';
import { assembliesFor, sectionSurvivesSearch } from './paletteSearch';

/**
 * The palette's search, and the entry it could not find.
 *
 * The owner asked for "the revision loop like one draggable component". It
 * already was one — `revisionLoopAssembly` drops an agent, a grader and the
 * `revise → feedback` edge in a single undoable step, verified by dragging it
 * onto the canvas. What was broken is that **searching for it returned
 * nothing**: measured live, `loop`, `revise` and `retry` each produced an
 * empty palette, while its keywords contain all three.
 *
 * Sections were filtered on matching *node types*, twice. No node type matches
 * "loop", so the whole `compose` section was discarded before anything asked
 * its assemblies. The one palette item that is genuinely hard to find by
 * browsing — 26th of 28, below the fold at a narrow width — was the one item
 * search could not reach (canvas-feels-right ticket 03).
 */
const section = (id: string) => ({ category: { id }, nodes: [] as never[] });

describe('finding an assembly by search', () => {
  it('matches the words a person actually types for a revision loop', () => {
    for (const query of ['loop', 'revise', 'revision', 'retry', 'feedback', 'critic']) {
      expect(assembliesFor(CATEGORY.compose, query), query).toHaveLength(1);
    }
  });

  it('matches the label as well as the keywords', () => {
    expect(assembliesFor(CATEGORY.compose, 'Revision')).toHaveLength(1);
  });

  it('does not match an unrelated word', () => {
    expect(assembliesFor(CATEGORY.compose, 'sqlite')).toHaveLength(0);
  });

  it('only offers an assembly to its own section', () => {
    expect(assembliesFor(CATEGORY.tools, 'loop')).toHaveLength(0);
  });
});

describe('whether a section survives the search', () => {
  it('keeps a section whose only match is an assembly', () => {
    // The regression. With no node types matching "loop", this returned false
    // and the Revision loop became unreachable.
    expect(sectionSurvivesSearch(section(CATEGORY.compose), 'loop')).toBe(true);
  });

  it('drops a section that matches nothing at all', () => {
    expect(sectionSurvivesSearch(section(CATEGORY.tools), 'loop')).toBe(false);
  });

  it('keeps every section when nothing is being searched for', () => {
    expect(sectionSurvivesSearch(section(CATEGORY.tools), '')).toBe(true);
    expect(sectionSurvivesSearch(section(CATEGORY.tools), '   ')).toBe(true);
  });
});
