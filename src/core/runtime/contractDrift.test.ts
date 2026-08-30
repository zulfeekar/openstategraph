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
  // `started` and `invoked` joined the list for the same reason and are
  // asserted in the contract's own order: the page renders the answer, and
  // neither the run opening nor a tool being asked for is part of an answer.
  // `started` is the one worth a second thought — it carries `threadId`, which
  // a client needs for a *second* turn — and this page has no second turn.
  'docs/examples/minimal-client.html': [
    'started',
    'update',
    'progress',
    'spawn',
    'settled',
    'invoked',
  ],
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
      expect(Object.keys(declared)).toHaveLength(10);
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

  /**
   * The *response* half, which nothing here watched.
   *
   * Every assertion above is about what the client **sends** — endpoints,
   * request fields, frame names. A field the server publishes and the client
   * never reads is the other direction of the same drift, and it is how
   * `routes` could have shipped on `RunResponse` and reached no reader
   * (`launch-readiness/175`): the run already computed every branch a parallel
   * router matched, and one label per router was all any door published.
   *
   * Pinned narrowly rather than as a whole-schema census: this file's own
   * argument is that a hand-written mirror is pinned on *the things a drift
   * would actually break*, and a census over every response schema would fail
   * on fields the editor has good reason never to read.
   */
  it('reads the run fields the contract publishes', () => {
    const declared = new Set(Object.keys(openapi.components.schemas.RunResponse.properties));

    for (const field of ['answer', 'decisions', 'routes', 'outputs', 'attempts']) {
      expect(declared, `RunResponse is missing ${field}`).toContain(field);
      expect(client, `RuntimeClient never reads ${field}`).toContain(`'${field}'`);
    }
  });

  /**
   * The response half again, and this time as a **census** rather than a list.
   *
   * The assertion above names five fields of one schema, and that is exactly
   * as much drift as it can see. `the-cost-of-one-more/06` added
   * `ThreadHistoryResponse.truncation` — the field that says a run came back
   * cut off at its oldest end — regenerated `docs/openapi.json`, documented it
   * in `docs/api.md`, and this whole file stayed green while the editor's
   * History lane went on drawing a 5,000-superstep run as a 200-superstep one
   * (`the-cost-of-one-more/13`). A drift test that passes on an unmirrored
   * field pins the fields somebody already thought of.
   *
   * So the roll is taken the way the stream consumers above are: **derived**.
   * Every property reachable from the 200 response of every endpoint the
   * client calls, resolved through `$ref`, must appear in the client as a
   * property — a quoted key (`payload['truncation']`), a dot access
   * (`payload.sources`), or a declared one (`truncation?: unknown`). Those are
   * the three spellings this client actually reads a wire field with, and
   * asking for the name as a bare word instead would pass on any field whose
   * name happens to be an ordinary identifier somewhere in seven hundred
   * lines.
   *
   * This is the census the comment above declined as too broad — "a census
   * over every response schema would fail on fields the editor has good reason
   * never to read". It was measured before it was written: **114 fields, four
   * unread**, which is a table of exceptions a person can read rather than a
   * suppression. The narrow pin above is kept, not replaced: it also asserts
   * the *schema* still declares those five, which a client-side census cannot.
   */
  const UNREAD_BY_DESIGN: Readonly<Record<string, string>> = {
    // **None left, and the debt is paid.** `14` asked whether its five were
    // one session or five, and the answer measured out at two and three.
    // `default_model` and `findings` needed a line and a badge on rows that
    // already existed, so they were mirrored and shown together; the three
    // that remained each needed an **affordance the editor did not have** — a
    // staleness warning with nowhere to live, a disclosure of what a parked
    // run is asking, a control that rebuilds routing knowledge. Three
    // features on three surfaces with three design questions was never one
    // ticket, and mirroring any of them here to clear a row would have been
    // the exact defect this census exists to name, inverted: a field read by
    // a client that no consumer of it can see.
    //
    // `editor_stale` and `note` went to `16` and `18`, `pause` to `17`. All
    // three are asserted **by name** in the reader test below rather than by
    // this row's absence, which is the assertion that stops any of them from
    // decaying back into a line in a mapper.
    //
    // An exemption pointing at a ticket is a debt. There are none left.
    // The one genuine by-design entry. `MountDocumentResponse` echoes the
    // address the client just asked with; `WorkflowFileClient` built that URL
    // out of an address it already holds, so reading the echo back would be
    // the client learning its own argument.
    mount_path: 'the address the client sent — reading the echo teaches it nothing',
    // `findings` used to sit here carrying two arguments, and only one of them
    // was about a field this census could see. It read as one name over two
    // schemas — `ValidateResponse`'s document validation, which the editor
    // derives itself from the same rules in `core/model`, and
    // `WorkflowSummaryResponse`'s package-contract lines, which only the
    // backend can know. The row is gone because the second half is read now
    // (`the-cost-of-one-more/14`), and the first half turns out never to have
    // been in scope at all: **no client file calls `POST
    // /api/workflows/validate`**, so `ValidateResponse` is not among the
    // schemas walked below and an exemption for it was an argument about
    // nothing. Recorded rather than deleted, because a plausible sentence
    // defending a field the instrument could not reach is the way an
    // exemption list starts describing something other than itself — and this
    // one had already been read twice as though it were load-bearing.
  };

  /** Every property name reachable from a schema, `$ref`s resolved. */
  function fieldsOf(schema: unknown, seen: Set<string>, found: Set<string>): void {
    if (schema === null || typeof schema !== 'object') return;
    const node = schema as Record<string, unknown>;
    const ref = node['$ref'];
    if (typeof ref === 'string') {
      const name = ref.split('/').pop() as string;
      if (seen.has(name)) return;
      seen.add(name);
      fieldsOf(openapi.components.schemas[name], seen, found);
      return;
    }
    const properties = node['properties'];
    if (properties && typeof properties === 'object') {
      for (const [key, value] of Object.entries(properties as Record<string, unknown>)) {
        found.add(key);
        fieldsOf(value, seen, found);
      }
    }
    for (const key of ['items', 'anyOf', 'allOf', 'oneOf', 'additionalProperties']) {
      const branch = node[key];
      if (Array.isArray(branch)) branch.forEach((entry) => fieldsOf(entry, seen, found));
      else if (branch) fieldsOf(branch, seen, found);
    }
  }

  /** Every field the endpoints this client calls can send back to it. */
  function fieldsThePublishedContractSends(): Map<string, string> {
    const called = new Set(pathsCalledByTheClient());
    const where = new Map<string, string>();
    const seen = new Set<string>();
    for (const [path, operations] of Object.entries(openapi.paths)) {
      if (!called.has(normalise(path))) continue;
      for (const [method, operation] of Object.entries(operations as Record<string, unknown>)) {
        const schema = (operation as { responses?: Record<string, Record<string, never>> })
          ?.responses?.['200']?.['content']?.['application/json']?.['schema'];
        if (!schema) continue;
        const found = new Set<string>();
        fieldsOf(schema, seen, found);
        for (const field of found) if (!where.has(field)) where.set(field, `${method} ${path}`);
      }
    }
    return where;
  }

  /**
   * The three spellings this client reads a wire field with — and no fourth.
   * A bare-word match would make `end`, `kept` and `pause` pass on the strength
   * of an unrelated local variable, which is a pin that cannot fail.
   */
  const clientReads = (field: string): boolean =>
    new RegExp(`(['"]${field}['"]|\\.${field}(?![\\w$])|(?<![\\w$.])${field}\\??\\s*:)`).test(
      client,
    );

  it('reads every field the endpoints it calls can send back', () => {
    const published = fieldsThePublishedContractSends();

    // Anti-vacuity, both halves: a walker that resolved no `$ref` would make
    // the loop below a statement about nothing, and the finding this test is
    // named for is a field two levels down a `$ref`.
    expect(published.size).toBeGreaterThan(80);
    expect([...published.keys()]).toContain('truncation');

    const unread = [...published.keys()].filter((field) => !clientReads(field));

    expect(
      unread.filter((field) => !(field in UNREAD_BY_DESIGN)),
      `published and unread: ${unread
        .map((field) => `${field} (${published.get(field)})`)
        .join(', ')} — the server sends it, the contract documents it, and no ` +
        `consumer of this client can see it. Mirror it, or record it in ` +
        `UNREAD_BY_DESIGN with the reason.`,
    ).toEqual([]);

    // Equality in the other direction too, the same way IGNORED_BY_DESIGN is
    // asserted: a field that got mirrored after all cannot linger here as a
    // recorded exception nobody re-reads.
    expect(
      Object.keys(UNREAD_BY_DESIGN).filter((field) => clientReads(field)),
      'recorded as unread but the client reads it — delete the entry',
    ).toEqual([]);
  });

  /**
   * **A mirror is not a reader, and the census above cannot tell them apart.**
   *
   * `clientReads` is satisfied by a property appearing in one of three client
   * files, which is exactly the property `truncation` needed and exactly the
   * property `progress` had before production-ready 56 found that the editor
   * parsed it and drew nothing. So the cheapest way to make the census green
   * is to add a line to a mapper and stop — a field read by a client that no
   * consumer of that client can see, which is this file's own finding turned
   * inside out.
   *
   * Discovered rather than listed, like the renderers above: a surface reads
   * a mirrored field by its camelCase name, and there is no fourth spelling
   * once the wire name has been mapped. The two fields `14` mirrored are
   * asserted by name because they are what this assertion was built for; a
   * third one added later inherits nothing from this and should join it.
   */
  it('lets no mirrored field stop at the mapper', () => {
    const surfaces = ['src/view', 'src/app', 'src/nodes'].flatMap(sourceFilesUnder);
    const read = (field: string): string[] =>
      surfaces.filter((path) =>
        new RegExp(`\\.${field}(?![\\w$])`).test(
          readFileSync(fileURLToPath(new URL(path, REPO)), 'utf8'),
        ),
      );

    // Anti-vacuity: a walker that found no surfaces would make both claims
    // below true of nothing.
    expect(surfaces.length).toBeGreaterThan(100);

    // Named surfaces, not merely a non-empty list. `AccessibilityCheck.tsx`
    // computes a `Finding[]` of its own, so "something in `src/view` writes
    // `.findings`" would have been true before this ticket and would have
    // stayed true if the badge were deleted tomorrow. What the mirror owes is
    // *this* reader.
    expect(
      read('defaultModel'),
      'the model a run gets when it names none reaches no surface',
    ).toContain('src/view/overlays/CredentialsDialog.tsx');
    expect(read('findings'), 'the package-contract lines reach no surface').toContain(
      'src/view/workflow/WorkflowManager.tsx',
    );
    // `the-cost-of-one-more/16`. The bundle-freshness answer, which was the
    // hardest of `14`'s three to place because there was no surface in this
    // product that said anything about the editor you are running. There is
    // one now, and it is a *named* one for the reason the two above are: the
    // store publishes `editorStale()` and a component that stopped rendering
    // it would leave the census green while the warning went back to reaching
    // nobody.
    expect(
      read('editorStale'),
      'the server said this bundle predates its source and no surface says so',
    ).toContain('src/view/topbar/EditorFreshnessChip.tsx');
    // `the-cost-of-one-more/18`. The publish note — read as a *signal* rather
    // than printed: its presence is the backend saying it did not rebuild
    // routing knowledge, and `consequences` turns that into the editor's own
    // sentence about the editor's own control. Forwarding the backend's
    // string, which names an HTTP verb and a path template, is what this
    // ticket refused to do; dropping it is what it was filed for.
    expect(
      read('note'),
      'the publish note reaches no surface — the routing clause is hardcoded again',
    ).toContain('src/view/workflow/consequences.ts');
    // `the-cost-of-one-more/17`. The comment above says a third field added
    // later inherits nothing from this and should join it, so it does. The
    // History lane is the only consumer: `pauseLines` lives in `core/` and
    // would satisfy `clientReads` on its own while drawing nothing.
    expect(read('pause'), 'what a parked run is asking reaches no surface').toContain(
      'src/view/ask/PastRuns.tsx',
    );
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
