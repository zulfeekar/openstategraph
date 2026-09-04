import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * CLAUDE.md's ceiling, on the TypeScript side.
 *
 *     "A class with many public members is a design failure, not a
 *     convenience. If it can be described only with 'and', split it.
 *     Ceiling: ~10 public members, one reason to change."
 *
 * `backend/tests/test_public_surface_ceiling.py` is the sibling; this is the
 * half the system design review measured and nobody pinned
 * (reviews-2026-08-14 tickets 07 and 14).
 *
 * **Three classes carry a recorded exception, and that is the point of the
 * file.** The review's finding was not only that they were wide — it was that
 * *"none is recorded as an exception the way `WorkflowModel` is, which is the
 * part that makes them violations rather than decisions."* A number written
 * down with its reasoning is a decision; the same number undocumented is a
 * class nobody has looked at. Every entry below therefore has to say what was
 * removed, what was considered, and what would take it further.
 *
 * The numbers are exact, not upper bounds. A class that drops a member should
 * fail here and be re-recorded lower — an exception that quietly has room to
 * spare is how a ceiling becomes a floor.
 */
const read = (relative: string): string =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

/**
 * What a consumer can reach: public methods, accessors and properties.
 *
 * A collaborator counts as one member — `paper.viewport` is a member,
 * `paper.viewport.fit` is not. That is the whole mechanism by which a class
 * gets under the ceiling, and it is how CLAUDE.md describes
 * `WorkflowController`'s ten.
 */
function classesIn(file: string): Map<string, string[]> {
  const source = ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true);
  const classes = new Map<string, string[]>();
  const walk = (node: ts.Node): void => {
    if (ts.isClassDeclaration(node) && node.name) {
      const found = new Set<string>();
      for (const member of node.members) {
        if (ts.isConstructorDeclaration(member)) continue;
        const flags = ts.getCombinedModifierFlags(member);
        if (flags & (ts.ModifierFlags.Private | ts.ModifierFlags.Protected)) continue;
        const name =
          member.name && ts.isIdentifier(member.name) ? member.name.text : member.name?.getText();
        if (!name || name.startsWith('#') || name.startsWith('_')) continue;
        found.add(name);
      }
      classes.set(node.name.text, [...found]);
    }
    ts.forEachChild(node, walk);
  };
  walk(source);
  return classes;
}

function publicMembers(file: string, className: string): string[] {
  const members = classesIn(file).get(className);
  if (!members) throw new Error(`${className} not found in ${file}`);
  return members;
}

/**
 * Every class under `src/` over the ceiling — derived, not remembered.
 *
 * The audit of 2026-08-15 found the reason this exists: pins chosen by hand
 * cover the classes somebody already worried about, which are the ones least
 * likely to drift. Three were pinned here and two in the Python sibling,
 * against nineteen over the ceiling — including `WorkflowModel` at 43, the
 * exception CLAUDE.md argues at the greatest length and nothing held to the
 * shape that argument assumed.
 *
 * Test and spec files are skipped for the same reason `hatch_build.py` skips
 * them: they are not the app, and a fixture class written to prove a point is
 * not a design decision.
 */
function classesOverTheCeiling(): Map<string, number> {
  const root = fileURLToPath(new URL('.', import.meta.url));
  const over = new Map<string, number>();
  for (const entry of readdirSync(root, { recursive: true, encoding: 'utf8' })) {
    const relative = entry.split('\\').join('/');
    if (!/\.tsx?$/.test(relative) || /\.(test|spec)\.tsx?$/.test(relative)) continue;
    if (relative.endsWith('.d.ts')) continue;
    for (const [className, members] of classesIn(`./${relative}`)) {
      if (members.length > CEILING) over.set(`./${relative}#${className}`, members.length);
    }
  }
  return over;
}

const CEILING = 10;

interface Subject {
  readonly file: string;
  readonly className: string;
  /** Exact expected count. `CEILING` where the class is genuinely under it. */
  readonly members: number;
  /** Why it is allowed to be wide. Absent means it is not. */
  readonly exception?: string;
}

const SUBJECTS: readonly Subject[] = [
  {
    file: './core/model/WorkflowModel.ts',
    className: 'WorkflowModel',
    members: 41,
    exception: `CLAUDE.md's recorded exception, and until 2026-08-15 the one nothing
      measured — which is how an argument becomes a story. The argument itself
      still holds and is not re-litigated here: the internals *are* split
      (AdjacencyIndex and GraphQueries hold the real implementations, each
      independently unit-tested), and ticket 17 concluded that collapsing the
      flat surface onto 'model.queries.x()' / 'model.adjacency.x()' is a
      100+-call-site rename across canvas, execution and validation code for a
      smaller public surface rather than a clearer design.

      What was missing was the number. Forty-one is 19 queries, 17 mutators,
      'on'/'onAny'/'dispose', 'toJSON' and 'transact'; ten of the queries
      (edgesOf, edgesInto, edgesFrom, childrenOf, descendantsOf, predecessorsOf,
      successorsOf, countOfType, topologicalOrder, bounds) are verbatim
      one-liners onto the private 'queries', which is precisely the shape the
      exception describes and now the shape it is held to. A forty-second member
      fails this test, and adding one is the thing CLAUDE.md forbids
      ("do not add new *behavior* directly onto WorkflowModel either way").

      It was 43 until install-experience 21. Two members had no caller at all —
      'requireNode', and 'isEmpty', which Inspector.tsx:279 reimplements inline
      as a local const rather than calling — so the exception was two members
      wider than any consumer had ever asked for. 'requireNode' went from
      'IWorkflowModel' with it: an interface method nothing implements against
      and nothing calls is a contract in name only.`,
  },
  {
    file: './canvas/PaperController.ts',
    className: 'PaperController',
    members: 15,
    exception: `Nine of the fifteen are collaborators — graph, paper, adapter, viewport,
      autoLayout, follower, mounts, features, shortcuts — which is the shape
      CLAUDE.md describes for WorkflowController ("each a collaborator...
      extend it by adding a collaborator, never a method"). Ticket 14 removed
      the three that were not: a dead 'element' getter with no caller in the
      repository, a 'clientToLocal' that forwarded verbatim to the already
      public 'viewport', and a 'viewportCenter' that derived a camera fact
      from 'viewport.visibleRect' — that one moved onto Viewport as 'center',
      where a camera calculation belongs.

      What is left over ten is grid state (isGridVisible/setGridVisible),
      'observeConnectionRejections', and the two framing calls that genuinely
      compose two collaborators the consumer cannot reach separately —
      'fitToContent' and 'contentBounds' both need the model, which is
      private here. Taking it under the ceiling means making grid a canvas
      feature in the 'features' registry, which is a real change with a real
      question attached (React toggles it, so it needs a handle) rather than
      a rename. Named here so the next person starts from it.`,
  },
  {
    file: './canvas/Viewport.ts',
    className: 'Viewport',
    members: 19,
    exception: `One reason to change: where the camera is and how it moves. The members
      are the vocabulary of a camera — read the transform, convert between
      screen and model, pan, zoom, frame, glide — and there is no sub-object
      here that consumers ask for together.

      Splitting the glide was the candidate and it does not pay. 'glideTo'
      and 'stopGlide' do have their own reason to change (easing, reduced
      motion, the rAF handle), but both go through the private 'apply', so a
      separate collaborator would need that made public: minus two members,
      plus two, and the transform's single funnel — the thing that guarantees
      every listener hears a change exactly once — widened for nothing.

      The value ticket 14 actually added here is the tests. This class is 250
      lines of arithmetic every canvas gesture depends on and it had **no test
      at all**; 'Viewport.test.ts' now covers the zoom anchor, the
      conversion round trip, the fit cap, the empty-graph and unmeasured-
      container paths, and the change-notification contract. Three deliberate
      mutations to the source were checked to fail it. An exception recorded
      without that would be a guess.`,
  },
  {
    file: './core/model/AbstractNodeModel.ts',
    className: 'AbstractNodeModel',
    members: 24,
    exception: `The 'WorkflowModel' case, and CLAUDE.md's recorded reasoning for that
      exception transfers: its members are read from canvas, execution,
      validation and view code in the hundreds, so collapsing 'node.position'
      onto 'node.geometry.position' is a very large rename for a smaller
      surface rather than a clearer design.

      Ticket 14 did take the part that was not that. Seven public 'apply*'
      mutators sat under a comment reading "WorkflowModel only" — with the
      comment as the entire enforcement — and they are now 'node.write', with
      'nodeWriteSeam.test.ts' holding the layering rule the comment asked for.
      That was worth doing independently of the count: seven public setters
      are seven ways to move a node without a command, which does not fail,
      it silently drops out of undo. Two dead members went with them
      ('applyData', 'getFlag' — no caller anywhere in src/).

      The ports group (ports, port, inputs, outputs, primaryInput,
      primaryOutput) is the next-largest cluster and was **considered and
      rejected**. Ticket 07's rule is to prefer a grouping the call sites
      already make; these are each read by a different consumer — the adapter
      takes 'port', edgeCommands takes the primaries, layout takes the lists —
      and never together. That is a grouping invented rather than found, and
      ticket 07 records what those are worth.`,
  },
  {
    file: './core/runtime/WorkflowFileClient.ts',
    className: 'WorkflowFileClient',
    members: 18,
    exception: `Eleven reads, six writes and one subscription over the file API — a flat
      HTTP adapter where every member is its own fetch and there is nothing to
      delegate to. Width here is the width of the endpoint surface, and the
      class does not get to be narrower than the API it adapts.

      The eighteenth is 'mountUsage' (\`production-ready\` ticket 17,
      \`GET /api/workflows/{slug}/mount-usage\`) — one more read the "push to
      package" action needs before it writes: how many mounts of a package
      exist across the workspace, and which of them already shadow the field
      about to change. Same shape as every other member here, one fetch, no
      shared state with its neighbours — the exception's own argument for
      not splitting the class covers it without adding a new one.

      The interesting part is that the split is **already drawn, in the type
      system**: this class declares four interfaces at once
      (IWorkflowFileClient, ICatalogueEvents, IWorkflowTemplates,
      IWorkflowExamples) and consumers import those, never this. That is the
      Interface Segregation half of the rule kept, with one implementation
      behind it — 'sqlSchema' is reached by SqlSchemaBody, 'watchCatalogue' by
      the catalogue view, and neither knows about the other's methods.

      Splitting the class to match would mean four objects each holding the same
      baseUrl, fetchImpl and eventSourceImpl, constructed together at one call
      site, so the consumer's view would not change and the wiring would grow.
      Recorded rather than done, and the next person should check the interface
      list first: if a fifth interface appears here, that is the signal this
      became a bucket.`,
  },
  {
    file: './core/providers/ProviderRegistry.ts',
    className: 'ProviderRegistry',
    members: 15,
    exception: `Two reasons to change, and both are visible in the member list: which
      providers and models exist (register, get, list, resolve, selectionFor,
      model, modelOptions, reasoningEffortLevelsFor, setWorkflowDefaultModel,
      refreshModels) and what credentials they are configured with (setApiKey,
      getApiKey, describeApiKey, setBaseUrl). The second already has a private
      collaborator — CredentialStore — and 'getApiKey' is a verbatim
      pass-through to it, so exposing 'credentials' as one member in place of
      three is a genuine reduction rather than an invented grouping. That is
      what would take this to twelve, and it is not done here.

      Install-experience 21 took the two that were free: 'allModels' had no
      caller anywhere, and 'providers' leaked the inner Registry with no
      external reader (every workbench.providers.list() resolves to this
      class's own wrapper, not to that field) — it is private now, so a second
      credential-unaware path to the same providers no longer exists.

      Pinned at fifteen meanwhile, because the credential move is a real
      change to a class the model picker, the runtime health dot and the
      workflow settings panel all read.`,
  },
  {
    file: './core/providers/ILLMProvider.ts',
    className: 'AbstractLLMProvider',
    members: 14,
    exception: `Five abstract members are the provider's identity (id, label, models,
      requiresApiKey, complete). Four are the shared credential behaviour every
      provider inherits rather than reimplements (setApiKey, setBaseUrl,
      hasApiKey, isConfigured) — the anti-duplication rule working exactly as
      CLAUDE.md states it, declared once on the abstract base.

      The remaining five are **declarations, not behaviour**: credentialsHint,
      allowsCustomModel, configurableEndpoint, runtimeCredentialKey and
      reasoningEffortLevels are optional properties defaulting to undefined, by
      which a provider says what it supports. That is the open/closed rule kept
      the cheap way — a new capability is a field a provider sets, not a
      subclass and not an edit to the consumer. Hiding them behind a
      'capabilities' object would be one member instead of five and one more
      indirection at every read site; considered, and not worth it while the
      list is five long. If it reaches ten, do it.`,
  },
  {
    file: './controller/SelectionModel.ts',
    className: 'SelectionModel',
    members: 13,
    exception: `One reason to change: what is selected. Six queries (nodes, edges, size,
      isEmpty, hasNode, hasEdge), five mutators (selectNodes,
      selectEdges, set, clear, prune) and the on/dispose pair every observable
      model here carries.

      Nodes and edges are the two axes of one selection rather than two
      sub-objects: 'set' takes both at once, 'prune' walks both, and the canvas
      asks "is this selected" without caring which kind it holds. A
      'selection.nodes.has()' / 'selection.edges.has()' split would double the
      mutator surface it removed and break the one invariant this class exists
      to keep — that a change to either axis notifies exactly once, through the
      private commit.

      Fourteen until install-experience 21, where 'soleNode' went for having no
      caller; at thirteen this stays a wide vocabulary for a single noun, which
      is the shape Viewport is recorded under.`,
  },
  {
    file: './core/providers/OllamaProvider.ts',
    className: 'OllamaProvider',
    members: 11,
    exception: `Almost entirely override, which is a property of the counting rule as much
      as of the class: this side counts *declared* members, so a leaf that
      concretises its base looks as wide as the base. Ten of the eleven are the
      abstract five made real (id, label, models, requiresApiKey, complete), the
      four capability declarations, and 'isConfigured' — overridden because
      Ollama is the one vendor reachable two ways, by key or by a host you run,
      which CLAUDE.md records as a standing instruction.

      Genuinely new: 'listModels', the interface's optional discovery method.
      It was twelve until install-experience 21 removed 'probe', a second
      liveness check with no caller anywhere in src/ — the runtime health dot
      asks the backend, not the browser. Everything vendor-specific — cloud
      detection, the seed list, header assembly, host resolution — is private,
      which is the part that matters: the base's surface did not widen to admit
      a second provider.`,
  },
  {
    file: './app/Workbench.ts',
    className: 'Workbench',
    members: 12,
    exception: `The composition root, and the shape CLAUDE.md blesses rather than tolerates:
      ten of the twelve are readonly collaborators (registry, preferences,
      model, credentials, providers, connectionValidator, workflowValidator,
      serializer, engine, controller) and the other two are 'warmUp', a
      pass-through to providers.refreshModels(), and 'dispose', which fans out
      to the three collaborators that own resources.

      It has no logic of its own beyond construction and the two serializer
      migrations it registers. "Extend it by adding a collaborator, never a
      method" is the rule for WorkflowController and it is doubly the rule here:
      an eleventh collaborator is this class working, an extra method is the
      composition root starting to do something, and this pin is where the
      difference gets noticed. That is why the count is exact rather than a
      bound.`,
  },
  {
    file: './core/model/GraphQueries.ts',
    className: 'GraphQueries',
    members: 11,
    exception: `The object WorkflowModel's recorded exception points at, one over the
      ceiling and for the least interesting reason: it is eleven read-only
      questions about a graph (edgesOf, edgesInto, edgesFrom, childrenOf,
      descendantsOf, predecessorsOf, successorsOf, isAncestorOf, countOfType,
      topologicalOrder, bounds), no state of its own, one reason to change —
      what a graph relation means.

      Splitting it would mean naming sub-vocabularies (traversal versus counting
      versus geometry) that no consumer asks for separately: every one of these
      is reached through WorkflowModel's pass-through by a different caller,
      never in a group. This is the class that *was* the extraction, and an
      extraction that then needs extracting is a signal worth having — so it is
      pinned at eleven rather than waved through as "basically ten".`,
  },
  {
    file: './controller/WorkflowController.ts',
    className: 'WorkflowController',
    members: 11,
    exception: `**The count CLAUDE.md asserted as settled, and it had drifted.** Ticket 17
      fixed this class at "10 public members, each a collaborator"; it is
      eleven. Nine are the readonly collaborators (selection, nodes, edges,
      grouping, clipboard, history, document, selectionActions — and 'model',
      the one that is re-exported rather than owned, which is the drift), plus
      'onChange' and 'dispose'. No queries, no mutators, no constants: the
      design is intact and the sentence describing it was not.

       That is the defect the audit called stale-claim, in the file that warns
       about stale claims — a number in prose has no way to fail. CLAUDE.md now
       says eleven and names the eleventh; this pin is what makes the next drift
       a red test instead of a paragraph. Taking it back to ten means asking
       whether 'model' should be reached through the controller at all, which is
       a question about the layering rule and not about a member count, so it is
       deliberately not answered by trimming.`,
  },
  {
    file: './core/runtime/RuntimeClient.ts',
    className: 'RuntimeClient',
    members: 16,
    exception: `One thin method per backend door, same shape as every member already
      here — 'run', 'runStream', 'resume', 'health', 'pastRuns', 'pastRun',
      'providers', 'verifyProvider', 'kanbanCards', and now 'runPatrol'
      (kanban-patrol/27) — a POST to the door the board's "Run Patrol" button
      calls instead of the placeholder toast it used to show. The class
      itself is not growing a new *kind* of responsibility; it is growing by
      exactly the count of endpoints this backend exposes, which is the
      argument the module's own docstring already makes for why it stays
      thin in code-line terms while wide in member-count terms.

      Ten was never a claim that eleven doors is one too many — it is the
      point past which a width has to be a decision rather than an accident,
      and this is that decision, made once, here. The next door
      ('kanban_list_cards', 'kanban_answer_card' — both still open tickets)
      would need this exception's number updated honestly rather than
      silently widened, which is exactly what this test exists to force.

      **Eleven -> thirteen** (kanban-patrol/07). Two more, both the read
      half of the same door 'runPatrol' now only starts: 'patrolStatus'
      (the refetch-on-open half of "refetch plus subscribe") and
      'watchPatrolEvents' (the push half, one 'EventSource' subscription on
      the sibling stream). Not a new kind of member — 'kanbanCards' is
      already a thin GET, and 'watchPatrolEvents' is the same shape
      'WorkflowFileClient.watchCatalogue' already carries, on a class that
      already imports its 'EventSourceFactory' type rather than declaring a
      second one. The next door still needs this number updated honestly,
      unchanged from the paragraph above.

      **Thirteen -> fourteen** (kanban-patrol/19). 'releaseCard', the human's
      explicit press on a card the system has already flagged stale — one
      more thin door, same shape as every member already here: a POST, an
      'Err' reading the backend's own refusal message. Not a new kind of
      member, and the same rule still applies: the next door still needs
      this number updated honestly rather than silently widened.

      **Fourteen -> fifteen**, 2026-09-04 (stable-beta-public/03, slice 1 of
      'docs/plans/token-status-bar'). 'spend' — one GET on
      '/api/runs/spend', the read behind the editor's token status bar. The
      same thin shape as 'pastRuns' down to the 'describeFailure' branch,
      and the count still rises by exactly the number of doors this backend
      exposes rather than by a new kind of responsibility. Recorded here
      before the surface that reads it was drawn, which is the point of the
      rule: the widening is a line in a review rather than a discovery.

      **Fifteen -> sixteen**, 2026-09-04 (kanban-patrol/15). 'answerCard' —
      a POST recording the decision a person typed onto a Needs You card,
      which is the last of the two doors the paragraph four up named as
      still open ('kanban_list_cards' shipped on the MCP side and needed no
      method here; this one is the browser's). Same thin shape as
      'releaseCard' beside it, down to reading the backend's own 'detail' on
      a refusal, and the rule it was written under is the one being kept:
      updated honestly, in a review, rather than silently widened.`,
  },
];

describe.each(SUBJECTS)('$className', (subject) => {
  it('has exactly the public surface recorded for it', () => {
    const members = publicMembers(subject.file, subject.className);

    expect(members.length, `${subject.className}: ${members.sort().join(', ')}`).toBe(
      subject.members,
    );
  });

  it(
    subject.exception
      ? 'carries a written reason for being over the ceiling'
      : 'is under the ceiling',
    () => {
      if (!subject.exception) {
        expect(subject.members).toBeLessThanOrEqual(CEILING);
        return;
      }
      // A number over the ceiling with no reasoning is the defect the review
      // named — a violation rather than a decision. Length is a crude proxy
      // for "somebody actually thought about this", and a crude proxy beats
      // none.
      expect(subject.exception.trim().length).toBeGreaterThan(400);
    },
  );
});

it('records every class over the ceiling, and only those', () => {
  // The half that was missing. Three classes were pinned here and two in the
  // Python sibling, against nineteen over the ceiling — so the guard covered
  // the classes somebody had already thought about, which are the ones least
  // likely to move. The list is derived now; the table has to match it.
  const census = classesOverTheCeiling();
  const recorded = new Set(SUBJECTS.map((s) => `${s.file}#${s.className}`));

  const unrecorded = [...census].filter(([key]) => !recorded.has(key));
  const departed = [...recorded].filter((key) => !census.has(key));

  expect(
    unrecorded,
    `over the ceiling and not recorded. Take it under ${CEILING} by adding a collaborator, ` +
      'or add it to SUBJECTS with the argument that makes the number a decision.',
  ).toEqual([]);
  expect(departed, 'recorded but no longer over the ceiling — delete the entry').toEqual([]);
});

it('records an exception only for a class that needs one', () => {
  // Stops the table becoming a place where a comfortable number gets an
  // essay attached to it.
  for (const subject of SUBJECTS) {
    if (subject.members <= CEILING) {
      expect(subject.exception, `${subject.className} is under the ceiling`).toBeUndefined();
    }
  }
});
