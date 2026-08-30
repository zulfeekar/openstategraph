import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * A host application mounts this product at a path of its own choosing, and
 * the built bundle has to survive that.
 *
 * Two facts make it survivable, and neither is visible from any single
 * module, which is why they are pinned here rather than beside one of them:
 *
 * - **Every asset URL the build emits is relative.** A root-absolute
 *   `/assets/index-*.js` is a request to the *host's* origin root, where the
 *   host answers its own 404 — the page loads and nothing in it does, which
 *   is the failure shape `runtimeBaseUrl.ts` already names for the API.
 * - **They are resolved against `<base href>`, not against the current URL.**
 *   Relative alone is not enough: this is a single-page app, and `?w=` deep
 *   links and `/w/<slug>` both reach `index.html` at a depth the assets do
 *   not share. The server injects the tag; the build must not compete with it
 *   by emitting absolute paths.
 *
 * Read from the files rather than from the config object, because what ships
 * is the emitted HTML.
 */
describe('the built bundle under a host mount', () => {
  const root = resolve(import.meta.dirname, '..');

  it('declares a relative base so every emitted asset URL is relative', () => {
    const config = readFileSync(resolve(root, 'vite.config.ts'), 'utf8');
    expect(config).toMatch(/base:\s*'\.\/'/);
  });

  it('names no root-absolute asset in the source document either', () => {
    // Vite rewrites what it recognises; a hand-written `/favicon.svg` in
    // `index.html` is copied through untouched and would 404 under a mount.
    const html = readFileSync(resolve(root, 'index.html'), 'utf8');
    const absolute = [...html.matchAll(/(?:href|src)="(\/[^/][^"]*)"/g)].map((m) => m[1]);
    expect(absolute).toEqual([]);
  });
});
