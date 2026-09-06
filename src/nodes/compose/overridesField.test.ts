import { describe, expect, it } from 'vitest';
import { OVERRIDES_FIELD } from './overridesField';

const validate = OVERRIDES_FIELD.validate! as (value: string) => string | null;

describe('the per-mount overrides field', () => {
  it('accepts an empty value (no overrides is the normal case)', () => {
    expect(validate('')).toBeNull();
    expect(validate('   ')).toBeNull();
  });

  it('accepts the documented shape', () => {
    expect(validate('{"grader1": {"criteria": "- stricter", "maxAttempts": 3}}')).toBeNull();
  });

  it('rejects malformed JSON with a readable message', () => {
    expect(validate('{not json')).toMatch(/JSON/);
  });

  it('rejects a top-level array or scalar', () => {
    expect(validate('[1,2]')).toMatch(/object/i);
    expect(validate('"just a string"')).toMatch(/object/i);
  });

  it('rejects a node id mapping to a non-object', () => {
    expect(validate('{"grader1": "oops"}')).toMatch(/grader1/);
  });

  it('is an advanced inspector-only field — never card clutter', () => {
    expect(OVERRIDES_FIELD.onCard).toBe(false);
    expect(OVERRIDES_FIELD.advanced).toBe(true);
  });
});
