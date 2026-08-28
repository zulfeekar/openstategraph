import { Err, Ok, type Result } from '@core/kernel/Result';
import { McpRegistryClient } from './McpRegistryClient';
import { describeRuntimeBase, runtimeBaseUrl } from './runtimeBaseUrl';

/**
 * The editor's only route to a runtime.
 *
 * Lives in `core/` because it is framework-free: no React, no JointJS, and
 * `fetch` is injected so it runs under Vitest's node environment like everything
 * else here.
 *
 * The contract it enforces is ticket 07's: the browser **posts a document and a
 * question**, and receives an answer. It never builds or executes a graph —
 * that is the backend's job, and the reason this class is so thin is that
 * keeping it thin is the point. It *stores* no provider credentials either;
 * it forwards whatever the caller passes in `credentials`, which the
 * credentials dialog owns.
 */

/**
 * What the **server** is configured for, per provider.
 *
 * Mirrors `ProviderStatusResponse`. Deliberately carries no key material: the
 * endpoint sends names and booleans, so there is nothing here to leak even by
 * accident (the-editor-makes-a-real-package ticket 04).
 */
export interface ProviderStatus {
  readonly name: string;
  readonly label: string;
  /** Whether this server can use it right now. Presence, not validity. */
  readonly configured: boolean;
  /** Which variable actually did it — Ollama takes either of two. */
  readonly configuredBy: string | null;
  /** Every variable that would configure it. Any one is enough. */
  readonly envVars: readonly string[];
  /**
   * Whether the integration package is importable on this server —
   * `ProviderEnvironment.is_installed()`, the same check `openstategraph
   * providers` reports as "needs its extra". Independent of `configured`: a
   * package can be installed with no credential, or a credential can be set
   * for a package nobody installed. Unlike a missing credential, a missing
   * package cannot be fixed from the browser's own credential store, which is
   * why the picker treats the two differently (launch-readiness/28).
   */
  readonly installed: boolean;
  /** The exact `pip install` line for this provider's integration. */
  readonly installHint: string;
  /** The pip extra's bare name, e.g. `openai`. */
  readonly extra: string;
  /**
   * A glance at what configured it: `sk****` for a secret, the whole value
   * for an address like `OLLAMA_HOST`. `null` when nothing is set.
   *
   * The mask is fixed-width by design, so it shows that *a* key is present
   * without revealing how long it is.
   */
  readonly keyHint: string | null;
}

/**
 * `GET /api/providers`'s whole answer — the rows, plus which environment
 * this server read to produce them.
 *
 * Mirrors `ProviderStatusListResponse` (providers-and-credentials/13): the
 * CLI and a running server can read two different `.env` files —
 * `openstategraph providers` loads one itself; `create_app` never does. A
 * reader with keys in `.env` could not tell, from this endpoint alone,
 * whether a server they started actually has them. `environment` is that
 * missing sentence, in the server's own words.
 */
export interface ProviderStatusList {
  readonly rows: readonly ProviderStatus[];
  readonly environment: string;
  /**
   * What a run through the default provider will do right now — the server's
   * own words, `ProviderCatalogue.elected_default().reason`
   * (providers-and-credentials/14). The same clause `openstategraph
   * providers` prints as its header, so a component that wants to say
   * whether a run will work reads this instead of composing its own claim.
   */
  readonly runReadiness: string;
}

export interface RunRequest {
  /** A `workflow.json` document, exactly as the serializer emits it. */
  readonly workflow: unknown;
  readonly question: string;
  /** Provider-prefixed, e.g. `ollama:gpt-oss:120b-cloud`. Server picks if absent. */
  readonly model?: string;
  /** Superstep budget — **not** an iteration count. */
  readonly recursionLimit?: number;
  /**
   * The open workflow's slug, when known. The backend layers that
   * workflow's own `tools/` over its defaults, so a document can bind the
   * tools that live beside it. Optional — a run without it still works.
   */
  readonly workflowSlug?: string;
  /**
   * Provider keys held in this browser, by backend environment-variable name
   * (`{ ANTHROPIC_API_KEY: '…' }`) — see `collectRuntimeCredentials`.
   *
   * Sent so the editor's "Models and credentials" dialog is the single home
   * for keys across *both* runtimes. The backend applies them only where it
   * has no value of its own, so this is a fallback and never an override.
   */
  readonly credentials?: Readonly<Record<string, string>>;
  /**
   * Who this run is for. `'developer'` additionally entitles the run to the
   * backend's developer channel — authoring warnings and the capability
   * suggestion an agent may offer when it is blocked for want of a tool.
   *
   * Omitted means `'customer'`, which is what the `/chat` page sends by
   * never setting it: a person who cannot edit the workflow must not be
   * offered edits to it. See `backend/openstategraph/api/audience.py` —
   * enforcement is at the runtime seam, not here.
   */
  readonly audience?: 'customer' | 'developer';
  /**
   * The conversation this question belongs to — the thread the previous turn
   * reported back on its terminal frame.
   *
   * Omitting it is not "no thread": the server invents one per request, so
   * every send becomes turn one and the graph's `messages` channel is always
   * empty. That is the whole of the follow-up defect — "how did you get
   * that?" arrives with nothing to refer to. Send the id back and the
   * question is the next *turn* of the same conversation.
   */
  readonly threadId?: string;
}

export interface RunResult {
  /**
   * The thread this run happened in — send it as `threadId` on the next
   * question to make that question a follow-up.
   *
   * Empty when the reply did not name one: `POST /api/runs`, the
   * non-streaming sibling, returns no thread, and a backend older than the
   * frame that discloses it will not either. Empty therefore means "this
   * response told me nothing about its thread", never "there was no thread" —
   * a caller must not overwrite a thread it already knows with it.
   */
  readonly threadId: string;
  readonly answer: string;
  /**
   * node id → branch taken, so the canvas can highlight the path that ran.
   *
   * **The outermost document's own nodes only** (ticket 40). It used to hold
   * every document the run touched, and `concierge` and `chinook-assistant`
   * ship sharing `in1`, `router1` and `out1` — so the child's values landed on
   * the parent's keys and the parent's own branch was simply gone. Anything
   * below the top level is in `nested`.
   */
  readonly decisions: Readonly<Record<string, string>>;
  /** node id → that node's output, for per-node inspection. Top level only. */
  readonly outputs: Readonly<Record<string, string>>;
  /**
   * The same two, for every node inside a mounted document — keyed by **mount
   * path**, `wf-music/agent-sql`.
   *
   * The same vocabulary as a frame's `path` and the address bar
   * (`MountAddress`), because "which node inside which mount" is one question
   * and one spelling of it is the point of ticket 42. Two mounts of one
   * package therefore stay apart: `wf-music/agent-sql` and
   * `wf-other/agent-sql` are different keys where the slug was the same.
   *
   * Always present; empty for a run with no mounts, so a reader needs no
   * special case.
   */
  readonly nested: {
    readonly outputs: Readonly<Record<string, string>>;
    readonly decisions: Readonly<Record<string, string>>;
  };
  readonly attempts: number;
  /** Mermaid text of the graph that actually compiled. */
  readonly mermaid: string;
  /**
   * True when a grader ran out of attempts and `answer` above is a candidate
   * it had rejected, published because the loop had to end somewhere.
   *
   * Visible on **both** audiences — `launch-readiness` 25: `attempts` alone
   * proved the loop exhausted itself, but nothing said whether the last
   * attempt had passed or been forced through, so a rejected answer reached
   * a customer indistinguishable from one that passed first try. The
   * grader's *reason* can quote internals and stays on
   * `developer.warnings`; that the event happened must not be
   * developer-only.
   */
  readonly publishedRejected: boolean;
  /**
   * The developer channel, or `null` when this run was not entitled to one.
   *
   * `null` is not "nothing was wrong" — it is "this run was a customer's,
   * and the backend did not send it". Kept distinguishable on purpose: a UI
   * that renders an empty warning list as "all clear" would be making a
   * claim the payload never made. See `api/audience.py`.
   */
  readonly developer: DeveloperChannel | null;
  /**
   * Authoring findings, flattened from `developer` for the callers that only
   * ever wanted the list. Empty for a customer run — which is honest, since
   * such a run has no findings *it may see*.
   */
  readonly warnings: readonly string[];
}

/** Everything a run knows that only a workflow editor may see. */
export interface DeveloperChannel {
  readonly warnings: readonly string[];
  /**
   * The raw capability suggestion, exactly as the agent emitted it. Raw
   * because whether it can be *applied* is a question only the live editor
   * can answer — `src/view/ask/suggestion.ts` is where that check lives, and
   * this type deliberately does not pretend to have made it.
   */
  readonly suggestion: Readonly<Record<string, unknown>> | null;
  /**
   * What the run said it needed when **nothing in the library provides it**.
   *
   * Separate from `suggestion` because they open different doors: one places a
   * tool that already exists, the other starts an interview to build a new,
   * workflow-scoped one (`every-workflow-green` 34). A card that cannot tell
   * the two apart cannot tell the user which is about to happen.
   */
  readonly capabilityGap: string | null;
  /**
   * What each Guardrail node removed from this run: counts and entity types,
   * **never values**.
   *
   * A redaction the machinery performs silently is its own defect for whoever
   * is debugging the answer, and showing what was removed would recreate the
   * leak in the surface people read most often. This is the middle: the
   * developer learns three emails left the answer at `guard-out`, and nobody
   * learns which three.
   */
  readonly redactions: readonly GuardrailRedaction[];
}

/** One entry of `DeveloperChannel.redactions`. There is no value field. */
export interface GuardrailRedaction {
  /** The Guardrail node that acted, by canvas id. */
  readonly node: string;
  /** `email`, `credit_card`, or whatever the policy named. */
  readonly entity: string;
  /** `redact` | `mask` | `hash` | `block`. */
  readonly strategy: string;
  readonly count: number;
}

/**
 * A run paused at a `human.approval` node instead of finishing.
 *
 * `threadId` is the only thing `resume()` needs to continue this exact run —
 * LangGraph resumes by replaying the same checkpointed thread, not by
 * resending the original request.
 */
export interface RunInterrupted {
  readonly interrupted: true;
  readonly threadId: string;
  readonly message: string;
  readonly candidate: string;
  /**
   * What the grader that produced `candidate` thought of it: `'pass'` or
   * `'revise'` (`workflow-gallery` 32). `''` when no grader produced it — the
   * server omits both this and `reason` together, and absence is a value: it
   * says no machine opinion exists, not that the machine had nothing to say.
   *
   * **The judgement, not the branch.** A grader at its attempt cap routes
   * `pass` for an answer it rejected; this field reports `revise` there,
   * which is the whole reason a person is being asked.
   */
  readonly verdict: string;
  /** The grader's sentence explaining `verdict`. `''` alongside it. */
  readonly reason: string;
  /**
   * Which deterministic check produced `verdict` without a model call
   * (`production-ready` 92), or `''` when a model formed the opinion.
   *
   * Present only when one fired, so a reviewer told "the grader asked for a
   * revision" can tell a judgement from a rule. Same fact, and the same
   * wording, as the trace row — see `graderCheckLine`.
   */
  readonly check: string;
  /**
   * The canvas node the run is parked on — the approval node itself.
   *
   * It never appears in an `update` frame, because `updates` reports a node
   * only once it *completes* and this one never did. Without this field a
   * surface can only mark the last node that reported, which is the node
   * *before* the approval — the paused ring landed one box early on `/chat`
   * before the backend started sending it. Empty when the backend predates
   * the field or the name is not a node of this canvas; callers fall back to
   * what they already knew rather than marking the wrong node.
   */
  readonly node: string;
}

/**
 * A stream the caller stopped — Stop, pressed mid-run (ticket 10).
 *
 * Deliberately an `Ok` outcome rather than an `Err`: the run did exactly what
 * it was told, so every surface renders it as a muted "Stopped by you" line
 * instead of a failure. Carries nothing, because a stopped run has no result
 * to report — whatever it streamed before the stop already reached `onEvent`.
 */
export interface RunCancelled {
  readonly cancelled: true;
}

/**
 * What a stream settles into: a finished run, one waiting on a human, or one
 * the caller stopped.
 */
export type RunOutcome = RunResult | RunInterrupted | RunCancelled;

/** Narrows a settled outcome to "the caller pressed Stop". */
export const isCancelled = (outcome: RunOutcome): outcome is RunCancelled =>
  'cancelled' in outcome && outcome.cancelled === true;

/**
 * Per-call options that are about the *transport*, not the run.
 *
 * Separate from `RunRequest` on purpose: everything in that interface is
 * serialised into the request body, and an `AbortSignal` is neither
 * serialisable nor something the backend is told about. It also keeps the
 * addition purely additive — an existing two-argument call is unchanged.
 */
export interface StreamOptions {
  /** Aborts the request and its body reader. See `RunCancelled`. */
  readonly signal?: AbortSignal;
}

export interface ResumeRequest {
  readonly threadId: string;
  readonly workflow: unknown;
  readonly decision: 'approve' | 'reject';
  readonly feedback?: string;
  readonly model?: string;
  readonly recursionLimit?: number;
  /** Same as `RunRequest.workflowSlug`: a resume must bind the same tool
   * set as the run it resumes. The backend's `ResumeRequest` declares this
   * field explicitly (it forbids unknown keys). */
  readonly workflowSlug?: string;
  /** Same as `RunRequest.credentials` — a resume re-initialises the model,
   * so it needs the same keys the run it continues had. */
  readonly credentials?: Readonly<Record<string, string>>;
  /** Same as `RunRequest.audience`. The backend's `ResumeRequest` declares
   * it explicitly (it forbids unknown keys), so a resume can carry it too —
   * and must, or an approved run comes back entitled to less than the run it
   * continues. */
  readonly audience?: 'customer' | 'developer';
}

/**
 * What one model message cost, as its provider reported it.
 *
 * The three standard counts and no more. LangChain's own `UsageMetadata`
 * carries optional per-modality breakdowns (audio, cache reads, reasoning
 * tokens) beside them, and those differ by provider — a field that is
 * sometimes there is a field a consumer cannot rely on, so none crosses.
 */
export interface TokenUsage {
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly totalTokens: number;
}

/**
 * One frame of `/api/runs/stream`'s Server-Sent-Events feed.
 *
 * `node`/`namespace`/`taskId` mirror the backend's own finding (verified
 * live against LangGraph): a `namespace` alone cannot tell two concurrently
 * `Send`-dispatched instances of the *same* worker node apart, because a
 * `Send` task shares its parent's checkpoint namespace rather than getting
 * its own — unlike an actual nested subgraph. `taskId` is what a Worker
 * node's dispatched instances carry instead, and is `null` for every other
 * node type.
 */
export type RunStreamEvent =
  | {
      readonly type: 'update';
      readonly node: string;
      readonly namespace: readonly string[];
      readonly taskId: string | null;
      /** True for steps inside a node's own compiled loop (model calls,
       * tool executions, middleware hooks) — trace-tree children, never
       * flat-feed rows. */
      readonly internal: boolean;
      readonly output: string | null;
      /**
       * The canvas node the run is *actually* inside for this frame, resolved
       * by the stream itself (ticket 01).
       *
       * `node` answers "which graph step reported"; this answers "what should
       * glow". They differ exactly when the interesting things happen: an
       * internal `model` frame of a long agent step resolves to that agent, a
       * frame from inside a mounted team resolves to the mount. Guessing it
       * client-side is what made both surfaces leave the highlight on the
       * router while a team worked.
       *
       * Falls back to `node` when the backend predates the field.
       */
      readonly activeNode: string; /**
       * Whether Stop, right now, **cancels** the node this frame names —
       * rather than merely walking away from it (`async-first/07`).
       *
       * A property of the node, not of the run: an agent can be cancellable
       * while the grader after it is not. Read the last value seen and use it
       * to word what a stopped turn says; `false` against a backend that
       * predates the field, which is the claim every run could always make.
       */
      readonly interruptible: boolean;

      /**
       * Where this frame is on **every** canvas it touches — canvas node ids
       * from the outermost document inward, one per level of nesting
       * (tickets 33/34).
       *
       * `activeNode` answers the question for the document that was *run*, and
       * that is all a top-level canvas needs. It is not enough for an editor,
       * because an editor lets you open a mount while it works — and that
       * child document contains neither `activeNode` (the mount, which is the
       * parent's card) nor `node` (which inside a mount is the compiler's
       * mangled `safe_name`, hyphens replaced, matching nothing).
       *
       * Consumed by `frameTarget`, which walks it outermost-first. Empty
       * against a backend that predates the field, and `frameTarget` then
       * falls back to the older node/owner rule.
       */
      readonly path: readonly string[];
      /**
       * Which document each `path` entry belongs to — same length, same
       * order, read by index.
       *
       * Ids are unique only within a document, and the shipped pair is the
       * counterexample: `concierge` mounts `chinook-assistant` and both have
       * `in1`, `router1` and `out1`. A consumer that knows which workflow it
       * is showing should match on this and treat "no level is me" as an
       * answer rather than a gap. An entry is `''` when the slug could not be
       * determined — "no claim", never "not you".
       */
      readonly pathSlugs: readonly string[];
      /**
       * Which deterministic check rejected this grader's candidate before any
       * model was invoked (`production-ready` 92), or `''`.
       *
       * The server omits this and `reason` together on every other frame, and
       * absence is the value: it says no deterministic check fired, which
       * covers an ordinary pass and a model's own rejection alike. Only its
       * presence is a claim — that `BaseGrader.grade` returned from
       * `deterministic_checks` and `self.model.invoke` was never reached.
       *
       * Never captioned or looked up: the marker is an open set a subclass
       * extends. `reason` is the sentence a reader is shown.
       */
      readonly check: string;
      /** The grader's sentence for `check`. `''` alongside it. */
      readonly reason: string;
    }
  | {
      readonly type: 'token';
      readonly node: string;
      readonly namespace: readonly string[];
      readonly content: string;
      /**
       * Which *kind* of text this is (ticket 23).
       *
       * A reasoning model streams its deliberation and its reply in the same
       * content list. Arriving as one frame kind, a consumer had two bad
       * choices — concatenate and render the model's private thinking as its
       * answer, or drop the thinking entirely — while reasoning effort has
       * been a per-node field all along.
       *
       * One chunk can produce **two** frames, reasoning first, because that is
       * the order it was produced in.
       *
       * Not the same question as `kind`, which says *who* produced the text. A
       * tool result is `kind: 'tool'` with `block: 'text'`.
       *
       * `'text'` against a backend that predates the field: it is the
       * overwhelming majority of frames and the only kind ever emitted before.
       */
      readonly block: 'text' | 'reasoning';
      /**
       * What this message cost, on the frame that **settles** it — `null` on
       * every other frame.
       *
       * So a non-null `usage` is also the only end-of-message signal this
       * stream has. The settling frame's `content` is usually empty, which is
       * exactly why none of this reached a consumer before: a frame with no
       * text used to be dropped on the floor.
       *
       * `null` on a customer run whatever the model reported — cost is
       * developer material, like a tool's name. There is no run total; sum
       * these if you want one.
       */
      readonly usage: TokenUsage | null;
      /**
       * The canvas node the run is inside for this frame — the same field, with
       * the same meaning, as on an `update` frame (ticket 02).
       *
       * It matters more here than there. `update` frames arrive when a node
       * *finishes*, so a highlight fed by them alone shows who last completed;
       * a token frame is the only one that arrives while a node is still
       * working. A consumer that follows this on tokens sees a mounted
       * workflow light up when it starts rather than twenty seconds later.
       *
       * Repeated on every frame, so a consumer must compare it against the node
       * it last highlighted — a single model turn is 100+ tokens and they all
       * name the same node.
       *
       * Empty against a backend that predates the field — deliberately NOT
       * falling back to `node` the way the `update` variant does. A token
       * frame's `node` is usually an inner step (`model`, `tools`, a node of a
       * mounted document) that is on no canvas, so the fallback would point the
       * highlight at something that does not exist. Empty means "this frame
       * says nothing about where the run is", and a consumer leaves the
       * highlight alone.
       */
      readonly activeNode: string; /**
       * Whether Stop, right now, **cancels** the node this frame names —
       * rather than merely walking away from it (`async-first/07`).
       *
       * A property of the node, not of the run: an agent can be cancellable
       * while the grader after it is not. Read the last value seen and use it
       * to word what a stopped turn says; `false` against a backend that
       * predates the field, which is the claim every run could always make.
       */
      readonly interruptible: boolean;

      /**
       * The same path the `update` variant carries — see its comment.
       *
       * Present here for the reason `activeNode` is: a `token` frame is the
       * only one that arrives while a node is *still working*, so a canvas fed
       * by `update` frames alone can only ever light who last finished. Inside
       * an open mount that is the whole difference between watching the run
       * and watching a static diagram, because the child's steps are exactly
       * the long ones.
       */
      readonly path: readonly string[];
      /** The documents behind `path`, read by index — see the `update`
       * variant, where the ambiguity this removes is spelled out. */
      readonly pathSlugs: readonly string[];
      /**
       * What produced this text (ticket 02).
       *
       * LangGraph's `messages` stream carries a node's *messages*, not only its
       * model tokens, so a tool's result arrives on this same frame type. A
       * consumer that cannot tell them apart concatenates a Markdown table onto
       * the tail of the model's prose and renders the pair as one document —
       * which is how an eleven-row table came out as a single wrapped line.
       *
       * `'ai'` against a backend that predates the field: model text is the
       * overwhelming majority of frames and the safer default, since it is only
       * ever rendered as reasoning.
       */
      readonly kind: 'ai' | 'tool';
      /** The tool that returned this text — empty unless `kind` is `'tool'`. */
      readonly toolName: string;
      /**
       * The `tool_call_id` this result answers — the identity a consumer folds
       * chunks on. Two consecutive calls to the *same* tool (a schema read of
       * `Invoice`, then of `InvoiceLine`) share a name and differ only here.
       */
      readonly toolCallId: string;
      /**
       * Whether this frame's text was **emptied deliberately** (ticket 10).
       *
       * A customer's stream carries the reply and not the machinery — a tool
       * payload, a branch name, a verdict, the echo of their own question are
       * all blanked — but the frame still arrives, because it is the only one
       * that says where a run is mid-node. Without this field a consumer
       * cannot tell that from a model that produced nothing, and
       * `api/audience.py` says the field exists precisely so it can.
       *
       * Always `false` on a developer run, which is why nothing here read it
       * for so long: the editor always sends `audience: 'developer'`, and
       * `audience` is public on `RunRequest` one screen up — so that was a
       * caller convention, not a guarantee. Emitted only when true, so `false`
       * covers both "there was text" and a backend that predates the field.
       */
      readonly withheld: boolean;
    }
  | {
      /**
       * A step said something about itself **while still working**.
       *
       * The third frame that can arrive mid-node, and the only one a *tool*
       * can send. `update` fires when a node completes and `token` exists only
       * while a model types, so a tool that spends forty seconds paging an API
       * produced nothing at all and the run read as stopped.
       *
       * A run whose steps say nothing emits none of these, so a consumer that
       * ignores the variant behaves exactly as it did before.
       */
      readonly type: 'progress';
      readonly node: string;
      readonly namespace: readonly string[];
      /**
       * What to show. Written by the workflow's own developer and addressed to
       * whoever is watching, so — unlike a tool's name or its payload — this
       * crosses to a customer intact.
       */
      readonly message: string;
      /**
       * How far along, when the step happens to know. `null` means **no
       * claim**, not zero: render a spinner rather than a bar until both are
       * numbers. Never a sentinel and never a non-finite number, which JSON
       * cannot carry across this seam.
       */
      readonly current: number | null;
      readonly total: number | null;
      /** The canvas node to show as running — same meaning as on `token`. */
      readonly activeNode: string; /**
       * Whether Stop, right now, **cancels** the node this frame names —
       * rather than merely walking away from it (`async-first/07`).
       *
       * A property of the node, not of the run: an agent can be cancellable
       * while the grader after it is not. Read the last value seen and use it
       * to word what a stopped turn says; `false` against a backend that
       * predates the field, which is the claim every run could always make.
       */
      readonly interruptible: boolean;

      /** The same path the other mid-node frames carry — see the `update`
       * variant, where the ambiguity it removes is spelled out. */
      readonly path: readonly string[];
      readonly pathSlugs: readonly string[];
    }
  | {
      /** A run created a child worker or subagent — the spawn *moment*,
       * emitted before the frame that revealed it. Three shapes of the same
       * event: an orchestrator's fan-out plan (`fanout`), a deep agent's
       * `task` tool call (`subagent`), and a mounted workflow starting its
       * own nested subgraph (`subgraph`). */
      readonly type: 'spawn';
      readonly kind: 'fanout' | 'subagent' | 'subgraph';
      /** The canvas node that did the spawning. */
      readonly parent: string;
      /** What to call the child: archetype, subagent type, or mounted node. */
      readonly label: string;
      /** First ~120 chars of the child's instruction, if the frame carried one. */
      readonly instruction: string;
      readonly taskId: string | null;
      readonly namespace: readonly string[];
    }
  | {
      readonly type: 'error';
      readonly detail: string;
      /**
       * The thread the failed run happened in (ticket 11's disclosure, ticket
       * 17's use). A failure is still a turn: the question reached the graph
       * and the `messages` channel may already hold it, so a client that
       * forgot the thread here would silently start a new conversation on the
       * next send. Empty against a backend that predates the field.
       */
      readonly threadId: string;
    };

/**
 * One past run, as the backend recorded it.
 *
 * "Past run", never "replay": every field here was written while the run
 * happened and is read back out of the checkpointer. Opening one calls no
 * model and no tool. The only thing that re-executes is `resume()`, and only
 * for a run whose `status` is `paused`.
 */
export interface PastRun {
  readonly threadId: string;
  readonly workflowSlug: string;
  readonly sessionId: string;
  readonly userEmail: string;
  readonly updatedAt: string;
  readonly steps: number;
  readonly question: string;
  readonly answer: string;
  /** `paused` runs can be continued with `resume()`; `finished` ones cannot. */
  readonly status: 'paused' | 'finished';
  /**
   * A node wrote the failure sentinel into `outputs` — separate from
   * `status`, which only answers whether the run is waiting on the user.
   * Never derived from an empty `answer`: a run may legitimately answer with
   * nothing (production-ready/78).
   */
  readonly failed: boolean;
}

/**
 * One tool a past run reached for, and what came back.
 *
 * Paired by the server and reported at the superstep that **asked**: LangGraph
 * writes the request in one superstep and the answer in the next, so reporting
 * them where each landed gives two half-rows to rejoin by hand.
 */
export interface PastRunToolCall {
  readonly name: string;
  /** The arguments as JSON text; `''` when the request is no longer stored. */
  readonly arguments: string;
  /** What came back; `''` means no answer was stored, not "returned nothing". */
  readonly result: string;
}

/**
 * What one superstep's model call cost, as the provider reported it.
 *
 * Read off `AIMessage.usage_metadata`, which has ridden in the checkpoints
 * since the message channel did — ticket 37 priced token counts as the half of
 * replay needing a frame table, and against the stored file that was wrong.
 *
 * This step's call, not the run's total: the message channel is cumulative, so
 * a reader that sums it charges the last row for the whole run.
 */
export interface PastRunTokens {
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly totalTokens: number;
}

/** One checkpoint of a past run: the state as it stood at that superstep. */
export interface PastRunStep {
  readonly checkpointId: string;
  readonly step: number;
  readonly at: string;
  readonly source: string;
  readonly values: Readonly<Record<string, string>>;
  /**
   * Which graph this step belongs to, outermost first; `[]` is the workflow
   * itself.
   *
   * Read the same way a live frame's `path` is. Without it a run is a flat
   * list in which `Step 3 · loop` appears once per graph, because every
   * subgraph numbers its own supersteps from `-1` — five graphs printed as one
   * graph repeating itself (`memory-and-replay` 37).
   */
  readonly namespace: readonly string[];
  /** The innermost entry of `namespace`, or `''` for the workflow itself. */
  readonly node: string;
  /**
   * The channels this superstep wrote — what *happened* here, where `values`
   * is what the state *was*.
   */
  readonly wrote: readonly string[];
  /**
   * Tools **this** superstep asked for. Not what the message channel contains:
   * the channel is cumulative and holds the whole history at every checkpoint,
   * so its contents would print every call on every row.
   */
  readonly toolCalls: readonly PastRunToolCall[];
  /**
   * How long this superstep took, in milliseconds.
   *
   * `null`, never `0`, when there was nothing to measure against — the first
   * step of a graph, an unreadable timestamp, a clock that went backwards. A
   * renderer must be able to tell *instant* from *unknown*, so it must not
   * coalesce this to zero.
   *
   * A parent superstep that dispatched a worker spans the worker's whole run,
   * because it did.
   */
  readonly durationMs: number | null;
  /** What this superstep's model call cost, or `null` if it made none. */
  readonly tokens: PastRunTokens | null;
}

export interface PastRunHistory {
  readonly run: PastRun;
  /** Oldest first, so reading top to bottom is watching the run happen. */
  readonly steps: readonly PastRunStep[];
}

export interface PastRunQuery {
  readonly workflowSlug?: string;
  readonly userEmail?: string;
  readonly sessionId?: string;
  readonly limit?: number;
}

export interface IRuntimeClient {
  run(request: RunRequest): Promise<Result<RunResult, string>>;
  /**
   * Runs the same request, but calls `onEvent` as each node acts — what lets
   * the canvas highlight whichever node is currently in charge instead of
   * only learning the outcome once the whole run has finished.
   *
   * Resolves to a `RunInterrupted` rather than a `RunResult` if the run
   * pauses at a `human.approval` node — `resume()` continues it from there.
   */
  runStream(
    request: RunRequest,
    onEvent: (event: RunStreamEvent) => void,
    options?: StreamOptions,
  ): Promise<Result<RunOutcome, string>>;
  /** Continues a paused run with a human's decision. Same outcome shape as `runStream` — a resumed run can itself pause again at a later approval node. */
  resume(
    request: ResumeRequest,
    onEvent: (event: RunStreamEvent) => void,
    options?: StreamOptions,
  ): Promise<Result<RunOutcome, string>>;
  health(): Promise<Result<{ modelConfigured: boolean }, string>>;
  /** Past runs this backend has stored, newest first. Reads only. */
  pastRuns(query?: PastRunQuery): Promise<Result<readonly PastRun[], string>>;
  /** One past run, checkpoint by checkpoint. Reads only — nothing re-executes. */
  pastRun(threadId: string, workflowSlug?: string): Promise<Result<PastRunHistory, string>>;
}

/** Injected so tests need no server and no network. */
export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

/**
 * What a stream that never said how it ended is reported as.
 *
 * The server's contract (`_stream_run`) is that every stream it can still
 * write to ends with `done`, `interrupt` or `error`. The one case no frame
 * can cover is the server's own death — a `--reload` restart, a crash, a cut
 * connection — because nothing is left to send it. **So this message is the
 * authoritative report of that case**, and it names the likely cause rather
 * than leaving a surface to guess between "finished" and "still working".
 *
 * One constant, two arrival shapes: the body can end cleanly with no terminal
 * frame, or the pending read can reject. Same fact, so the same wording.
 */
const DROPPED =
  'The runtime closed the stream without saying how it ended — the backend most likely restarted or crashed mid-run. Nothing was saved from this run; ask again.';

const describeError = (error: unknown): string => {
  const message = (error as { message?: unknown } | null)?.message;
  return typeof message === 'string' && message !== '' ? ` (${message})` : '';
};

/**
 * One paint, or the closest this module gets to one.
 *
 * `requestAnimationFrame` in a browser — the actual thing a narration line
 * needs, a chance for the screen to update before the next frame's state
 * overwrites it. `core/` also runs under Vitest's node environment, which has
 * no `requestAnimationFrame`, so this falls back to a macrotask (`setTimeout`)
 * there: still a real yield of the event loop, just not tied to a screen.
 */
const yieldToPaint = (): Promise<void> =>
  new Promise((resolve) => {
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => resolve());
    } else {
      setTimeout(resolve, 0);
    }
  });

/**
 * The body every run-shaped request sends.
 *
 * One builder because there were three, and the copies were not equally
 * tested: `RuntimeClient.run` had assertions for every key — `audience`,
 * `workflow_slug`, `recursion_limit`, `credentials` — while `runStream`, the
 * door **both shipped UIs actually use**, had one. `run` has no product
 * caller at all (reviews-2026-08-14 ticket 02).
 *
 * So dropping a key from the stream body could not fail a test, while the
 * editor silently lost its tool registry or its developer channel. With one
 * builder there is one thing to get right and one thing to test.
 */
function runBody(request: {
  model?: string;
  recursionLimit?: number;
  workflowSlug?: string;
  credentials?: Readonly<Record<string, string>>;
  audience?: string;
}): Record<string, unknown> {
  return {
    ...(request.model ? { model: request.model } : {}),
    ...(request.recursionLimit != null ? { recursion_limit: request.recursionLimit } : {}),
    ...(request.workflowSlug ? { workflow_slug: request.workflowSlug } : {}),
    ...(request.credentials ? { credentials: request.credentials } : {}),
    ...(request.audience ? { audience: request.audience } : {}),
  };
}

export class RuntimeClient implements IRuntimeClient {
  constructor(
    private readonly baseUrl: string = runtimeBaseUrl(),
    private readonly fetchImpl: FetchLike = (url, init) => fetch(url, init),
  ) {
    this.mcp = new McpRegistryClient(baseUrl, fetchImpl);
  }

  /**
   * Which MCP servers this project can bind, and whether one answers.
   *
   * A collaborator rather than four more methods here — CLAUDE.md's rule for
   * a class at its ceiling, and the honest split besides: the run seam and a
   * project-level registry change for different reasons.
   */
  readonly mcp: McpRegistryClient;

  /**
   * The base said out loud. Same-origin resolves to an empty prefix, which is
   * exactly right in a URL and meaningless in a sentence.
   */
  private unreachable(): string {
    return `Could not reach the runtime at ${describeRuntimeBase(this.baseUrl)}. Is the backend running?`;
  }

  async run(request: RunRequest): Promise<Result<RunResult, string>> {
    const body = {
      workflow: request.workflow,
      question: request.question,
      ...runBody(request),
      ...(request.threadId ? { thread_id: request.threadId } : {}),
    };

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/runs`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch {
      // The single most likely failure in development, so it gets the message
      // that actually helps rather than a bare "Failed to fetch".
      return Err(this.unreachable());
    }

    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const developer = asDeveloperChannel(payload['developer']);
      return Ok({
        // `RunResponse` does not carry one today; see `RunResult.threadId`.
        threadId: asString(payload['thread_id']),
        answer: asString(payload['answer']),
        decisions: asRecord(payload['decisions']),
        outputs: asRecord(payload['outputs']),
        nested: {
          outputs: asRecord(
            (payload['nested'] as Record<string, unknown> | undefined)?.['outputs'],
          ),
          decisions: asRecord(
            (payload['nested'] as Record<string, unknown> | undefined)?.['decisions'],
          ),
        },

        attempts: typeof payload['attempts'] === 'number' ? payload['attempts'] : 0,
        mermaid: asString(payload['mermaid']),
        publishedRejected: payload['published_rejected'] === true,
        developer,
        warnings: developer ? developer.warnings : [],
      });
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async runStream(
    request: RunRequest,
    onEvent: (event: RunStreamEvent) => void,
    options?: StreamOptions,
  ): Promise<Result<RunOutcome, string>> {
    const body = {
      workflow: request.workflow,
      question: request.question,
      ...runBody(request),
      ...(request.threadId ? { thread_id: request.threadId } : {}),
    };
    return this.streamFrom(`${this.baseUrl}/api/runs/stream`, body, onEvent, options);
  }

  async resume(
    request: ResumeRequest,
    onEvent: (event: RunStreamEvent) => void,
    options?: StreamOptions,
  ): Promise<Result<RunOutcome, string>> {
    const body = {
      thread_id: request.threadId,
      workflow: request.workflow,
      decision: request.decision,
      ...(request.feedback ? { feedback: request.feedback } : {}),
      ...runBody(request),
    };
    return this.streamFrom(`${this.baseUrl}/api/runs/resume`, body, onEvent, options);
  }

  private async streamFrom(
    url: string,
    body: unknown,
    onEvent: (event: RunStreamEvent) => void,
    options?: StreamOptions,
  ): Promise<Result<RunOutcome, string>> {
    const signal = options?.signal;
    /**
     * True for both spellings of "the caller stopped this": the signal is
     * already aborted, or the rejection is a fetch/stream `AbortError`. Both
     * checked, because which one a runtime raises depends on *when* the abort
     * landed relative to the request, and a stop must never be reported as
     * "is the backend running?".
     */
    const wasAborted = (error: unknown): boolean =>
      signal?.aborted === true || (error as { name?: string } | null)?.name === 'AbortError';

    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
        ...(signal ? { signal } : {}),
      });
    } catch (error) {
      if (wasAborted(error)) return Ok({ cancelled: true });
      return Err(this.unreachable());
    }

    if (!response.ok) return Err(await describeFailure(response));
    if (!response.body) return Err('The runtime did not stream a response body.');

    // SSE, not JSON: frames arrive as `event: <name>\ndata: <json>\n\n`, and
    // a frame can straddle two chunk boundaries, so this buffers text and
    // only parses complete frames (split on the blank-line terminator).
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let outcome: RunOutcome | null = null;
    let failure: string | null = null;

    const consumeFrame = (frame: string): void => {
      let eventName = '';
      let dataLine = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) eventName = line.slice('event: '.length);
        else if (line.startsWith('data: ')) dataLine = line.slice('data: '.length);
      }
      if (eventName === '' || dataLine === '') return;

      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(dataLine) as Record<string, unknown>;
      } catch {
        return;
      }

      if (eventName === 'update') {
        onEvent({
          type: 'update',
          node: asString(payload['node']),
          namespace: Array.isArray(payload['namespace']) ? payload['namespace'].map(asString) : [],
          taskId: typeof payload['taskId'] === 'string' ? payload['taskId'] : null,
          internal: payload['internal'] === true,
          output: typeof payload['output'] === 'string' ? payload['output'] : null,
          activeNode: asString(payload['activeNode']) || asString(payload['node']),
          // Emitted as a real boolean, so anything else — including a backend
          // that predates the field — reads as "not cancellable".
          interruptible: payload['interruptible'] === true,
          path: asPath(payload['path']),
          pathSlugs: asPath(payload['pathSlugs'], { keepBlanks: true }),
          check: asString(payload['check']),
          reason: asString(payload['reason']),
        });
      } else if (eventName === 'progress') {
        onEvent({
          type: 'progress',
          node: asString(payload['node']),
          namespace: Array.isArray(payload['namespace']) ? payload['namespace'].map(asString) : [],
          message: asString(payload['message']),
          // `null` unless the backend sent an actual number: a step that does
          // not know how far along it is must not be rendered as being at 0.
          current: typeof payload['current'] === 'number' ? payload['current'] : null,
          total: typeof payload['total'] === 'number' ? payload['total'] : null,
          activeNode: asString(payload['activeNode']),
          interruptible: payload['interruptible'] === true,
          path: asPath(payload['path']),
          pathSlugs: asPath(payload['pathSlugs'], { keepBlanks: true }),
        });
      } else if (eventName === 'spawn') {
        const kind = asString(payload['kind']);
        onEvent({
          type: 'spawn',
          kind: kind === 'fanout' || kind === 'subagent' ? kind : 'subgraph',
          parent: asString(payload['parent']),
          label: asString(payload['label']),
          instruction: asString(payload['instruction']),
          taskId: typeof payload['taskId'] === 'string' ? payload['taskId'] : null,
          namespace: Array.isArray(payload['namespace']) ? payload['namespace'].map(asString) : [],
        });
      } else if (eventName === 'token') {
        const tool = asRecord(payload['tool']);
        const usage = payload['usage'];
        onEvent({
          type: 'token',
          node: asString(payload['node']),
          namespace: Array.isArray(payload['namespace']) ? payload['namespace'].map(asString) : [],
          content: asString(payload['content']),
          // `'text'` unless the backend said otherwise — the safe default,
          // and what every frame was before the field existed.
          block: payload['block'] === 'reasoning' ? 'reasoning' : 'text',
          // Present only on the frame that settles a message, so `null` here
          // is the common case rather than a failure to parse.
          usage: usage && typeof usage === 'object' ? asTokenUsage(usage) : null,
          activeNode: asString(payload['activeNode']),
          interruptible: payload['interruptible'] === true,
          path: asPath(payload['path']),
          pathSlugs: asPath(payload['pathSlugs'], { keepBlanks: true }),
          kind: payload['kind'] === 'tool' ? 'tool' : 'ai',
          toolName: asString(tool['name']),
          toolCallId: asString(tool['callId']),
          // Emitted only when true, so its absence is "there was text" — the
          // same shape the backend uses, and what a pre-field backend sends.
          withheld: payload['withheld'] === true,
        });
      } else if (eventName === 'error') {
        failure = asString(payload['detail']) || 'The workflow failed while streaming.';
        onEvent({ type: 'error', detail: failure, threadId: asString(payload['threadId']) });
      } else if (eventName === 'interrupt') {
        outcome = {
          interrupted: true,
          threadId: asString(payload['threadId']),
          message: asString(payload['message']),
          candidate: asString(payload['candidate']),
          verdict: asString(payload['verdict']),
          reason: asString(payload['reason']),
          check: asString(payload['check']),
          node: asString(payload['node']),
        };
      } else if (eventName === 'done') {
        const developer = asDeveloperChannel(payload['developer']);
        outcome = {
          threadId: asString(payload['threadId']),
          answer: asString(payload['answer']),
          decisions: asRecord(payload['decisions']),
          outputs: asRecord(payload['outputs']),
          nested: {
            outputs: asRecord(
              (payload['nested'] as Record<string, unknown> | undefined)?.['outputs'],
            ),
            decisions: asRecord(
              (payload['nested'] as Record<string, unknown> | undefined)?.['decisions'],
            ),
          },

          attempts: typeof payload['attempts'] === 'number' ? payload['attempts'] : 0,
          mermaid: asString(payload['mermaid']),
          publishedRejected: payload['publishedRejected'] === true,
          developer,
          warnings: developer ? developer.warnings : [],
        };
      }
    };

    try {
      for (;;) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const wasProgress = frame.startsWith('event: progress');
          consumeFrame(frame);
          boundary = buffer.indexOf('\n\n');
          // `launch-readiness/105`: a tool's narration is real and reaches
          // this loop, but a fast tool (measured: 66ms) reports its whole
          // before/after story inside one network chunk — several `progress`
          // frames arrive here in the same synchronous pass, before React (or
          // a person watching) ever gets a paint between them. Left alone,
          // this loop drains the whole chunk and only the *last* state update
          // survives to be seen — which is indistinguishable from the line
          // never having arrived, and is exactly what a live poll measured.
          // Yielding one paint after a `progress` frame, but only when
          // another frame is already queued behind it, costs nothing on the
          // common case (one frame per chunk) and turns a blip nobody could
          // see into a line that was genuinely displayed.
          if (wasProgress && boundary !== -1) {
            await yieldToPaint();
          }
        }
      }
    } catch (error) {
      if (wasAborted(error)) {
        // Stopped. Cancelling the reader is what actually closes the HTTP
        // connection, and closing it is what makes the *server's* generator
        // exit — so this line is the whole client half of "Stop stops work".
        // Swallowed: cancelling an already-errored stream rejects, and that
        // rejection carries no information a caller could act on.
        await reader.cancel().catch(() => undefined);
        return Ok({ cancelled: true });
      }
      // The socket died mid-stream — how a killed or reloaded backend usually
      // arrives, since the pending `read()` rejects rather than resolving.
      // Settled as a failure rather than rethrown: this used to propagate out
      // of `runStream` past callers that only `await` the `Result`, leaving a
      // turn stuck on "Running…" with nothing to end it. Same fact and same
      // wording as the no-terminal-frame case below; the raw error rides
      // along so a genuine bug is still legible.
      await reader.cancel().catch(() => undefined);
      return Err(`${DROPPED}${describeError(error)}`);
    }

    if (failure) return Err(failure);
    if (outcome) return Ok(outcome);
    // A stop does not always arrive as a thrown `AbortError`: cancelling a
    // reader can instead resolve the pending read with `done: true`, which
    // looks exactly like a server that hung up early. Found live — the loop
    // exited cleanly and the surface reported "closed the stream without
    // reporting a result", turning the user's own Stop into an error. The
    // signal is the only thing that can tell the two apart, and it is
    // checked last so a real `done` frame still wins.
    if (signal?.aborted) return Ok({ cancelled: true });
    return Err(DROPPED);
  }

  async pastRuns(query: PastRunQuery = {}): Promise<Result<readonly PastRun[], string>> {
    const params = new URLSearchParams();
    if (query.workflowSlug) params.set('workflow_slug', query.workflowSlug);
    if (query.userEmail) params.set('user_email', query.userEmail);
    if (query.sessionId) params.set('session_id', query.sessionId);
    if (query.limit != null) params.set('limit', String(query.limit));
    const suffix = params.size > 0 ? `?${params.toString()}` : '';

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/threads${suffix}`);
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const rows = Array.isArray(payload['threads']) ? payload['threads'] : [];
      return Ok(rows.map((row) => asPastRun(asRecordOfUnknown(row))));
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async pastRun(threadId: string, workflowSlug?: string): Promise<Result<PastRunHistory, string>> {
    const suffix = workflowSlug ? `?workflow_slug=${encodeURIComponent(workflowSlug)}` : '';
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/threads/${encodeURIComponent(threadId)}${suffix}`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (response.status === 404) return Err(`No stored run for thread ${threadId}`);
    if (!response.ok) return Err(await describeFailure(response));
    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const steps = Array.isArray(payload['steps']) ? payload['steps'] : [];
      return Ok({
        run: asPastRun(asRecordOfUnknown(payload['thread'])),
        steps: steps.map((step) => {
          const row = asRecordOfUnknown(step);
          return {
            checkpointId: asString(row['checkpoint_id']),
            step: typeof row['step'] === 'number' ? row['step'] : 0,
            at: asString(row['at']),
            source: asString(row['source']),
            values: asRecord(row['values']),
            // `keepBlanks: false` — unlike `pathSlugs`, a namespace has no
            // "no claim" entry to preserve: the backend drops empty segments
            // before publishing, so a blank here is malformed rather than
            // meaningful.
            namespace: asPath(row['namespace']),
            node: asString(row['node']),
            wrote: asPath(row['wrote']),
            toolCalls: (Array.isArray(row['tool_calls']) ? row['tool_calls'] : []).map((call) => {
              const entry = asRecordOfUnknown(call);
              return {
                name: asString(entry['name']),
                arguments: asString(entry['arguments']),
                result: asString(entry['result']),
              };
            }),
            // `?? null` and never `?? 0`: the server withholds a duration it
            // could not measure, and a client that defaults it to zero
            // reinstates exactly the claim the server declined to make.
            durationMs: typeof row['duration_ms'] === 'number' ? row['duration_ms'] : null,
            tokens: asTokens(row['tokens']),
          };
        }),
      });
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * Which providers **the server** is configured for.
   *
   * Names and booleans only — the endpoint never sends key material, not even
   * masked, so nothing here can render one. What comes back is which variable
   * did it, which is the fact a person can act on.
   *
   * Presence, not validity: a key can be set, well-formed and rejected for
   * want of credit. `configured` means "this server has what it needs to try".
   */
  async providers(): Promise<Result<ProviderStatusList, string>> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/api/providers`);
      if (!response.ok) return Err(`Could not read providers (${response.status})`);
      const body = (await response.json()) as Record<string, unknown>;
      const rows = Array.isArray(body['providers']) ? body['providers'] : [];
      return Ok({
        rows: (rows as Record<string, unknown>[]).map((row) => ({
          name: String(row['name'] ?? ''),
          label: String(row['label'] ?? ''),
          configured: row['configured'] === true,
          configuredBy: typeof row['configured_by'] === 'string' ? row['configured_by'] : null,
          envVars: Array.isArray(row['env_vars']) ? row['env_vars'].map(String) : [],
          installed: row['installed'] === true,
          installHint: typeof row['install_hint'] === 'string' ? row['install_hint'] : '',
          extra: typeof row['extra'] === 'string' ? row['extra'] : '',
          keyHint: typeof row['key_hint'] === 'string' ? row['key_hint'] : null,
        })),
        environment: typeof body['environment'] === 'string' ? body['environment'] : '',
        runReadiness: typeof body['run_readiness'] === 'string' ? body['run_readiness'] : '',
      });
    } catch {
      return Err('Could not reach the runtime');
    }
  }

  /**
   * Make one real call to a provider and report what came back.
   *
   * `configured` says a variable is set; this says it *works*, and the gap is
   * where the confusing failures live — a key can be set, well-formed and
   * rejected for want of credit. Costs money and latency, so it is only ever
   * called when somebody presses the button.
   */
  async verifyProvider(name: string): Promise<Result<{ ok: boolean; detail: string }, string>> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/api/providers/${name}/verify`, {
        method: 'POST',
      });
      if (!response.ok) return Err(`Could not verify ${name} (${response.status})`);
      const payload = (await response.json()) as Record<string, unknown>;
      return Ok({
        ok: payload['ok'] === true,
        detail: typeof payload['detail'] === 'string' ? payload['detail'] : '',
      });
    } catch {
      return Err('Could not reach the runtime');
    }
  }

  async health(): Promise<Result<{ modelConfigured: boolean }, string>> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/api/health`);
      if (!response.ok) return Err(`Runtime is unhealthy (${response.status})`);
      const payload = (await response.json()) as Record<string, unknown>;
      return Ok({ modelConfigured: payload['model_configured'] === true });
    } catch {
      return Err('Runtime is not reachable');
    }
  }
}

function asRecordOfUnknown(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

/** A `token` frame's `usage` object, with a missing count read as zero. */
function asTokenUsage(value: unknown): TokenUsage {
  const row = asRecordOfUnknown(value);
  const count = (key: string): number => (typeof row[key] === 'number' ? row[key] : 0);
  return {
    inputTokens: count('inputTokens'),
    outputTokens: count('outputTokens'),
    totalTokens: count('totalTokens'),
  };
}

/**
 * A usage block, or `null`.
 *
 * Absent means *no model was called here*, which is a different fact from
 * *a call that cost nothing* — so a missing block never becomes a zeroed one.
 */
function asTokens(value: unknown): PastRunTokens | null {
  if (value === null || value === undefined) return null;
  const row = asRecordOfUnknown(value);
  const count = (key: string): number => (typeof row[key] === 'number' ? row[key] : 0);
  return {
    inputTokens: count('input_tokens'),
    outputTokens: count('output_tokens'),
    totalTokens: count('total_tokens'),
  };
}

function asPastRun(row: Record<string, unknown>): PastRun {
  return {
    threadId: asString(row['thread_id']),
    workflowSlug: asString(row['workflow_slug']),
    sessionId: asString(row['session_id']),
    userEmail: asString(row['user_email']),
    updatedAt: asString(row['updated_at']),
    steps: typeof row['steps'] === 'number' ? row['steps'] : 0,
    question: asString(row['question']),
    answer: asString(row['answer']),
    // Anything the backend has not promised is treated as finished: offering
    // a Resume button for a run that cannot be resumed is the worse mistake.
    status: row['status'] === 'paused' ? 'paused' : 'finished',
    failed: row['failed'] === true,
  };
}

/**
 * Turns an error status into something a developer can act on.
 *
 * Each of these is a distinct, likely situation with a distinct fix, so
 * collapsing them into one message would waste the information the server sent.
 */
export async function describeFailure(response: Response): Promise<string> {
  const detail = await readDetail(response);
  if (response.status === 503) {
    return detail || 'No model is configured on the runtime.';
  }
  if (response.status === 422) {
    return detail || 'The runtime rejected the workflow or question as invalid.';
  }
  if (response.status === 502) {
    if (detail === '') return 'The workflow failed while running.';
    // A provider's own 5xx is transient far more often than it is a bug in the
    // workflow — observed once from Ollama cloud on a request that succeeded on
    // the next attempt. Saying "try again" is more useful than surfacing a raw
    // `ResponseError: Internal Server Error` and implying the workflow is broken.
    if (/\b5\d\d\b|internal server error/i.test(detail)) {
      return `The model provider returned an error — this is usually transient, so try again. (${detail})`;
    }
    return detail;
  }
  return detail || `The runtime returned ${response.status}`;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    const detail = payload.detail;
    if (typeof detail === 'string') return detail;
    // FastAPI's 422 detail is an array of field errors; summarise rather than
    // dumping the structure into a toast.
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item as { msg?: string }).msg ?? '')
        .filter(Boolean)
        .join('; ');
    }
    return '';
  } catch {
    return '';
  }
}

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

/**
 * A frame's `path` or `pathSlugs`, defensively: strings only.
 *
 * Empty for a server that predates the fields, which is exactly what
 * `frameTarget` treats as "no answer here" before falling back to the older
 * node/owner rule — so an old runtime and a new editor still agree.
 *
 * `keepBlanks` is for `pathSlugs`, and it is load-bearing rather than lenient:
 * the two arrays are read **by index**, so dropping an unnameable level would
 * silently shift every slug onto the wrong node. A blank there means "this
 * level could not be named", which `frameTarget` handles explicitly.
 */
const asPath = (value: unknown, options?: { keepBlanks?: boolean }): readonly string[] => {
  if (!Array.isArray(value)) return [];
  const strings = value.filter((step): step is string => typeof step === 'string');
  return options?.keepBlanks === true ? strings : strings.filter((step) => step.trim() !== '');
};

const asRecord = (value: unknown): Record<string, string> => {
  if (typeof value !== 'object' || value === null) return {};
  const out: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) out[key] = asString(item);
  return out;
};

/**
 * The `developer` object of a `done` frame, or `null` when there was none.
 *
 * Absence is the customer case and is preserved as `null` rather than
 * flattened into an empty channel — see `RunResult.developer`. A malformed
 * value is also `null`: a client that cannot read the channel has no channel,
 * which is the safe reading of a payload it does not understand.
 */
function asDeveloperChannel(value: unknown): DeveloperChannel | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const suggestion = record['suggestion'];
  const capabilityGap = record['capabilityGap'];
  const redactions = record['redactions'];
  return {
    warnings: Array.isArray(record['warnings']) ? record['warnings'].map(asString) : [],
    suggestion:
      typeof suggestion === 'object' && suggestion !== null && !Array.isArray(suggestion)
        ? (suggestion as Record<string, unknown>)
        : null,
    capabilityGap: typeof capabilityGap === 'string' ? capabilityGap : null,
    // Copied field by field rather than cast: this is a hand mirror of a
    // Pydantic model, and a row the backend later widens must not arrive here
    // carrying something this type promises it never holds.
    redactions: Array.isArray(redactions)
      ? redactions
          .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
          .map((row) => ({
            node: asString(row['node']),
            entity: asString(row['entity']),
            strategy: asString(row['strategy']),
            count: typeof row['count'] === 'number' ? row['count'] : 0,
          }))
      : [],
  };
}
