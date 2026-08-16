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
 * client calls, the field names it sends, and — since ticket 22 — the SSE
 * event names it handles, which is the one leg of the seam nothing watched.
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

/**
 * The SSE event names the published contract declares, per endpoint.
 *
 * OpenAPI 3.1 cannot describe a *sequence* of frames, so `sse_contract.py`
 * declares the media type and writes the vocabulary into the response
 * description — generated from `RUN_EVENTS`, never retyped. That sentence is
 * therefore the machine-readable half of the frame contract, and this is what
 * makes it a pin rather than a comment.
 */
function eventNamesDeclaredFor(path: string, method: string): string[] {
  const description: string = openapi.paths[path]?.[method]?.responses?.['200']?.description ?? '';
  const names = description.match(/Event names: ([^.]*)\./)?.[1] ?? '';
  return [...names.matchAll(/`([a-z]+)`/g)].map((match) => match[1] as string);
}

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

  /**
   * The half of the seam the endpoint pin above could never see.
   *
   * A new frame name is not a new endpoint and not a new request field, so
   * every assertion in this file used to pass while the backend grew an event
   * the client silently dropped on the floor. `RUN_EVENTS` → `docs/api.md` →
   * `RuntimeClient.ts` is the real contract (`api/sse_contract.py` says so
   * outright), and until now only the first two legs were pinned —
   * `test_api_guide.py` holds the guide to the tuple, and nothing held the
   * TypeScript to either.
   */
  describe('the SSE frame vocabulary', () => {
    it('is declared by the contract at all', () => {
      // Guards the regex, not the client: a matcher that silently found
      // nothing would make every assertion below vacuous.
      expect(eventNamesDeclaredFor('/api/runs/stream', 'post')).toContain('done');
      expect(eventNamesDeclaredFor('/api/runs/stream', 'post').length).toBeGreaterThan(4);
    });

    it('is handled frame for frame by the client', () => {
      const declared = eventNamesDeclaredFor('/api/runs/stream', 'post');
      const unhandled = declared.filter((name) => !client.includes(`eventName === '${name}'`));

      expect(
        unhandled,
        `RuntimeClient never handles ${unhandled.join(', ')} — a frame the backend ` +
          `emits and the client drops. Add the branch, the RunStreamEvent variant ` +
          `and the row in docs/api.md, or remove it from RUN_EVENTS.`,
      ).toEqual([]);
    });

    it('is the same vocabulary on resume', () => {
      // One parser handles both endpoints, which is only safe while both
      // publish the identical vocabulary — the guide promises exactly that.
      expect(eventNamesDeclaredFor('/api/runs/resume', 'post')).toEqual(
        eventNamesDeclaredFor('/api/runs/stream', 'post'),
      );
    });
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
