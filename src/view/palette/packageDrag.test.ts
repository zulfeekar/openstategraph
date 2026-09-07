import { describe, expect, it } from 'vitest';
import { SUBGRAPH_TYPE } from '@nodes/compose/SubgraphNode';
import { decodePackageDrag, encodePackageDrag } from './packageDrag';

describe('the Packages drag payload', () => {
  it('carries the mount type and the slug it is bound to', () => {
    expect(decodePackageDrag(encodePackageDrag('chinook-assistant'))).toEqual({
      typeId: SUBGRAPH_TYPE,
      data: { workflow: 'chinook-assistant' },
    });
  });

  it('is a fresh object per decode, so two drops cannot share one data bag', () => {
    const raw = encodePackageDrag('chinook-assistant');
    const first = decodePackageDrag(raw);
    const second = decodePackageDrag(raw);
    expect(first).not.toBe(second);
    expect(first?.data).not.toBe(second?.data);
  });

  it('refuses anything it did not write, rather than throwing into a drop handler', () => {
    // A drop handler runs on whatever the OS hands it. Every one of these
    // reached `JSON.parse` or a property access in an earlier shape of this.
    expect(decodePackageDrag('')).toBeNull();
    expect(decodePackageDrag('not json')).toBeNull();
    expect(decodePackageDrag('null')).toBeNull();
    expect(decodePackageDrag('[]')).toBeNull();
    expect(decodePackageDrag('{"typeId":"workflow.subgraph"}')).toBeNull();
    expect(decodePackageDrag('{"typeId":7,"data":{"workflow":"a"}}')).toBeNull();
    expect(decodePackageDrag('{"typeId":"workflow.subgraph","data":{"workflow":7}}')).toBeNull();
  });

  it('refuses an empty slug — a mount bound to nothing is the two-step it replaces', () => {
    expect(decodePackageDrag(encodePackageDrag('   '))).toBeNull();
  });

  it('trims the slug, because a padded slug resolves to nothing on the server', () => {
    expect(decodePackageDrag(encodePackageDrag('  chinook-assistant '))?.data.workflow).toBe(
      'chinook-assistant',
    );
  });
});
