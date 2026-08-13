import { describe, expect, it } from 'vitest';
import { MOUNT_BADGE, MOUNT_TYPES, isMountType } from './mountKind';

/**
 * One mount type since schema v3 (production-ready ticket 16).
 *
 * This asserted two ids and a `kind` for each. `team.workflow` compiled
 * through the same builder with no branch and identical ports; what made it
 * look like a second organism was a glyph, a documentation field and a census
 * note the child earns. So the question a card asks is no longer *which* mount
 * this is — only whether it is one.
 */
describe('isMountType', () => {
  it('recognises the mount', () => {
    expect(isMountType('workflow.subgraph')).toBe(true);
  });

  it('does not recognise the id that was collapsed away', () => {
    // A document still carrying it has been migrated by `normalize_document`
    // before any card sees it, so treating it as a mount here would keep a
    // dead id alive in the one place nothing would notice.
    expect(isMountType('team.workflow')).toBe(false);
  });

  it('is false for an atom, so only mounts are badged', () => {
    expect(isMountType('agent.llm')).toBe(false);
    expect(isMountType('route.grader')).toBe(false);
    expect(isMountType('tool.chinook-query')).toBe(false);
    expect(isMountType('')).toBe(false);
  });

  it('covers exactly the composition-bodied types', () => {
    expect([...MOUNT_TYPES].sort()).toEqual(['workflow.subgraph']);
  });

  it('stays a list, because it declares a category and not a count', () => {
    // A registered plugin mount would join it without reopening `NodeCard`,
    // `nodeBodyRegistry` or these tests.
    expect(Array.isArray(MOUNT_TYPES)).toBe(true);
  });
});

describe('MOUNT_BADGE', () => {
  it('states the kind in one word', () => {
    expect(MOUNT_BADGE.label).toBe('graph');
    expect(MOUNT_BADGE.label.split(/\s+/)).toHaveLength(1);
  });

  it('never claims a loop — that claim belongs to the census, which derives it', () => {
    const text = `${MOUNT_BADGE.label} ${MOUNT_BADGE.title}`.toLowerCase();
    expect(text).not.toMatch(/loop|itera|repeat|until/);
  });
});
