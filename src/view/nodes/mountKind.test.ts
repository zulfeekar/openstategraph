import { describe, expect, it } from 'vitest';
import { MOUNT_BADGE, MOUNT_KINDS, mountKindOf } from './mountKind';

describe('mountKindOf', () => {
  it('names the two mount types by kind', () => {
    expect(mountKindOf('team.workflow')).toBe('team');
    expect(mountKindOf('workflow.subgraph')).toBe('subgraph');
  });

  it('is null for an atom, so only mounts are badged', () => {
    expect(mountKindOf('agent.llm')).toBeNull();
    expect(mountKindOf('route.grader')).toBeNull();
    expect(mountKindOf('tool.chinook-query')).toBeNull();
    expect(mountKindOf('')).toBeNull();
  });

  it('covers exactly the composition-bodied types', () => {
    expect(Object.keys(MOUNT_KINDS).sort()).toEqual(['team.workflow', 'workflow.subgraph']);
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
