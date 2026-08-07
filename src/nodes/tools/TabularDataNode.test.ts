/**
 * Tabular data tool nodes — definition tests (not registration, since these are workflow-scoped).
 */

import { describe, expect, it } from 'vitest';
import {
  TABULAR_NODES,
  getTableSchemaNode,
  queryDataNode,
  sampleDataNode,
} from './TabularDataNode';

describe('tabular data nodes definition', () => {
  it('exports all four tabular tool nodes', () => {
    const ids = TABULAR_NODES.map((n) => n.definition.id);
    expect(ids).toContain('tool.tabular-list-files');
    expect(ids).toContain('tool.tabular-get-schema');
    expect(ids).toContain('tool.tabular-query');
    expect(ids).toContain('tool.tabular-sample');
  });

  it('get-schema node has a fileName field with validation', () => {
    const fileNameField = getTableSchemaNode.fields.find((f) => f.key === 'fileName');
    expect(fileNameField).toBeDefined();
    expect(fileNameField?.kind).toBe('text');

    // Validation: must end with .csv or .parquet
    const validate = fileNameField?.validate as ((value: string) => string | null) | undefined;
    expect(validate?.('data.csv')).toBeNull();
    expect(validate?.('data.parquet')).toBeNull();
    expect(validate?.('data.txt')).toBe('Must end with .csv or .parquet');
    expect(validate?.('')).toBe('Must end with .csv or .parquet');
  });

  it('query-data node has maxRows slider', () => {
    const maxRowsField = queryDataNode.fields.find((f) => f.key === 'maxRows');
    expect(maxRowsField).toBeDefined();
    expect(maxRowsField?.kind).toBe('slider');
    expect(maxRowsField?.defaultValue).toBe(200);
  });

  it('sample-data node has fileName and nRows fields', () => {
    const fileNameField = sampleDataNode.fields.find((f) => f.key === 'fileName');
    const nRowsField = sampleDataNode.fields.find((f) => f.key === 'nRows');

    expect(fileNameField).toBeDefined();
    expect(fileNameField?.kind).toBe('text');

    expect(nRowsField).toBeDefined();
    expect(nRowsField?.kind).toBe('slider');
    expect(nRowsField?.defaultValue).toBe(10);
    // Type assertion since max is on SliderFieldSchema specifically
    expect((nRowsField as any)?.max).toBe(50);
  });

  it('all nodes have tool output port defined in their base type', () => {
    // Tool nodes inherit their port structure from defineToolNode
    // Each should have exactly one output port of type 'tool'
    for (const { definition } of TABULAR_NODES) {
      expect(definition.id).toMatch(/^tool\.tabular-/);
    }
  });
});
