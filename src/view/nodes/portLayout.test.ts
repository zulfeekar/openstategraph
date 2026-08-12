import { describe, expect, it } from 'vitest';
import type { FlowDirection, IPortDescriptor } from '@core/model/contracts/ports';
import { allNodeDefinitions } from '@nodes/portSpecs';
import { defaultsFrom } from '@core/model/contracts/fields';
import { planPortLayout, portPositions, type CardMetrics } from './portLayout';

const WIDTH = 252;
const HEIGHT = 160;

const port = (init: Partial<IPortDescriptor> & Pick<IPortDescriptor, 'id' | 'direction'>) =>
  ({ type: 'text', label: init.id, ...init }) as IPortDescriptor;

/** Rows measured as if the footer had laid out at 24px per row. */
function metricsFor(plan: ReturnType<typeof planPortLayout>): CardMetrics {
  const rowCentres = new Map<string, number>();
  for (const entry of plan.rows) rowCentres.set(entry.port.id, 100 + entry.row * 24);
  return {
    width: WIDTH,
    height: HEIGHT,
    rowCentres,
    pill: plan.pill ? { centre: WIDTH / 2, left: 80 } : null,
    pillOverhang: 8,
  };
}

describe('planPortLayout', () => {
  it('pairs the nth input with the nth output instead of trailing it', () => {
    // The reported defect. CSS sparse auto-placement never moves its cursor
    // backwards, so with `prompt`, `skill`, `feedback` declared before
    // `result`, `result` landed on row 3 and row 1's right cell stayed empty.
    const plan = planPortLayout(
      [
        port({ id: 'prompt', direction: 'in' }),
        port({ id: 'feedback', direction: 'in' }),
        port({ id: 'result', direction: 'out' }),
      ],
      'horizontal',
    );
    const rowOf = (id: string) => plan.rows.find((entry) => entry.port.id === id)?.row;
    expect(rowOf('prompt')).toBe(1);
    expect(rowOf('result')).toBe(1);
    expect(rowOf('feedback')).toBe(2);
    expect(plan.rowCount).toBe(2);
  });

  it('numbers two full columns row for row', () => {
    const plan = planPortLayout(
      [
        port({ id: 'a', direction: 'in' }),
        port({ id: 'b', direction: 'in' }),
        port({ id: 'x', direction: 'out' }),
        port({ id: 'y', direction: 'out' }),
      ],
      'horizontal',
    );
    expect(plan.rows.map((entry) => [entry.port.id, entry.row])).toEqual([
      ['a', 1],
      ['b', 2],
      ['x', 1],
      ['y', 2],
    ]);
  });

  it('sinks an edge-anchored binding below the flank ports in its column', () => {
    // A bus keeps its legend line but its dot is on the bottom edge. Left where
    // it was declared it puts a dotless gap in the middle of the left stack; at
    // the foot of the column the flank dots stay contiguous.
    //
    // The gap is why `skill` stopped being edge-anchored at all: sinking a row
    // repairs the *order* of the left stack but not the missing dot, and a card
    // whose legend lists three inputs must show three dots. Sorting is the
    // right treatment for a bus, which draws its dot on a capsule of its own.
    const plan = planPortLayout(
      [
        port({ id: 'prompt', direction: 'in' }),
        port({ id: 'tools', direction: 'in', side: 'bottom' }),
        port({ id: 'feedback', direction: 'in' }),
      ],
      'horizontal',
    );
    expect(plan.rows.map((entry) => entry.port.id)).toEqual(['prompt', 'feedback', 'tools']);
  });

  it('keeps a pill anchored to its capsule in both flow directions', () => {
    // A pill is drawn at the card's bottom centre by CSS whatever the flow
    // direction, so it must not rotate onto a flank with the rest of its side.
    const tools = port({ id: 'tools', direction: 'in', side: 'bottom', appearance: 'pill' });
    for (const flow of ['horizontal', 'vertical'] as const) {
      expect(planPortLayout([tools], flow).anchors.get('tools')).toBe('pill');
    }
  });

  it('leaves a pill out of the footer legend, since it draws its own label', () => {
    const plan = planPortLayout(
      [port({ id: 'tools', direction: 'in', side: 'bottom', appearance: 'pill' })],
      'horizontal',
    );
    expect(plan.rows).toEqual([]);
    expect(plan.pill?.id).toBe('tools');
  });
});

describe('portPositions', () => {
  it('puts each flank dot on the centre of its own measured row', () => {
    const plan = planPortLayout(
      [port({ id: 'prompt', direction: 'in' }), port({ id: 'result', direction: 'out' })],
      'horizontal',
    );
    const points = portPositions(plan, metricsFor(plan));
    expect(points.get('prompt')).toEqual({ x: 0, y: 124 });
    expect(points.get('result')).toEqual({ x: WIDTH, y: 124 });
  });

  it('spreads unmeasured flank rows down the card rather than stacking them', () => {
    // First paint: the rows are not in the DOM yet. Collapsing them onto the
    // card's middle would put two dots on one pixel.
    const plan = planPortLayout(
      [port({ id: 'a', direction: 'in' }), port({ id: 'b', direction: 'in' })],
      'horizontal',
    );
    const points = portPositions(plan, {
      width: WIDTH,
      height: HEIGHT,
      rowCentres: new Map(),
      pill: null,
      pillOverhang: 0,
    });
    expect(points.get('a')!.y).not.toBe(points.get('b')!.y);
  });

  it('drops the bus dot onto the capsule’s lower rim', () => {
    const plan = planPortLayout(
      [port({ id: 'tools', direction: 'in', side: 'bottom', appearance: 'pill' })],
      'horizontal',
    );
    const points = portPositions(plan, metricsFor(plan));
    expect(points.get('tools')).toEqual({ x: WIDTH / 2, y: HEIGHT + 8 });
  });
});

describe('every registered node type, in both flow directions', () => {
  const flows: readonly FlowDirection[] = ['horizontal', 'vertical'];

  for (const definition of allNodeDefinitions()) {
    for (const flow of flows) {
      const ports = definition.ports(defaultsFrom(definition.fields));
      if (ports.length === 0) continue;

      describe(`${definition.id} (${flow})`, () => {
        const plan = planPortLayout(ports, flow);
        const points = portPositions(plan, metricsFor(plan));

        it('gives every declared port a dot', () => {
          expect([...points.keys()].sort()).toEqual(ports.map((entry) => entry.id).sort());
        });

        it('never stacks two ports on one point', () => {
          const seen = new Set([...points.values()].map((point) => `${point.x},${point.y}`));
          expect(seen.size).toBe(points.size);
        });

        it('keeps every flank dot on the edge it belongs to', () => {
          for (const [id, point] of points) {
            const anchor = plan.anchors.get(id);
            if (anchor === 'left') expect(point.x).toBe(0);
            if (anchor === 'right') expect(point.x).toBe(WIDTH);
            if (anchor === 'top') expect(point.y).toBe(0);
            if (anchor === 'bottom' || anchor === 'pill') {
              expect(point.y).toBeGreaterThanOrEqual(HEIGHT);
            }
          }
        });

        it('lists every row-appearance port in the footer legend, once', () => {
          const expected = ports
            .filter((entry) => (entry.appearance ?? 'row') === 'row')
            .map((entry) => entry.id)
            .sort();
          expect(plan.rows.map((entry) => entry.port.id).sort()).toEqual(expected);
        });

        it('numbers each column from one, with no gap and no collision', () => {
          for (const column of ['in', 'out'] as const) {
            const numbers = plan.rows
              .filter((entry) => entry.column === column)
              .map((entry) => entry.row);
            expect(numbers).toEqual(numbers.map((_, index) => index + 1));
          }
        });
      });
    }
  }
});
