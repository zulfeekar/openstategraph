import { describe, expect, it } from 'vitest';
import type { PortRef } from '@core/model/contracts/ports';
import { availableTargets } from './portAffordance';

const ref = (nodeId: string, portId: string): PortRef => ({ nodeId, portId });

describe('availableTargets', () => {
  const ports = [ref('a', 'result'), ref('b', 'prompt'), ref('b', 'tools'), ref('c', 'prompt')];

  it('offers exactly the ports the drop rule would accept', () => {
    // The affordance must never light a target the drop then refuses, so it
    // asks the *same* predicate rather than re-deriving compatibility.
    const legal = new Set(['b/prompt', 'c/prompt']);
    const available = availableTargets(ref('a', 'result'), ports, (_source, target) =>
      legal.has(`${target.nodeId}/${target.portId}`),
    );
    expect(available).toEqual([ref('b', 'prompt'), ref('c', 'prompt')]);
  });

  it('never offers the port the link is leaving', () => {
    // A predicate that says yes to everything is the honest stress case: the
    // origin still must not be dressed as a landing place, because it is
    // already wearing the origin's own marking.
    const available = availableTargets(ref('a', 'result'), ports, () => true);
    expect(available).not.toContainEqual(ref('a', 'result'));
    expect(available).toHaveLength(ports.length - 1);
  });

  it('offers nothing when nothing is legal, rather than falling back to all', () => {
    expect(availableTargets(ref('a', 'result'), ports, () => false)).toEqual([]);
  });

  it('passes the origin as the source, in that order', () => {
    const seen: [string, string][] = [];
    availableTargets(ref('a', 'result'), [ref('b', 'prompt')], (source, target) => {
      seen.push([source.nodeId, target.nodeId]);
      return true;
    });
    expect(seen).toEqual([['a', 'b']]);
  });
});
