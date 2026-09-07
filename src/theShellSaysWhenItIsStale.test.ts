import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The shell has to be able to report its own failure to load.
 *
 * `osg-agent-experience/77`: a release on a fixed port, a browser that kept
 * the previous `index.html`, and a `<script src="assets/index-<oldhash>.js">`
 * the new server does not have. React never runs, so nothing in the
 * application can say anything — `#root` stays empty and the page is white.
 * The 404 exists only in a console.
 *
 * `Cache-Control: no-cache` on the document (see
 * `backend/tests/test_a_cached_shell_cannot_outlive_its_assets.py`) is the
 * fix. This is the belt to that pair of braces: a browser that ignores the
 * header, an intermediary that strips it, or a service worker somebody adds
 * later all end in the same place, and one sentence beats white.
 *
 * **It reads `dist/index.html`, and that is the whole reason this file is a
 * test rather than a review comment.** The ticket asked for an `onerror`
 * attribute on the entry script; written that way it worked in the checkout
 * and shipped nothing, because Vite deletes the source tag and emits its own
 * `<script type="module" crossorigin src="./assets/index-<hash>.js">`. A pin
 * reading only the repository's `index.html` would have been green over a
 * built shell with no fallback in it at all — the failure being pinned
 * against, one layer up.
 *
 * `dist/` is gitignored, so the built half is asserted where a build exists
 * and skipped where one does not; the source half always runs.
 */
describe('the shell when its own bundle will not load', () => {
  const root = resolve(import.meta.dirname, '..');
  const shells = ['index.html', 'dist/index.html']
    .map((relative) => resolve(root, relative))
    .filter((path) => existsSync(path));

  it.each(shells)('%s listens for a subresource that will not load', (path) => {
    const html = readFileSync(path, 'utf8');

    expect(html).toMatch(/addEventListener\(\s*'error'/);
    // Capture phase: `error` from a failed script or stylesheet does not
    // bubble, so a listener registered without `true` never runs.
    expect(html).toMatch(/'error',[\s\S]*?\btrue\s*\)/);
  });

  it.each(shells)('%s carries the sentence and hides it until then', (path) => {
    const html = readFileSync(path, 'utf8');

    expect(html).toMatch(/id="stale-shell"/);
    expect(html).toMatch(/older build/);
    // `hidden`, so a shell whose bundle loads normally shows nothing.
    expect(html).toMatch(/id="stale-shell"[\s\S]*?\shidden/);
  });

  it('needs nothing else to load in order to say it', () => {
    const html = readFileSync(resolve(root, 'index.html'), 'utf8');
    const notice = html.match(/<div\s+id="stale-shell"[\s\S]*?<\/div>/)?.[0] ?? '';

    // No class hook into a stylesheet, no imported font, no icon: every
    // dependency is another asset that can fail the same way.
    expect(notice).not.toMatch(/class=/);
    expect(notice).toMatch(/style="/);
  });
});
