import { describe, expect, it } from 'vitest';
import type { IPortDescriptor, PortSide } from '@core/model/contracts/ports';
import {
  LINK_CONNECTOR,
  LINK_ROUTER,
  branchRank,
  edgeLabelText,
  labelPlacement,
  linkRouter,
} from './edgeDecoration';

const port = (over: Partial<IPortDescriptor> = {}): IPortDescriptor => ({
  id: 'result',
  direction: 'out',
  type: 'result',
  label: 'result',
  ...over,
});

/**
 * `args` is optional on JointJS's router JSON, and `?? {}` there erased the
 * argument type along with it — every assertion below then read a property of
 * `{}`. `linkRouter` always fills `args` in, so the honest reading is to say
 * so once and keep the router's own argument type for the assertions.
 */
const routerArgs = (source: PortSide | undefined, target: PortSide | undefined) => {
  const { args } = linkRouter(source, target);
  if (!args) throw new Error('linkRouter always supplies args');
  return args;
};

describe('edgeLabelText', () => {
  it('labels a conditional branch with the port name', () => {
    expect(edgeLabelText(null, port({ id: 'pass', label: 'pass', branch: true }))).toBe('pass');
  });

  it('leaves a typed edge unlabelled — colour and dash already say what it is', () => {
    expect(edgeLabelText(null, port({ id: 'tool', label: 'tool', type: 'tool' }))).toBeNull();
    expect(edgeLabelText(null, port())).toBeNull();
  });

  it('prefers a label the author set by hand over the derived one', () => {
    expect(edgeLabelText('retry', port({ label: 'pass', branch: true }))).toBe('retry');
    expect(edgeLabelText('note', port())).toBe('note');
  });

  it('treats an empty author label as no label rather than an empty halo', () => {
    expect(edgeLabelText('', port())).toBeNull();
    expect(edgeLabelText('   ', port())).toBeNull();
  });

  it('survives an edge whose source port has gone (a mid-edit reconcile)', () => {
    expect(edgeLabelText(null, undefined)).toBeNull();
    expect(edgeLabelText('kept', undefined)).toBe('kept');
  });
});

describe('branchRank', () => {
  const ports = [
    port({ id: 'question', direction: 'in', label: 'question' }),
    port({ id: 'branch:a', label: 'alpha', branch: true }),
    port({ id: 'branch:b', label: 'beta', branch: true }),
    port({ id: 'branch:c', label: 'gamma', branch: true }),
  ];

  it('ranks by the node’s own port order, not by when an edge was drawn', () => {
    expect(branchRank(ports, 'branch:a')).toBe(0);
    expect(branchRank(ports, 'branch:b')).toBe(1);
    expect(branchRank(ports, 'branch:c')).toBe(2);
  });

  it('ignores inputs and unlabelled outputs when counting', () => {
    expect(branchRank(ports, 'question')).toBe(0);
    expect(branchRank(ports, 'nope')).toBe(0);
  });
});

describe('labelPlacement', () => {
  it('measures from the source end, so a branch name sits where it leaves', () => {
    const first = labelPlacement('horizontal', 0);
    expect(first.distance).toBeGreaterThan(1);
  });

  it('staggers siblings so five branch labels do not pile on one another', () => {
    const flows = ['horizontal', 'vertical'] as const;
    for (const flow of flows) {
      const distances: number[] = [0, 1, 2, 3, 4].map(
        (rank) => labelPlacement(flow, rank).distance,
      );
      const ascending: number[] = [...distances].sort((a, b) => a - b);
      expect(distances).toEqual(ascending);
      expect(new Set(distances).size).toBe(distances.length);
    }
  });

  it('spaces vertical labels further apart than horizontal ones', () => {
    // A layout tuned for horizontal cannot be reused rotated: vertical rows
    // sit closer together than horizontal columns do, so the same stagger
    // would collide.
    const horizontal =
      labelPlacement('horizontal', 1).distance - labelPlacement('horizontal', 0).distance;
    const vertical =
      labelPlacement('vertical', 1).distance - labelPlacement('vertical', 0).distance;
    expect(vertical).toBeGreaterThan(horizontal);
  });

  it('alternates the side siblings sit on, so two near-parallel lines still separate', () => {
    for (const flow of ['horizontal', 'vertical'] as const) {
      const offsets = [0, 1, 2, 3].map((rank) => labelPlacement(flow, rank).offset as number);
      expect(Math.sign(offsets[0]!)).toBe(Math.sign(offsets[2]!));
      expect(Math.sign(offsets[1]!)).toBe(Math.sign(offsets[3]!));
      expect(Math.sign(offsets[0]!)).not.toBe(Math.sign(offsets[1]!));
    }
  });

  it('never rotates the text — a vertical link must not produce sideways words', () => {
    for (const flow of ['horizontal', 'vertical'] as const) {
      expect(labelPlacement(flow, 0).args?.keepGradient).toBeFalsy();
      expect(labelPlacement(flow, 0).angle ?? 0).toBe(0);
    }
  });
});

describe('LINK_CONNECTOR', () => {
  it('draws the route verbatim and only eases the corner', () => {
    // The owner asked for a rigid line. `rounded` reproduces the router's
    // segments; anything that re-curves them (`smooth`, `curve`) would put the
    // spline back and undo the whole point.
    expect(LINK_CONNECTOR.name).toBe('rounded');
    expect(LINK_CONNECTOR.args?.radius).toBeGreaterThan(0);
  });
});

describe('linkRouter', () => {
  it('is the obstacle-avoiding router the free package actually ships', () => {
    // `docs/decisions/edge-legibility.md` claimed this was a paid feature and
    // wrote off a real defect on the strength of it. It is `manhattan`, it is
    // free, and this test is here so the claim cannot come back.
    expect(linkRouter('right', 'left').name).toBe('manhattan');
  });

  it('sends a run out of the side its port sits on, in either reading', () => {
    // Horizontal: out of the right edge, into the left edge of the next card.
    expect(linkRouter('right', 'left').args).toMatchObject({
      startDirections: ['right'],
      endDirections: ['left'],
    });
    // Vertical: the same two ports have rotated, and so must the directions —
    // this is the pair that used to leave a bottom port sideways.
    expect(linkRouter('bottom', 'top').args).toMatchObject({
      startDirections: ['bottom'],
      endDirections: ['top'],
    });
  });

  it('offers exactly one direction per end, never a menu', () => {
    // A list would let the pathfinder leave a dot backwards to save a few
    // pixels of path length, which is the doubling-back the pinned tangents
    // were introduced to stop.
    const args = routerArgs('right', 'left');
    expect(args.startDirections).toHaveLength(1);
    expect(args.endDirections).toHaveLength(1);
  });

  it('leaves an end unpinned when the port is unknown, rather than guessing', () => {
    const args = routerArgs(undefined, 'top');
    expect('startDirections' in args).toBe(false);
    expect(args).toMatchObject({ endDirections: ['top'] });
  });

  it('forbids the 45° step, so no route can come out diagonal', () => {
    // The pathfinder defaults to 45, which is how `metro` earns its diagonals.
    expect(linkRouter('right', 'left').args?.maxAllowedDirectionChange).toBe(90);
  });

  it('carries an obstacle test only when one is supplied', () => {
    expect(linkRouter('right', 'left').args?.isPointObstacle).toBeUndefined();
    const test = (): boolean => false;
    expect(linkRouter('right', 'left', test).args?.isPointObstacle).toBe(test);
  });
});

describe('LINK_ROUTER', () => {
  it('is orthogonal from the first frame of a drag, before either port is known', () => {
    expect(LINK_ROUTER.name).toBe('manhattan');
    expect(LINK_ROUTER.args?.startDirections).toBeUndefined();
    expect(LINK_ROUTER.args?.endDirections).toBeUndefined();
  });
});
