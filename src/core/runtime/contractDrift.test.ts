import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The hand-written client, pinned to the published contract.
 *
 * CLAUDE.md's DRY rule names this file specifically: Pydantic is the single
 * source of truth for the run/stream seam, `docs/openapi.json` is its
 * generated publication, and `RuntimeClient.ts` is *"a hand-written client, to
 * be pinned to the published contract by a drift test rather than by
 * codegen"* — and then: **"A new hand-mirror without that pin is what this
 * rule forbids."**
 *
 * The pin did not exist. `test_openapi_contract.py` binds the JSON to the
 * FastAPI app; nothing bound the TypeScript to either, so a dozen mirrored
 * types drifted on trust (reviews-2026-08-14 ticket 08).
 *
 * **Deliberately not codegen.** `docs/decisions/typescript-runtime-types.md`
 * rejected a generator and that is not being re-litigated. This asserts the
 * two agree on the things a drift would actually break: the endpoints the
 * client calls, and the field names it sends.
 */
const REPO = new URL('../../../', import.meta.url);
const openapi = JSON.parse(readFileSync(fileURLToPath(new URL('docs/openapi.json', REPO)), 'utf8'));
/**
 * The client, plus its collaborators — the pin is on the *seam*, not on one
 * file. `McpRegistryClient` was split out of `RuntimeClient` for the public
 * surface ceiling (mcp-connect ticket 03), and a pin that watched only the
 * file the routes used to live in would have gone quiet at exactly the moment
 * four new endpoints appeared.
 */
const client = ['RuntimeClient.ts', 'McpRegistryClient.ts']
  .map((name) => readFileSync(fileURLToPath(new URL(`src/core/runtime/${name}`, REPO)), 'utf8'))
  .join('\n');

/** Every path the client builds, as a template with `{}` for interpolations. */
function pathsCalledByTheClient(): string[] {
  const found = new Set<string>();
  for (const match of client.matchAll(/\$\{this\.baseUrl\}(\/api\/[^`?]*)/g)) {
    const raw = match[1] ?? '';
    const withHoles = raw.replace(/\$\{[^}]*\}/g, '{}');
    // A hole that does not follow a `/` is a query suffix, not a path
    // segment: `/api/threads${suffix}` is still `/api/threads`. Without this
    // the pin reports its own crudeness as drift.
    found.add(withHoles.replace(/([^/])\{\}/g, '$1').replace(/\/$/, ''));
  }
  return [...found];
}

/** The same shape for a documented path: `/api/workflows/{slug}` → `/api/workflows/{}`. */
const normalise = (path: string): string => path.replace(/\{[^}]*\}/g, '{}');

describe('the client and the published contract', () => {
  it('calls only endpoints the contract documents', () => {
    const documented = new Set(Object.keys(openapi.paths).map(normalise));
    const undocumented = pathsCalledByTheClient().filter((path) => !documented.has(path));

    // A path the contract does not describe is either a typo or an endpoint
    // somebody forgot to regenerate — both are the drift this pins.
    expect(undocumented, `regenerate docs/openapi.json, or fix the URL`).toEqual([]);
  });

  it('finds the run and stream doors it depends on', () => {
    // A sanity check on the matcher itself: if the regex above silently
    // matched nothing, the test above would pass vacuously — which is the
    // defect class ticket 09 is about.
    const called = pathsCalledByTheClient();

    expect(called).toContain('/api/runs');
    expect(called).toContain('/api/runs/stream');
    expect(called.length).toBeGreaterThan(5);
  });

  it('sends run fields the contract declares', () => {
    // The keys `runBody` writes must be ones `RunRequest` accepts, or the
    // server ignores them and the editor loses a feature silently — which is
    // exactly how `workflow_slug` and `audience` could have been dropped.
    const declared = new Set(Object.keys(openapi.components.schemas.RunRequest.properties));

    for (const field of [
      'workflow',
      'question',
      'model',
      'recursion_limit',
      'workflow_slug',
      'credentials',
      'audience',
      'thread_id',
    ]) {
      expect(declared, `RunRequest is missing ${field}`).toContain(field);
      expect(client, `RuntimeClient never sends ${field}`).toContain(field);
    }
  });
});
