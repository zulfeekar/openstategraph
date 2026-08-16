import { readdirSync, readFileSync } from 'node:fs';
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
 *
 * `WorkflowFileClient.ts` joined for the same argument read the other way
 * (framework-packaging ticket 11): it builds thirteen more `/api/` paths — the
 * catalogue, the templates, the examples, the mounts — and was outside the
 * list because the list named the files in front of its author. Every one of
 * them was documented on the day it was added, which is the argument for
 * adding the file now rather than after a fourteenth is not.
 */
const client = ['RuntimeClient.ts', 'McpRegistryClient.ts', 'WorkflowFileClient.ts']
  .map((name) => readFileSync(fileURLToPath(new URL(`src/core/runtime/${name}`, REPO)), 'utf8'))
  .join('\n');

/**
 * Every client of the run stream — **discovered, not listed**.
 *
 * The listed version of this is what let `progress` and `block` ship to the
 * editor and not to the customer (architecture review 2026-08-16, F2). The
 * list above named the two files that were in front of the author;
 * `chat.html` reads the same frames through `fetch` + `getReader()` and was
 * outside the pin, so a fully green suite watched the one page the `progress`
 * frame was built for drop it.
 *
 * So the roll is taken by walking the shipped trees for the two things that
 * make a file a consumer of this stream: it names the endpoint, and it reads
 * the body itself. That is the `port_specs.json` lesson applied to a seam
 * that cannot be generated — a fourth client cannot appear without appearing
 * here, which is the only property that stops this finding recurring.
 */
const CLIENT_ROOTS = ['src', 'backend/openstategraph', 'docs', 'site'];
const SKIPPED_DIRS = new Set(['node_modules', 'dist', '__pycache__', '.git']);

function sourceFilesUnder(dir: string): string[] {
  let entries;
  try {
    entries = readdirSync(fileURLToPath(new URL(dir, REPO)), { withFileTypes: true });
  } catch {
    return [];
  }
  const found: string[] = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      if (!SKIPPED_DIRS.has(entry.name)) found.push(...sourceFilesUnder(`${dir}/${entry.name}`));
    } else if (/\.(ts|tsx|js|html)$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) {
      found.push(`${dir}/${entry.name}`);
    }
  }
  return found;
}

/**
 * A file is a run-stream client when it posts to the stream door **and**
 * reads the frames off the body. Both halves matter: `site/gallery.html`
 * prints `/api/runs/stream` in prose and consumes nothing, and a file that
 * calls `getReader()` on some other response is not this contract's problem.
 */
function streamConsumers(): string[] {
  return CLIENT_ROOTS.flatMap(sourceFilesUnder).filter((path) => {
    const source = readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8');
    return source.includes('/api/runs/stream') && source.includes('getReader(');
  });
}

/**
 * How a consumer spells "I handle this frame".
 *
 * Three spellings, because the three clients are a TypeScript module and two
 * plain-HTML pages: `eventName === 'x'`, `event === "x"`, `name === "x"`. The
 * lookbehind keeps `err.name === "AbortError"` and `d.kind === 'tool'` out —
 * a property access is a different question about a different value.
 */
function framesHandledBy(source: string): Set<string> {
  const found = new Set<string>();
  for (const match of source.matchAll(
    /(?<![.\w])(?:eventName|event|name)\s*===\s*['"]([a-z]+)['"]/g,
  )) {
    found.add(match[1] as string);
  }
  return found;
}

/**
 * The consumers that deliberately handle less than the whole vocabulary, and
 * exactly which names they skip.
 *
 * Silence is not allowed to be the way a client opts out — that is the defect
 * this file now exists to catch — so an omission is a recorded decision with
 * a reason, and the assertion is an **equality**: a new frame name is red for
 * this file too until somebody either writes the branch or adds the name
 * here, and a name that is handled after all cannot linger in the record.
 */
const IGNORED_BY_DESIGN: Record<string, readonly string[]> = {
  // The documentation's fifty-line "smallest thing that works" — it renders
  // the answer, not the run, and `docs/api.md` introduces it as exactly that.
  // Teaching a reader to handle the progress frames is the *next* page's job;
  // making this one handle seven events would cost it the property it is for.
  'docs/examples/minimal-client.html': ['update', 'progress', 'spawn'],
};

/**
 * The **second** leg of the roll call, and the one the first could not see.
 *
 * `streamConsumers()` above discovers a file by two marks — it names the
 * endpoint and it reads the body. Both plain-HTML pages parse and render in
 * one file, so for them that is the whole story. The editor is split:
 * `RuntimeClient.ts` parses a frame into a `RunStreamEvent` and hands it on,
 * and a *renderer* decides what a person sees. So the pin passed, honestly, on
 * a client that parses `progress` perfectly and an editor that dropped it on
 * the floor — production-ready 56's finding, and a pin defect rather than a
 * second instance of the original one.
 *
 * Discovered the same way, for the same reason: a file that takes a
 * `RunStreamEvent` and branches on `event.type` is a renderer, and a second
 * one cannot appear without appearing here.
 */
const RENDERER_ROOTS = ['src/view', 'src/app'];

function eventRenderers(): string[] {
  return RENDERER_ROOTS.flatMap(sourceFilesUnder).filter((path) => {
    const source = readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8');
    return source.includes('RunStreamEvent') && source.includes('event.type ===');
  });
}

/** The `type` discriminants `RuntimeClient` can actually hand a renderer. */
function variantsTheClientProduces(): string[] {
  return [...client.matchAll(/readonly type: '([a-z]+)'/g)].map((match) => match[1] as string);
}

/** How a renderer spells "I handle this variant". */
function variantsHandledBy(source: string): Set<string> {
  const found = new Set<string>();
  for (const match of source.matchAll(/event\.type\s*===\s*'([a-z]+)'/g))
    found.add(match[1] as string);
  return found;
}

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

/**
 * What each frame *carries* — the level below the names, and where the drift
 * actually was (framework-packaging ticket 10).
 *
 * Read out of the same published description, for the same reason the names
 * are: `FRAME_FIELDS` in `api/streaming.py` is the one declaration, and
 * `sse_responses` writes it into `docs/openapi.json`. Reading it here rather
 * than listing it makes a field the backend adds a red test on the day the
 * snapshot is regenerated, instead of a widening nobody diffs.
 */
function frameFieldsDeclaredFor(path: string, method: string): Record<string, string[]> {
  const description: string = openapi.paths[path]?.[method]?.responses?.['200']?.description ?? '';
  const sentence = description.match(/Frame fields: (.*?)\. /s)?.[1] ?? '';
  const found: Record<string, string[]> = {};
  for (const match of sentence.matchAll(/`([a-z]+)`: ([^;]+)/g)) {
    found[match[1] as string] = [...(match[2] as string).matchAll(/`([A-Za-z]+)`/g)].map(
      (field) => field[1] as string,
    );
  }
  return found;
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
    // And the third file's own doors, so adding it to the list above is not
    // three more strings the matcher never reaches (ticket 11).
    expect(called).toContain('/api/templates');
    expect(called).toContain('/api/examples');
    expect(called).toContain('/api/workflows/{}/publish');
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

    it('has more than one client, and the roll finds them all', () => {
      // The anti-vacuity control for the discovery above, and the finding it
      // is named after: a walker that quietly found one file would make the
      // per-consumer assertion below true of a list of one.
      const consumers = streamConsumers();

      expect(consumers).toContain('src/core/runtime/RuntimeClient.ts');
      expect(consumers).toContain('backend/openstategraph/api/static/chat.html');
      expect(consumers).toContain('docs/examples/minimal-client.html');
      expect(consumers.length).toBeGreaterThanOrEqual(3);

      // A recorded exemption for a file that is no longer a client is a
      // record nobody will re-read; it has to fall over when the file moves.
      for (const path of Object.keys(IGNORED_BY_DESIGN)) {
        expect(consumers, `${path} is exempted from a pin it is no longer in`).toContain(path);
      }
    });

    it('is handled frame for frame by every client', () => {
      const declared = eventNamesDeclaredFor('/api/runs/stream', 'post');

      for (const path of streamConsumers()) {
        const handled = framesHandledBy(readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8'));

        // Per file, not against the concatenation of all of them: a name one
        // client handles said nothing about the others, which is precisely
        // how `progress` reached the editor and not the customer.
        const missing = declared.filter((name) => !handled.has(name));
        const ignored = [...(IGNORED_BY_DESIGN[path] ?? [])];

        expect(
          missing.length,
          `${path} matched almost nothing — check the handled-frame matcher, not the client`,
        ).toBeLessThan(declared.length - 2);
        expect(
          missing,
          `${path} never handles ${missing.join(', ')} — a frame the backend emits ` +
            `and this client drops. Add the branch, or record the omission and its ` +
            `reason in IGNORED_BY_DESIGN.`,
        ).toEqual(ignored);
      }
    });

    it('reaches a renderer, not only a parser', () => {
      // The gap the roll call above is structurally unable to see: in the
      // editor, handling a frame and *showing* it are two files, and only the
      // first one names the endpoint.
      const renderers = eventRenderers();
      const produced = variantsTheClientProduces();

      // Anti-vacuity, both halves: a walker that found nothing, or a variant
      // matcher that found nothing, would make the loop below true of empty.
      expect(renderers, 'no renderer found — check the discovery, not the editor').toContain(
        'src/view/ask/AskPanel.tsx',
      );
      expect(produced).toContain('progress');
      expect(produced.length).toBeGreaterThan(4);

      for (const path of renderers) {
        const handled = variantsHandledBy(readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8'));
        const missing = produced.filter((name) => !handled.has(name));

        expect(
          missing,
          `${path} never handles ${missing.join(', ')} — the client parses that frame ` +
            `and this renderer shows nothing for it. That is how 'progress' shipped to ` +
            `the customer page and not to the editor.`,
        ).toEqual([]);
      }
    });

    /**
     * The level below the names, and the one the pin above never reached.
     *
     * Asserted against `RuntimeClient.ts` and its collaborators only — not
     * against every discovered consumer, unlike the frame *names* above. The
     * two questions are different. A frame name a client ignores is a frame it
     * drops on the floor, which is what `progress` did; a field it does not
     * read is usually a client with a narrower job, and `chat.html` has no
     * business with `pathSlugs`. What the DRY rule actually names is *this*
     * file — the hand-written mirror of the Pydantic seam — so this is where
     * the whole vocabulary has to land.
     */
    it('is parsed field for field by the hand-written client', () => {
      const declared = frameFieldsDeclaredFor('/api/runs/stream', 'post');

      // Anti-vacuity: an extractor that matched nothing would make the loop
      // below a statement about no frames and no fields.
      expect(Object.keys(declared)).toHaveLength(7);
      expect(declared['token']).toContain('withheld');

      for (const [name, fields] of Object.entries(declared)) {
        const missing = fields.filter((field) => !client.includes(field));

        expect(
          missing,
          `RuntimeClient never reads ${missing.join(', ')} off a \`${name}\` frame — ` +
            `the field is emitted, documented and published, and no consumer of this ` +
            `client can see it. That is exactly how 'withheld' shipped to nobody.`,
        ).toEqual([]);
      }
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

  /**
   * `audience` was pinned as a *key* and not as its two values
   * (framework-packaging ticket 10) — the same one-level-short shape as the
   * frame names above, and nearly free to close because this file already
   * reads the schema the enum is in.
   *
   * It is worth closing because of what the values decide. `customer` and
   * `developer` are the boundary `api/audience.py` draws between a reply and
   * the machinery around it; a client sending a third spelling gets a 422, and
   * a client whose union drifts to `'dev'` sends a customer run believing it
   * asked for a developer one — and the difference is silent, because a
   * customer run answers perfectly well.
   */
  it('sends only audiences the contract accepts', () => {
    const declared: string[] = openapi.components.schemas.RunRequest.properties.audience.enum ?? [];

    expect(declared, 'RunRequest.audience is no longer an enum').toEqual(['customer', 'developer']);

    const union = client.match(/audience\??:\s*('(?:customer|developer)'(?:\s*\|\s*'\w+')*)/)?.[1];
    expect(
      union,
      'RuntimeClient no longer types `audience` as a union — check the matcher',
    ).toBeDefined();
    expect([...(union as string).matchAll(/'(\w+)'/g)].map((match) => match[1])).toEqual(declared);
  });
});
