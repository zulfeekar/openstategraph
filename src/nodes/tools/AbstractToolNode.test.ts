import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ToolNodeModel } from './AbstractToolNode';
import { CHINOOK_NODES } from './ChinookDatabaseNode';

/**
 * The tool family's ladder, with the rung that was missing.
 *
 * CLAUDE.md declares Interface → Abstract → Base → Concrete, and says every
 * layer must earn its place: *"Inheritance must earn itself... Depth is not a
 * virtue."*
 *
 * The tool family had an `AbstractToolNodeModel` that added **nothing** —
 * `export abstract class AbstractToolNodeModel extends AbstractNodeModel {}`,
 * not one member — and beneath it five concrete subclasses that were also
 * empty. Six classes, zero behaviour, and the review called it what it was:
 * pure ceremony (reviews-2026-08-14 ticket 07).
 *
 * The missing rung was **Base** — "a usable default implementation". Five of
 * the seven tool models need no accessors at all, so what they wanted was a
 * concrete class to use, not an abstract one to extend into emptiness. Two
 * genuinely add typed accessors (`RedditSearchNodeModel.subreddit`,
 * `ExecuteSqlNodeModel.maxRows`) and those are the Concretes.
 */
describe('the tool node ladder', () => {
  it('offers a usable base rather than an abstract nobody adds to', () => {
    const definition = CHINOOK_NODES[0]!.definition;

    const model = definition.create({ position: { x: 0, y: 0 } });

    // Constructible and functional: a node type that needs no accessors gets
    // a working model without declaring a class of its own.
    expect(new ToolNodeModel(definition, model as never)).toBeInstanceOf(ToolNodeModel);
  });

  it('has no empty subclass left in the family', () => {
    // The guard, because emptiness returns one convenience at a time: the
    // next tool that needs no accessors is one `class X extends Y {}` away
    // from restoring the ceremony this removed.
    const here = fileURLToPath(new URL('.', import.meta.url));
    const offenders: string[] = [];
    for (const file of readdirSync(here).filter((name) => name.endsWith('.ts'))) {
      const source = readFileSync(`${here}${file}`, 'utf8');
      for (const match of source.matchAll(/class\s+(\w+)\s+extends\s+ToolNodeModel\s*\{\s*\}/g)) {
        offenders.push(`${file}: ${match[1]}`);
      }
    }

    expect(offenders, 'extend ToolNodeModel only to add something; otherwise use it').toEqual([]);
  });

  it('keeps the concretes that actually carry accessors', async () => {
    const { RedditSearchNodeModel } = await import('./RedditSearchNode');
    const { ExecuteSqlNodeModel } = await import('./ChinookDatabaseNode');

    // Substitutable for the base (Liskov), and each adds a reason to exist.
    expect(RedditSearchNodeModel.prototype).toBeInstanceOf(ToolNodeModel);
    expect(ExecuteSqlNodeModel.prototype).toBeInstanceOf(ToolNodeModel);
    expect(Object.getOwnPropertyNames(RedditSearchNodeModel.prototype)).toContain('subreddit');
    expect(Object.getOwnPropertyNames(ExecuteSqlNodeModel.prototype)).toContain('maxRows');
  });
});
