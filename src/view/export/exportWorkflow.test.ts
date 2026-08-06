import { describe, expect, it } from 'vitest';
import { slugify } from './exportWorkflow';

/**
 * `slugify` is the only DOM-free logic in this file — everything else
 * (`exportSVG`/`exportPNG`/`download`/`importJSON`) touches `document`,
 * `canvas`, or a live `PaperController`'s real SVG, and this project's
 * Vitest runs in a `node` environment by design (core stays framework-free;
 * see `vite.config.ts`). Those paths are verified live in a browser instead,
 * per this project's own testing norm for DOM-dependent code.
 */
describe('slugify', () => {
  it('lowercases and hyphenates', () => {
    expect(slugify('My Workflow')).toBe('my-workflow');
  });

  it('collapses non-alphanumeric runs into one hyphen', () => {
    expect(slugify('Chinook: NL -> SQL!!')).toBe('chinook-nl-sql');
  });

  it('strips leading and trailing hyphens', () => {
    expect(slugify('--already--slugged--')).toBe('already-slugged');
  });

  it('falls back to "workflow" for a name with no alphanumeric characters', () => {
    expect(slugify('!!!')).toBe('workflow');
  });

  it('falls back to "workflow" for an empty name', () => {
    expect(slugify('')).toBe('workflow');
  });
});
