import { describe, expect, it } from 'vitest';
import { validateFields } from './contracts/fields';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';

/**
 * The per-node retry/timeout override — the P1 "per-node retry/timeout UI"
 * gap. `set_node_defaults` (workflow_compiler.py) already gives every node
 * the same graph-wide retry policy; this is the per-node *override* LangGraph's
 * own `add_node(..., retry_policy=..., timeout=...)` supports. Declared once
 * in `defineNode` (CLAUDE.md: a graph-assembly concern, inherited by every
 * executable node type, not re-declared per type) rather than added to each
 * node file individually.
 */
describe('defineNode — execution override fields', () => {
  it('every standard node type gets maxRetries and timeoutSeconds fields', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent);
    const keys = agent.definition.fields.map((f) => f.key);
    expect(keys).toContain('maxRetries');
    expect(keys).toContain('timeoutSeconds');
  });

  it('both default to blank — inherit the workflow default, not a bogus number', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent);
    expect(agent.data['maxRetries']).toBe('');
    expect(agent.data['timeoutSeconds']).toBe('');
  });

  it('a container node (kind "container") does not get the override fields', () => {
    const workbench = makeWorkbench();
    const group = addNode(workbench, TYPE.group);
    const keys = group.definition.fields.map((f) => f.key);
    expect(keys).not.toContain('maxRetries');
    expect(keys).not.toContain('timeoutSeconds');
  });

  it('accepts a positive integer for maxRetries and rejects everything else', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent);
    const schema = agent.definition.fields.find((f) => f.key === 'maxRetries')!;

    expect(validateFields([schema], { maxRetries: '' })).toEqual({});
    expect(validateFields([schema], { maxRetries: '5' })).toEqual({});
    expect(validateFields([schema], { maxRetries: '0' })).toHaveProperty('maxRetries');
    expect(validateFields([schema], { maxRetries: '-1' })).toHaveProperty('maxRetries');
    expect(validateFields([schema], { maxRetries: '1.5' })).toHaveProperty('maxRetries');
    expect(validateFields([schema], { maxRetries: 'abc' })).toHaveProperty('maxRetries');
  });

  it('accepts a positive number for timeoutSeconds and rejects everything else', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent);
    const schema = agent.definition.fields.find((f) => f.key === 'timeoutSeconds')!;

    expect(validateFields([schema], { timeoutSeconds: '' })).toEqual({});
    expect(validateFields([schema], { timeoutSeconds: '30' })).toEqual({});
    expect(validateFields([schema], { timeoutSeconds: '0.5' })).toEqual({});
    expect(validateFields([schema], { timeoutSeconds: '0' })).toHaveProperty('timeoutSeconds');
    expect(validateFields([schema], { timeoutSeconds: '-5' })).toHaveProperty('timeoutSeconds');
    expect(validateFields([schema], { timeoutSeconds: 'abc' })).toHaveProperty('timeoutSeconds');
  });

  it('the override fields are inspector-only, not shown on the compact card', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent);
    const retries = agent.definition.fields.find((f) => f.key === 'maxRetries')!;
    const timeout = agent.definition.fields.find((f) => f.key === 'timeoutSeconds')!;
    expect(retries.onCard).toBe(false);
    expect(timeout.onCard).toBe(false);
  });
});
