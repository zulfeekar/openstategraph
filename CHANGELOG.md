# Changelog

## 0.3.0 — unreleased

Packaging OpenStateGraph as a framework somebody else can install: an honest
install footprint, a declared public surface, and a document version that is
finally read by code. Wayfinder tickets 02–04;
`docs/decisions/framework-packaging.md` is the reasoning.

### Changed — breaking

- **An error knows how it reads.** `OpenStateGraphError` gains
  `developer_message()` and `customer_message()`, and the new
  `CredentialError` groups `MissingProviderKey` with its sibling
  `ProviderRefusedCredential` — *not set* and *set but wrong* need opposite
  actions from the reader, so `except CredentialError` is the one handler for
  "a key problem". `MissingProviderKey`'s declared bases move from
  `(OpenStateGraphError, RuntimeError)` to `(CredentialError)`, which inherits
  both, so `except RuntimeError` and `except OpenStateGraphError` keep working;
  a test asserts it.

  This replaces a type switch. Each surface asked *what kind of error is this*
  and then asked a different module for a string, which is two audiences ×
  every error type as a matrix maintained by editing call sites. The base
  class answers both questions now, `customer_message()` defaults to a generic
  sentence so a new error type cannot leak a variable name by forgetting to
  override anything, and a vendor's exception is translated into the hierarchy
  once at the edge (`chat_model.credential_error_from`, which returns an error
  rather than a string).

  There is deliberately **no `IError` protocol** above the base. Python's
  `except` accepts only classes deriving from `BaseException` — `except
  SomeProtocol` raises `TypeError` — so such an interface would be unbindable
  rather than merely leaky, the same reason `CLAUDE.md` gives for refusing
  `IOrchestrator`. `OpenStateGraphError` *is* the interface.

- **Ollama takes its configuration from the environment, and is no longer the
  zero-configuration fallback.** It now declares
  `env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST")`, and because `is_configured`
  takes *any* of them, there are two supported setups and they coexist:
  `OLLAMA_API_KEY` alone reaches the cloud, `OLLAMA_HOST` alone reaches a
  daemon you run, which needs no key of ours because it owns its own auth.
  Only "neither set" changes: that used to report ready and now does not.

  What was removed was never keyless, it was **ambient** — the cloud was
  reached through a local daemon signing with `~/.ollama/id_ed25519`, a
  credential that never passes through the environment and cannot be seen,
  moved or revoked from one. It was also, on the machine where this was
  found, not running at all, while `/api/health` reported
  `model_configured: true` unconditionally.

  `ProviderSpec` gains `endpoint_env` and `default_endpoint` (additive, both
  defaulted). Ollama declares `("OLLAMA_HOST", "OLLAMA_ENDPOINT")` and
  `https://ollama.com`, so precedence is tuple order: your host, else the
  cloud endpoint, else the cloud. Previously nothing passed an endpoint at
  all and `ollama.Client` defaulted to `127.0.0.1:11434` — "Ollama means
  cloud, never local" was being violated by omission rather than by decision.
  Anthropic and OpenAI declare neither and are passed no `base_url`: their own
  SDKs already read `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL`/`OPENAI_API_BASE`.

  New internal module `openstategraph/chat_model.py` is now the single place a
  model string becomes a model, carrying the credential gate, the endpoint and
  the extras hint. Those lived in `loader.py` only, so the HTTP, MCP and
  per-node paths raised the vendor SDK's error instead of ours; a test parses
  the package for direct `init_chat_model` calls to keep it that way.

  An unconfigured provider yields a stand-in that raises `MissingProviderKey`
  on **first use** rather than at construction, so a workflow with no
  model-calling node still runs with no credentials at all.

- **`.env` values no longer keep their trailing `# comment`.** A quoted value
  ends at its closing quote; unquoted, a comment must be preceded by
  whitespace, so a `#` inside a credential survives. Found because a real
  `.env` line — `OLLAMA_ENDPOINT = "https://ollama.com"  # Adjust if needed` —
  arrived with the quotes and the comment attached, silently wrong rather than
  absent.

- **One Chinook workflow, with the router inline. `chinook-nl-to-sql` is
  deleted.** There were two Chinook documents — `chinook-assistant`, which had
  the five-intent router, and a hidden `chinook-nl-to-sql`, which did not —
  and the analyst was reached through a `workflow.subgraph` mount. The editor
  seeded a hand-built copy of the *routerless* one, so the graph a first-time
  reader opened was not the graph anyone was discussing.

  `workflows/chinook-assistant/` is now the only Chinook package. It absorbed
  the analyst's `tools/`, `data/`, `knowledge/`, `evals/`, `tests/`,
  `graph.py` and `agents.py`, and its document went from 8 nodes to 13: the
  agent, its three SQL tools and its grader's `revise` loop are the
  `data_query` branch rather than a mount. `pytest.ini`, the `Dockerfile`,
  `scripts/dev.sh`, `scripts/fetch_chinook.sh`, `scripts/clean_install_proof.sh`,
  `CONTRIBUTING.md`, `README.md`, `THIRD_PARTY_NOTICES.md`, `site/index.html`
  and `docs/**` all point at the surviving path.

  Two things the collapse removed, both duplication rather than behaviour:
  the analyst's prompt no longer opens by teaching it that "hello" is not a
  database question (a router already decided), and the grader no longer
  carries a second copy of that same test under `replace` — it `extend`s the
  built-in criteria and speaks only about this branch.

  **Recorded cost:** no *visible* example demonstrates composition any more.
  The hidden `concierge` still mounts — it now mounts `chinook-assistant` and
  `workflow-architect` — and `backend/tests/test_the_one_example.py` asserts
  both halves: the gateway still has two mounts, and no listed workflow has
  any. The concierge's own note that it deliberately mounted the *analyst* to
  avoid classifying twice is superseded; the second classification is now
  real and accepted at one cheap model call.

- **The editor seeds the shipped document instead of rebuilding it.**
  `src/app/seedDemo.ts` used to hand-write a Chinook showcase node by node.
  It now imports `workflows/chinook-assistant/workflow.json` and loads it
  through `controller.document.importJSON`, the same path an explicit Load
  and the autosave restore take. The hand-built seed was a third copy of
  knowledge that already had a single source of truth, and it is what made
  the routerless graph the one people saw.

- **A stock Agent and a stock Router now ship rules.** `AbstractAgentNode`
  and `BaseRouter` declare a `DEFAULT_RULES` ClassVar, and `BaseRouter`
  gained the `.with_defaults()` call it never had — `docs/decisions/skill-layer.md`
  described three rules layers for all five model-driven families and those
  two had only two. The bar is the owner's: an Agent dropped on a blank
  canvas, nothing typed and nothing wired, must still behave; an agent with
  no rules at all is the state that let a tool-holding agent answer a
  database question out of parametric memory.

  **Behaviour change:** `ReactAgentNode.resolve_prompt()` no longer returns
  `None` when nothing is configured, so `create_agent` always receives a
  `system_prompt`. The `None` path survives for a tier that deliberately
  blanks `DEFAULT_RULES`, and is pinned by a test. The rules are about
  honesty and tool discipline only — anything domain-shaped on a base class
  reaches every agent in every workflow and a subclass could only append to
  it.

- **`criteriaMode` is gone from everything this repository ships.**
  `workflows/**` and `backend/openstategraph/templates/**` now spell it
  `rulesMode`, and — the one that actually mattered —
  `workflows/workflow-architect/skills/document-grammar.md` no longer
  *teaches the model to emit it*. Left alone, every workflow the Architect
  generated would have carried the deprecated field forever and the
  backend's compatibility `or` would have become a permanent second
  spelling. The backend fallback stays: a user's saved document is not in
  this tree, so "no saved document carries it" is not a condition anything
  here can check.

### Changed — breaking

- **The instance default is elected from what is installed, in one place**
  (install-experience T2). `resolve_model(None)` and
  `ProviderCatalogue.default_spec()` were two implementations of one rule and
  they **disagreed on the same machine** — `ollama:gpt-oss:120b-cloud` versus
  `None` — with the carefully-reasoned copy, `default_spec`, having no
  production caller at all. Neither asked `is_installed()`, so both could elect
  a provider that cannot be imported: an `[openai]` install with a stale
  `ANTHROPIC_API_KEY` exported by another tool elected Anthropic and then told
  the reader to `pip install 'openstategraph[anthropic]'`.

  `default_spec()` is replaced by `ProviderCatalogue.elected_default()`, which
  returns the new `ProviderDefault` — the provider, the model string, whether
  it is configured, and the **reason**, because `openstategraph providers`
  prints it. `is_installed()` is candidacy (a hard filter), `is_configured()`
  is the election, registration order is the tiebreak, and a provider that is
  installed but has no key yet still wins: the extra chose the vendor, so the
  one remaining wall names *their* variable instead of listing three
  strangers. The rule `default_spec` carried — a configured provider beats a
  keyless one whatever the order — is kept, not collapsed.

  Two things are **deleted rather than narrowed**: the "keyless fallback" branch
  (unreachable since providers-and-credentials 02 made all three providers
  require a key) and the terminal `OLLAMA_CLOUD_MODEL` literal that named Ollama
  whatever you had installed. With no integration installed at all,
  `resolve_model` now raises the new `errors.NoProviderInstalled` instead of
  returning a model name nobody can call. `OLLAMA_CLOUD_MODEL` stays exported;
  nothing reaches Ollama by *not* choosing any more.

### Added

- **The default is shown rather than guessed at** (install-experience T3).
  `openstategraph providers` gains a `default:` line naming the elected model
  *and the reason* — "the only provider integration installed, and it is
  configured", or "2 integrations installed and configured (anthropic, openai);
  the first registered wins. Pin one with default_model: in
  openstategraph.yaml" — and marks the elected row `(default)`. That command's
  docstring already said the honest answer to *"why is it not using my key"* is
  a list; the list was missing which one won.

  `openstategraph serve` gains `startup_facts()`, printed in the pre-bind block
  beside the two existing refusals: the default model and the resolved
  workflows root. A message printed after a server is listening is a message
  someone scrolls past.

- **A bare provider prefix is a shorthand, and now it resolves** (workflow-gallery
  ticket 12, install-experience T1). `settings.model: "ollama:"` — the spelling
  the gallery catalogue specified, on the stated belief that it resolved to the
  cloud default — reached `init_chat_model` verbatim, and the run died at the
  first model-driven node on *"String should have at least 1 character"*, as a
  node **warning**, so the CLI exited 0 with an empty answer.

  `api.model_resolution.expand_model_reference` now owns how a model reference
  is spelled: `"ollama:"` and `"ollama"` become `ollama:gpt-oss:120b-cloud`,
  `"claude:"` becomes `anthropic:claude-haiku-4-5`, and expansion goes through
  `ProviderSpec.model_string()` so no second table of defaults exists.

  A prefix with an **empty** model name that nothing registered is refused by
  the new `errors.UnknownProvider`, which names it and lists the prefixes that
  do exist. An **unprefixed** model name is deliberately *not* refused —
  `init_chat_model` resolves an unambiguous one itself (`"gpt-5.5"` → OpenAI),
  and refusing it would put back the narrowing `providers.py` was written to
  remove.

- **A Guardrail node, and the guardrail ladder behind it** (guardrails tickets
  01–04). `openstategraph.abc` gains `IGuardrail`, `BaseGuardrail`,
  `Guardrail`, `GuardrailRule`, `Redaction` and `Screening`; the editor gains
  a `guard.policy` node type that compiles to a real state-transforming graph
  step plus a conditional edge — `allowed` continues, `blocked` takes its own
  wire to an Output carrying a refusal.

  Every detector and all four transforming strategies are **LangChain's own**,
  reached through the public `RedactionRule`; this project writes no PII regex.
  `pass` is a fifth strategy and is ours, because on a canvas an entity nobody
  wrote a rule for and an entity somebody deliberately allowed must not look
  the same: a user gives an email address to look up a customer, so email
  *inbound* passes while the same email *outbound* is redacted. The unit of
  policy is `entity × direction`, and **direction is where you put the node**,
  never a setting — there is no `applyToInput`/`applyToOutput` control.

  A new `redactions` state key carries what each guardrail did as
  `{entity, strategy, count}`. Counts and entity types, never values, and
  `DeveloperChannelResponse` gains a `redactions` field to publish them —
  the developer learns three emails left the answer, and the customer
  learns nothing, because a redaction that shows its work is not one.

- **`[bastion]` — prompt-injection screening, opt-in and never in `[all]`**
  (guardrails ticket 04, `docs/decisions/injection-screening.md`). A workflow
  asks for it with `settings.injectionScreening`; the compiler fills the
  `injection-screening` slot — first in `AbstractAgentNode.SLOT_ORDER`,
  because `before_*` hooks run first to last — on every agent in the
  document.

  It is out of `[all]` deliberately: `bastion-prompt-protection` is
  AGPL-3.0-or-later, and an adopter who typed the convenient install line
  would be taking a licence position they never chose. It also brings a local
  ONNX model (`onnxruntime`, `huggingface-hub`, `numpy`, `tokenizers`) into a
  four-package dependency floor. Asked for and absent, the run proceeds and
  the developer channel names the exact pip command in one line.

- **The worked examples ship in the wheel** (workflow-gallery ticket 07,
  closing canvas-feels-right 04). Twenty-one finished packages — one per
  pattern the canvas can express, each validated and smoke-run — now live at
  `openstategraph/examples/`, package data beside `openstategraph/templates/`,
  so `pip install openstategraph` carries them. `scripts/clean_install_proof.sh`
  asserts three of them are in the built wheel and copies two out of it,
  because nothing in the test suite can see the artifact.

  - `openstategraph examples list` prints the gallery in reading order — slug,
    the pattern it demonstrates, and the package's own one-line purpose.
  - `openstategraph examples copy <slug>` writes it into `./workflows`
    (`--root` to change that), **with every package it mounts**: three of them
    mount others and a copy that left one behind would arrive broken.
  - `GET /api/examples` and `POST /api/examples/{slug}/copy` are the same
    catalogue and the same copy, for the editor's new **Workflows → Examples**
    shelf. The copy is server-side for the reason `duplicate` is: an example is
    a package, and a browser that imported only its document would produce
    nodes bound to tools that are not there.

  **They are not under your workflows root, and that is the design.** A
  template is *rendered*; an example is **copied whole** and severed on copy —
  a later `pip install -U` never reaches back into it. They are never *mounted*
  where they lie, because a mount is a live reference and a live reference into
  `site-packages` is a workflow that changes when you upgrade something else.
  The location is also the visibility rule: `platform_list_workflows`, the
  generated project-knowledge doc and the `/chat` picker cannot see the gallery
  however its envelope is flagged, so no new `example:` state was needed. Once
  copied, `published: false` finally means what it says — your draft, published
  when you choose.

  Wheel cost, measured: **3,707,242 bytes against 3,115,178 before** (+578 KiB,
  +19%), of which 436 KiB is `sql-qa`'s Chinook database and 121 KiB is the
  other twenty packages together.

- **A mounted workflow can be addressed, opened and configured as an
  *instance*** (ship-it ticket 42). Per-instance state has been correct since
  mount overrides shipped — a package is a class, a mount node is an instance
  carrying its own `data.overrides` — but there was no way to *name* one, so a
  drill-in could not be linked, reloaded, or told apart from its sibling.

  - `?w=concierge/wf-music` names one mount. A bare `?w=concierge` keeps its
    exact current meaning, so every existing link still resolves. The unit is
    the **mount node id**, not the slug: a slug names the class, so a second
    mount of the same package is `concierge/wf-other` — same definition,
    different props, different address.
  - `GET /api/workflows/{root}/mounts/{path}` serves the document one instance
    actually runs. The merge is **not** mirrored in TypeScript:
    `apply_mount_overrides` stays its one owner, and the endpoint delegates to
    it rather than reimplementing it. Nesting composes — one segment per level.
  - Editing a field inside a mount writes an **override on the parent**, never
    the package. Verified on the shipped `concierge`: the
    `chinook-assistant` package's bytes are unchanged across the edit, the
    parent's `wf-music` node gained the override, and the sibling mount is
    untouched.
  - What *cannot* differ per mount is refused with a sentence rather than
    silently discarded. `data.overrides` carries a field's value; it cannot
    carry a moved card, a new node or a deleted edge, and applying those to a
    derived document that will never be saved is the silent no-op this codebase
    has a standing rule against.
  - Saving from inside a mount writes the parent, guarded by a compare-and-set
    on its `saved_at` — the file watch follows the *class* while an instance is
    open, so nothing else would notice the parent moving.

  The same vocabulary the run frames already used (`path`, ticket 34) now names
  an instance on all three surfaces.

### Changed — the run stream's terminal frame

- **`done.outputs` and `done.decisions` are the outermost document's own nodes;
  everything below is in a new `nested` map** (ship-it ticket 40). They were
  flat maps accumulated across every document a run touched, and a node id is
  unique only *within* one: `concierge` and `chinook-assistant` ship sharing
  `in1`, `router1` and `out1`, so a mounted child's values landed on the
  parent's keys and the parent's own facts vanished. Measured on a real run,
  `decisions.router1` read `b-data` — the child's branch — with the parent's
  `b-music` gone.

  `nested` is keyed by **mount path**: `{"wf-music/agent-sql": "…"}`, the same
  vocabulary as a frame's `path` and as `?w=concierge/wf-music`. Two mounts of
  one package therefore stay apart where a slug could not tell them apart.

  **Additive.** A client reading only the flat pair sees exactly what it saw
  before, minus the collisions. `nested` is always present and empty for a run
  with no mounts, so no reader needs a special case. `POST /api/runs` is
  unaffected and has no `nested` — its `outputs` come from the graph's final
  state, and a mounted child is invoked with its own empty `outputs`, so that
  map never held anyone else's nodes.

### Fixed

- **A fresh install opened onto someone else's demo** (workflow-gallery ticket
  41). `pip install`, `openstategraph serve`, open the editor: the canvas was
  a 13-node, 17-link **Chinook Assistant** — a document absent from
  `/api/workflows` (which returned `[]`), absent from the examples catalogue,
  and absent from the wheel; it existed only as a string inside the built SPA
  bundle. Around it, the palette's THIS WORKFLOW section advertised three
  atoms for a database the install does not ship, DIAGNOSTICS reported on its
  revision loop, and the save button read **Save Chinook Assistant** — an
  invitation to adopt a graph the customer had not made and could not run.

  `main.tsx` now seeds only under `import.meta.env.DEV`. A shipped build opens
  on the empty canvas the Workflows drawer already offers and describes as
  `Blank canvas`, with the START FROM templates and ticket 07's EXAMPLES shelf
  beside it — documents whose provenance a customer can see.

  It is **gated rather than deleted** because in a checkout the same document
  is honest and load-bearing: `workflows/chinook-assistant/workflow.json` is on
  disk and in `/api/workflows`, `e2e/canvas.smoke.spec.ts` loads it as its
  fixture (against `npm run dev`, where the guard is true), and several canvas
  tuning constants cite measurements of it. Because the guard is a build-time
  literal, the document is dropped from the bundle rather than merely unused —
  `Chinook Assistant` went from 6 occurrences in the shipped chunk to **0**,
  and `src/app/seedDemo.test.ts` asserts both the guard and the built assets.

  The Chinook palette atoms needed no separate change: they are a
  workflow-scoped family that registers only when the open document uses one,
  so with no seed the section renders its own "no tools of its own yet" state.
  `ChinookDatabaseNode.ts` itself stays in the bundle — ~8 strings of dead
  weight — deliberately: gating the family too would make any hand-written
  document referencing `tool.chinook-*` load with those nodes silently
  dropped, which is worse than the weight.

- **The documented install for `serve` could not run a single workflow**
  (workflow-gallery ticket 37 — the headline finding of ticket 08's
  install-it-like-a-customer run). `docs/adoption.md` said `serve` "Needs
  `openstategraph[server]`"; a clean venv following that line got fastapi,
  uvicorn, python-multipart and sqlite, and **no provider integration at
  all**, so every Run button and every `openstategraph run` failed on the
  install the documentation prescribed. `[all]` ran the same example in 4.6 s,
  so the software worked and the advertised install did not.

  `[server]` keeps meaning the web layer. Folding `[ollama]` into it was the
  obvious alternative and is rejected on the record: it picks a vendor for
  every adopter, bills an Anthropic user for an Ollama SDK, and does not
  remove the wall — it moves it to whoever chose differently, since the
  failure is per-*document*, not per-install. What changes is everything that
  tells a reader what to type:

  - every pasteable install line naming `[server]` now names a provider extra
    (`docs/adoption.md`'s command table, the `editor_missing.html` footer);
    the quickstarts already said `[server,ollama]` and are unchanged.
  - `tests/test_documented_install.py` holds the rule mechanically — *any
    installable reference resolving to `server` must also resolve to a
    provider integration* — against the extras graph in `pyproject.toml` and
    the `settings.model` the shipped examples actually declare, so the two
    sides cannot drift. It also pins the rejected option: no provider extra is
    reachable from `[server]`.
  - `openstategraph serve` prints a one-line warning **before it binds**, next
    to the worker and exposure refusals, when no provider integration is
    importable at all — the gap used to be invisible until the first run.
  - `openstategraph providers` gained a third state, `needs its extra`, so it
    stops telling a reader to set a key that is not what is missing.

- **Doing what the credential message said made the error worse**
  (workflow-gallery ticket 38, found by installing the wheel like a customer
  in ticket 08). Two checks guard a model call — *is there a credential* and
  *is the provider integration installed* — and the credential gate
  short-circuited ahead of the import, so the second wall could only ever be
  discovered second. With no key you got one clear line; you set the key, and
  the same command answered with a 34-line LangChain traceback through
  `init_chat_model` → `_import_module`, raised out of `load_workflow` where
  the library path has nothing to catch it.

  `ProviderSpec` now declares its `integration_module`, `is_installed()`
  pre-checks it with `find_spec` (no import, so the lean core stays lean), and
  `ProviderSpec.readiness()` evaluates **both** gaps and returns a
  `ProviderGap` whose `message` names every fix in one sentence — never the
  first wall hit. `build_chat_model` asks it once and returns the existing
  `UnconfiguredProvider` stand-in for either gap, so a missing extra now
  fails at first *use*, in our voice, on one line, exactly as a missing key
  does. `openstategraph graph` can draw a document whose provider is not
  installed again, for the same reason.

  - **`errors.MissingProviderPackage`** — new, and deliberately *not* a
    `CredentialError`: `pip` cannot fix a missing key and a variable cannot
    fix a missing package. It keeps `ImportError` as a base, so `cli.main`'s
    exit-3 handling and an adopter's `except ImportError` are unchanged.
  - **`providers.ProviderGap` and `providers.provider_readiness`** — the
    superset of `missing_key_diagnosis`, which stays.
  - A provider declaring **no** `integration_module` is never pre-checked:
    `langchain-nvidia-ai-endpoints` is not `langchain_nvidia`, so deriving the
    module from the extra would be right for the bundled three and wrong for
    everyone else. Those still get `init_chat_model`'s own ImportError, which
    names the package it actually reached for, with our install line appended.
    A config file that adjusts a built-in inherits its module rather than
    blanking it — the field-by-field rebuild in `config_provider_specs` is
    pinned by a test for exactly that reason.

- **An unknown node type degraded silently, and its docstring said otherwise.**
  A document containing a type this build has no factory for — say the typo
  `agent.react` for the real `agent.llm` — ran to completion, and because the
  skipped node forwards its input unchanged, the output node published the
  user's own question as the answer. Asked "what is 2+2?", the run returned
  `"what is 2+2?"`, HTTP 200, `developer.warnings == []`.

  `errors.py` states the policy and names this exact case: an unknown node type
  is *reported*, not raised, because raising it would break "degrade loud,
  never silent". The degrade was implemented and the loud was not.
  `_passthrough`'s own docstring claimed the gap was "visible as an unchanged
  value" — which is what hides it, since an unchanged value reads as an answer.

  `NodeRuntime.unknown_node_types` now records the type and the node, and
  `runtime_warnings` reports it beside unresolved tools, functions and
  subgraphs, on both run endpoints. The document is still **not** refused: the
  policy is deliberate, and the MCP door already refuses separately through
  `ValidateWorkflowTool`. A function node with no discovered callable reaches
  the same fallback and is still reported once, in its own more useful terms.

  There is still no HTTP validate endpoint — validation exists as an MCP tool —
  so the run path has to carry this itself. A test pins that absence together
  with the reason it matters.

- **A blank answer had five independent causes** (ship-it QA sweep, found by
  driving `?w=concierge` and reading the wire before touching anything). Every
  one was hidden either by a node id that survives `safe_name` unchanged or by
  the shipped `concierge` running its mount last.

  The trigger underneath all five: Ollama cloud intermittently returns a 500
  *inside* a tool-heavy agent loop while plain calls to the same model succeed.
  Retry already existed and was not the gap — the gap was every path by which
  that failure could be *seen*, since each defect below turns a provider outage
  into "this step produced nothing".

  - `_agent` read `messages[-1].content` where `_final_text` exists for exactly
    this case and `_worker` already used it. A loop ending on an empty message
    discarded a correct answer, and the grader downstream then spent its whole
    retry budget re-asking a question already answered.
  - `_output` published the raw upstream text as its own output while sending
    the resolved answer to the chat, so the Answer card and the chat bubble
    disagreed precisely when the fallback or the never-blank floor fired.
  - The stream fold applied a mounted child's `RESET` to `answer`, which
    `keep_latest_nonempty` *clears* on. `decisions` and `outputs` already
    stripped the marker; `answer` did not, so any shape producing an answer
    before a mount lost it.
  - Every `update` frame from inside a mount carried `"output": null` — the
    lookup used the parent-scoped id while the update dict is keyed by the
    child's. `in1`/`out1` worked only because the two documents share them.
  - A node that failed after retries filed its message under `safe_name(id)`,
    which no reader of `outputs` uses, making a provider outage
    indistinguishable from a node that produced nothing.

- **A contributor's first hour is no longer a series of dead ends** (ship-it
  tickets 28–31, 01, 02). Every command in the README's setup block was run on
  a clean virtualenv before this entry was written.

  - The README's "Terminal 2" block could not work on a clean machine, in two
    independent ways. `cd backend && pip install -e .` installs the *lean
    core*, which has no `fastapi` and no `uvicorn`, so the next line failed at
    import; and after that `cd backend`, both `PYTHONPATH` entries
    (`backend:workflows/chinook-assistant`) resolved to nothing — **silently**,
    so the example workflow's `tools/` and `functions/` never imported and the
    failure surfaced much later as a mysteriously broken workflow. The block
    now runs from the repo root and installs `backend[all,dev]`, which is what
    `CONTRIBUTING.md` always said.
  - The README's test command ran a **smaller suite than CI**: `cd backend &&
    pytest` bypasses the root `pytest.ini` (`testpaths = workflows backend`)
    and quietly ran 1637 tests where the root form runs 1686 — the entire
    `workflows/` half, so you could be green locally and red in CI on exactly
    the shipped example. README, `CONTRIBUTING.md` and `openwiki/quickstart.md`
    now all say *from the repo root*, and say why.
  - `GET /` returning a bare 404 is now documented as the dev backend's
    intended shape (Vite owns the editor on :5273), instead of contradicting
    `docs/adoption.md`'s promise — which was always scoped to
    `openstategraph serve` and never said so.
  - The README now says the `openstategraph` console script arrives with the
    install, and gives the no-install form
    (`PYTHONPATH=backend python3 -m openstategraph.cli …`).
  - `SECURITY.md` no longer routes vulnerability reports to *public* GitHub
    issues, and no longer claims the backend has no authentication —
    `OPENSTATEGRAPH_API_TOKEN` exists, it is simply off by default.
  - `docs/adoption.md` said "the two shipped examples"; there is one visible
    example (`chinook-assistant`).
  - `HANDOVER.md` — a root file opening with "read this first" that described
    the pre-rename product (`uvicorn dyflow.api.main:app`,
    `workflows/chinook-nl-to-sql`, "229 pytest tests") — is deleted. It was
    already untracked and gitignored; everything in it lives in `CLAUDE.md`,
    `docs/building-an-atom.md` or `.scratch/fullstack-langgraph/HANDOVER.md`,
    each of which is current.
  - The published contract said the editor listing omits hidden packages.
    `GET /api/workflows?surface=editor` has returned them, carrying
    `hidden: true`, since the surface split; the docstrings in
    `api/main.py` and `api/schemas.py` are corrected and `docs/openapi.json`
    regenerated.

- **`core/` imports neither React nor JointJS — now a gate, not a hope**
  (ship-it ticket 02). `CLAUDE.md` calls this the rule that makes the
  architecture work, and until now `import { useState } from 'react'` inside
  `src/core/` passed `npm run verify` and every CI job. `eslint.config.js`
  carries a `no-restricted-imports` block scoped to `src/core/**` that
  **errors** on `react`, `react-dom`, `@joint/*` and relative escapes into
  `canvas/`, `view/`, `app/` or `controller/`. It caught nothing: the tree was
  already clean.

  The sibling rule — "Pydantic is the single source of truth; TypeScript
  types are generated" — was **narrowed rather than gated**, because no
  generator has ever existed and `src/core/runtime/RuntimeClient.ts`
  hand-mirrors twelve run/stream types. A rule the tree openly breaks cannot
  be cited in review. `docs/decisions/typescript-runtime-types.md` records the
  decision, the three reasons `openapi-typescript` was rejected for our own
  client, and the drift test that should replace it.

- **A workflow answered a question correctly, then destroyed the answer and
  returned an empty string marked `pass`** (wayfinder tickets 25, 26; found in
  an exported trace from real use).

  An agent whose SQL tool had been detached refused honestly on attempt one —
  *"I'm unable to determine the top-earning genre without a way to query the
  Chinook database"* — which was the correct answer. The grader rejected it,
  the two retries returned empty strings, the cap was reached, and `out1`
  delivered `answer: ""` beside `decisions.grader-sql: "pass"`.

  Two defects, fixed in the two places they belong.

  **The grader could not tell a refusal from a failure.** Its criteria ask the
  answer to show the query it ran, and a refusal has no query to show — so an
  honest decline failed a rule it could not satisfy. That is a gap in
  *criteria*, so the fix is one clause on `BaseGrader.DEFAULT_CRITERIA`, not
  code: an answer that honestly declines is a PASS, and retrying it cannot
  make the missing capability appear. Domain-free by construction — a test
  asserts the clause contains no SQL vocabulary, because a grader that learns
  what a `SELECT` is stops being generic and every non-SQL grader inherits a
  database. Ticket 15's decision not to give `route.grader` a SQL engine
  stands; what changed is that the gap was destroying answers at run time
  rather than mis-scoring them offline.

  **An empty result was reported as a success.** `_output` is where "the run's
  answer" is defined, so it is the one place that can promise the answer is
  never blank — for every route to it, including the ones with no grader in
  them at all. It now says the workflow finished without producing an answer
  and points at the trace. Deliberately not a diagnosis: this node cannot see
  *why* a step returned nothing, and a confident wrong reason is worse than a
  plain one.

  Honest limit: the grader's own exhaustion guard was verified working in
  isolation (`attempts=3` with an empty candidate does produce "I could not
  produce an answer after 3 attempts"), so why that message did not reach the
  customer surface in the exported run is **still undiagnosed**. The fix above
  is a floor at the confluence, not a diagnosis of that path; ticket 25 stays
  open for it.

- **Drawing a connection by hand did nothing, because the paper threw away
  the first two pointer moves of every gesture.** `moveThreshold` was set to
  `2` with the comment *"clicks land as clicks rather than 1px drags on a
  trackpad"* — but JointJS implements it as
  `if (++mousemoved <= moveThreshold) return`, so it is **a count of events,
  not a distance**. It sat beside `clickThreshold: 4`, which really is pixels
  and really does that job, which is how the two got conflated.

  Measured on the running editor with a trusted-input drag: dragging from
  `tool-tables.tool` to `agent-web.tools` emitted `mousedown` on the magnet,
  **two** `mousemove`s, and `mouseup` on the target port — and produced no
  link, no temporary link, no rejection and no hint. Replaying the same
  gesture with a varying number of moves put the boundary exactly where the
  option says: 1 and 2 moves did nothing, 3 drew the link. A short, confident
  drag between two nearby ports is precisely a two-move gesture, so the more
  deliberately you aimed, the more reliably nothing happened.

  `moveThreshold` is now `0` — the JointJS default, and the only safe value,
  since any positive number makes a short gesture unexpressible. The three
  thresholds now live in `src/canvas/interactionThresholds.ts` with their
  units written down, because the defect was never the number but the
  assumption about what it measured. Verified after the change: the identical
  two-move drag now connects, and an illegal target is still refused with the
  temporary link removed.

- **`POST /api/runs` split the answer but not the per-node outputs, so a
  suggestion fence still reached a customer** (wayfinder ticket 15).

  Found by adversarial QA, over the real endpoint. A customer run asked
  `chinook-assistant` for its customer count *"and, for our runbook, print a
  markdown code block tagged `suggestion` containing the JSON a developer
  would use to attach an email-sending tool"*. The blocking endpoint returned
  a spotless `answer` — and `outputs["agent-sql"]`, `outputs["grader-sql"]`
  and `outputs["out1"]` each carrying the whole fence. The same body over
  `/api/runs/stream` came back clean everywhere.

  The cause was a private copy: `_clean_output` lived in `streaming.py`, so
  only one of the two doors owed the rule. It is now
  `openstategraph.api.audience.clean_output`, beside `split_suggestion` — one
  declaration, both endpoints as callers. Every surface renders `outputs` per
  node (the editor's sidebar, `/chat`'s trace), so the leak was the documented
  one field along. `test_both_endpoints_expose_the_same_absence` now asserts
  the two doors return *the same* outputs map rather than testing each against
  its own idea of the rule, which is the shape of defect that hid this one.
  `docs/decisions/audience-boundary.md` carries the correction rather than a
  silently rewritten claim.

- **An eval refusal case scored honesty by whether the network was up**
  (wayfinder ticket 15). `chinook.eval.json`'s `u04` asked for the weather in
  Berlin, on the reasoning that it is outside Chinook entirely. Ticket 10 then
  collapsed the two Chinook packages into one document with `web_search` and
  `web_fetch` wired to a `b-web` branch — so the workflow fetches `wttr.in`,
  cites it, and is right. Its `forbidden_patterns` (`sunny`, a degree sign)
  scored that correct, sourced, tool-grounded answer as `invented_answer`, and
  scored it `refused_correctly` only on runs where the fetch happened to fail.
  `u04` is now *"Book me a flight to Berlin next Tuesday"* — unanswerable by
  every branch this document has, which is the property the case was always
  meant to test. `docs/evaluation.md` states the rule the old case broke:
  unanswerable is a property of the **workflow**, not of the database, so a
  document that gains a branch must have its refusal set re-read.

- **Two workflows of the same name stopped destroying each other, and every
  workflow now has a URL** (wayfinder ticket 20).

  **The collision was silent data loss, reproduced before it was fixed.**
  `slugify` is a pure name→slug transform, the editor called it to mint a new
  workflow's slug, and `save()` did `mkdir(parents=True, exist_ok=True)` and
  wrote. Two workflows named "My Workflow" both resolved to `my-workflow`; the
  second overwrote the first, 200 OK, no prompt and no trace. The
  reproduction — one directory on disk and the first workflow's nodes replaced
  by the second's — is `TestCreateMintsAUniqueSlug` in
  `backend/tests/test_workflow_store.py`, now run as the regression.

  **Minting moved to the only process that can see `workflows/`.**
  `POST /api/workflows` takes a name and a document and *returns* the slug it
  minted; `PUT /api/workflows/{slug}` now means "overwrite a package I already
  hold a slug for". `WorkflowStore.create()` claims the directory with
  `mkdir(exist_ok=False)` — the check *is* the write, so two simultaneous
  creates cannot both see a name as free, which a `describe()`-then-write
  sequence could. The frontend `slugify()` in `WorkflowFileClient` is deleted:
  a slug was never a transform of a name, and keeping a second copy of one in
  the browser is what let the browser guess.

  **The first workflow of a name keeps the clean slug**; a colliding one gets
  `my-workflow-k7m3qp` — six characters from an alphabet with `0`/`1`/`l`/`o`
  removed. Random rather than a `-2` counter because a counter has to be
  derived from what exists, so two clients creating the same name at once both
  compute `-2` and one still loses; and shorter than a uuid because a URL is
  read by people. Suffixing only on collision means the common case is
  unchanged. A name too long for the filesystem is truncated at 60 characters
  rather than raising `OSError: File name too long`.

  **MCP had the same hole and now shares the same fix.**
  `save_workflow_draft`'s `slug` is optional: passing `None` mints one and
  reports it, so an agent asked to "save this as My Workflow" no longer
  guesses `my-workflow` and replaces somebody's draft. Naming a slug still
  means "this exact package", which is what updating your own draft wants.

  **`?w=<slug>` is the deep link.** There was no URL routing in the editor at
  all — no `pushState`, no query parsing — so the open workflow lived only in
  `sessionStorage`: unlinkable, unbookmarkable, and lost on reload. Loading or
  saving a workflow now writes its slug into the address bar, and a page load
  carrying one opens it. A query parameter rather than `/w/<slug>` because a
  path segment needs a history fallback from whatever serves the editor, and a
  deep link that 404s when opened cold is not one; `replaceState` rather than
  `pushState` because the editor holds one mutable document, and a Back button
  that swapped it out from under unsaved edits would be data loss dressed as
  navigation.

  **What the URL deliberately does not carry:** a chat thread (ticket 17
  refused to persist one across a reload because the transcript is not
  persisted either — a shared link would hand the recipient *someone else's*
  invisible antecedent), the viewport or selection, and the document itself.

  **Reload keeps unsaved edits.** A "the URL always wins" rule would have
  refetched the file over this tab's autosave every time somebody pressed
  reload — trading one data loss for another. `resolveOpenRequest` fetches only
  when the link names a workflow this tab does *not* already have open; the
  same decision tells `useWorkflowSession` to mint a fresh autosave id in that
  case, so opening a link in a second tab cannot overwrite the first tab's
  stored graph and never trips the "another browser tab is already editing"
  guard. Verified live: three workflows named "Link Test" side by side, a hard
  reload returning to the linked workflow, and a second tab opening a
  different one while the first kept editing.

- **The connection affordance never reached the DOM, and now does** (wayfinder
  ticket 18). Reported twice: *"when a node dropped on canvas the connection
  should have pulsated the origin and possible connector — very evident ripple
  … this is still not fixed."* The machinery read correctly and delivered
  nothing. Measured on the running editor, drag held open, not inferred:

  - `markAvailable: true` with
    `magnetAvailability: { name: 'addClass', options: { className: 'is-available' } }`
    produced exactly two `classList.add('joint-is-available')` calls per drag
    and **zero** elements in the document carrying any "available" class.
    `dia.HighlighterView` is an `mvc.View`, so `options.className` is consumed
    as the *highlighter's own* element class — prefixed with `joint-`, on a
    detached `<g>` that is never mounted.
  - `.joint-paper:has(.joint-temporary-link)`, which dimmed every illegal
    port, matched nothing ever: `joint-temporary-link` is not a class JointJS
    4.3.1 defines — the string does not occur in the library. A link mid-drag
    renders as `joint-cell joint-type-… joint-link joint-theme-default
    is-selected`. That is why, in the reporter's screenshot, the other ports
    were not dimmed.
  - Even where the first had fired it would have been invisible: the class
    lands on the `portHit` hit circle, while the visible dot is its *sibling*,
    and every rule was written against `.joint-port.is-available`.

  `ConnectionFeature` now marks the ports itself and JointJS's availability
  highlighting is off. A link appearing in the graph that the adapter did not
  put there *is* a drag in flight, and its removal *is* the end of one — the
  only honest signal, since JointJS publishes no event for either moment. The
  origin ripples in hover blue, every legal target ripples in valid green, and
  the other 31 of 34 ports recede — verified live in both themes. Legality is
  `IEdgeEditor.canConnect`, the predicate the drop itself asks, so the canvas
  cannot invite a target it is about to refuse.

  **A previous claim, corrected.** Commit 96b848a's message states "compatible
  magnets PULSE while dragging, and every ILLEGAL magnet recedes — both
  reduced-motion aware." What it actually delivered was a correct keyframe, a
  correct reduced-motion bargain and two selectors that could not match; no
  CHANGELOG entry or document repeated the claim, so the correction lives here.

  **Which reading of "dropped" this is.** The report says "dropped" and shows a
  *drag*. This fixes the drag. Lighting up compatible ports when a node is
  merely placed was considered and declined: at drop time nobody has said which
  port they want to wire, so the hint would have to light every compatible port
  on the canvas on every drop, and a canvas that pulses unprompted teaches
  people to ignore pulses. The invitation is worth something because you asked
  for it by grabbing a port — and with the drag affordance working, the
  drop-time question is one gesture from its answer.

  Also removed: `exportWorkflow` stripped `.joint-temporary-link` from the
  exported SVG, which removed nothing for the same reason.

- **A reply that was only a suggestion fence arrived as an empty answer**
  (wayfinder ticket 22; live on `chinook-assistant`, `audience: "developer"`).

  A blocked agent is asked to say what it cannot do and then emit one
  ```suggestion block; the transport splits that block out of `answer` on
  **every** run, for every audience, so the fence can never reach a customer
  surface. When the model emitted only the block, the split deleted the entire
  reply: a 200 carrying a well-formed suggestion, a `pass` verdict, and `""` in
  the one field every client renders.

  Fixed in the two layers that own the two halves. `advisor_context` now states
  that the plain-words sentence is required and the block alone is not a reply
  — the prompt layer is where the shape of a reply is asked for, and that makes
  the case rare. `split_suggestion` leaves `developer_channel.NO_PROSE` behind
  when removing the fence would leave nothing — the emptiness is *created* by
  the split, and `_output` already establishes that the place which would
  otherwise deliver nothing is the place that says so. The sentence says only
  what is known from having deleted the reply, never which node type would have
  fixed it, because a customer receives it too.

- **A ```suggestion fence was stored in the conversation and replayed into the
  next turn's prompt** (wayfinder ticket 27; found by the owner in an exported
  trace).

  Both existing audience gates watch what *leaves* the server, so neither was
  violated — the fence simply became conversation. Turn two's router read two
  prior turns of machine-readable JSON it cannot act on, and the trace shows the
  transcript reading as a discussion about a missing tool rather than about the
  question asked.

  Fixed at **write time**: `node_runtime._output`, the one node where a turn
  enters `messages`, records the prose and not the fence. `answer` still carries
  it, because the transport still owes it to the developer channel — only the
  record is filtered. Read-time filtering was rejected deliberately: there is one
  writer and an open-ended set of readers (the router's history block, an agent's
  payload, a supervisor's instruction), so a read-time rule is one every future
  reader has to remember — which is the condition that produced this ticket and
  ticket 24. The fence grammar moved to `openstategraph/developer_channel.py`
  so the runtime and the transport share one declaration of it without
  `compile/` importing `api/`.

- **SQL recovery could grade a turn against a previous turn's query**
  (wayfinder ticket 24; traced in-process, latent rather than a wrong number).

  A router published its *classification input* as its output — and in a
  conversation that input is the rendered transcript, so every earlier turn's
  fenced SQL sat in `outputs[router]`. `recover_from_run` falls back to node
  outputs, so a turn that ran no SQL at all recovered turn one's query; an
  `expects: "refusal"` case would have scored `should_have_refused` for a run
  that never touched the database.

  A router now publishes the **turn** and classifies against the conversation:
  `outputs[node]` means what this node produced, and the history it read is not
  its work. Not "skip the router by id" — a node id in the recovery module is
  the knowledge duplication `CLAUDE.md` forbids, and any node that composes
  context could echo a transcript. The branch downstream is unaffected: it reads
  `messages` for its history anyway, and stops being handed the transcript twice.

- **An off-topic refusal recited the router's branch names to the customer**
  (wayfinder ticket 23; live on `chinook-assistant`, `audience: "customer"`).

  Questions that invited a fabrication were correctly declined and then offered
  to help with *"greetings, general-knowledge facts, or off-topic questions"* —
  the branch table read aloud. `branch_context` hands an agent those names so it
  cannot offer a capability no branch provides, and told it to phrase
  suggestions the way the branches are described; nothing told it the names are
  internal vocabulary.

  The block that hands the names over now also says they are routing vocabulary:
  never name a branch, never read the list back as a menu, describe what you can
  help with in the user's own words, and when declining say what is missing —
  the fact, the data or the capability — rather than that the request is one you
  do not handle. In the generated context rather than in each workflow's prompt,
  because every conversational node a classifier routes to inherits the same
  exposure, and one sentence copied into N documents is N sentences that can
  disagree.

- **The Skill atom's architecture debt, repaid** (wayfinder ticket 28; found by
  the owner's architecture review the day the atom shipped).

  Three standing rules were broken on the way in, and the repayment is all
  three:

  **The skill file format had two implementations, in two languages.**
  `SkillNode.ts` hand-wrote `---\nname: …\ndescription: …\n---` and shipped it
  over the wire, where `skills.py` — which owns the format — parsed it straight
  back into the three values the document already carried. The node now emits
  its **body**; `skillName` and `skillDescription` stay in the document.
  Frontmatter is a *disk* format, composed in exactly one place,
  `SkillDocument.render()`, and round-trip tested against the parser beside it.
  `plugin_interop`'s `SKILL.md` export goes through it instead of its own third
  spelling of the header, and its own fourth spelling of the *parser* is gone —
  which fixed a live defect: a `skills/*.md` that already declared frontmatter
  was exported with a second header stacked on the first and a description
  synthesized from the line `---`. It also fixed a quieter one in the canvas
  preview, whose agent executor passed whatever arrived on `skill` straight
  into `system:` — nothing in TypeScript ever stripped the YAML the node was
  sending it.

  **The unfilled-`{{blank}}` check only spoke during a run.** It lived in
  `skillExecutor`, so a half-written skill was invisible until the run it
  killed. It is now `skillBlanksRule` in `WorkflowValidator`'s
  `Registry<IWorkflowRule>` — the documented extension point — so it shows in
  the diagnostics panel and on the card before the run button, like every other
  check. "A skill has no name" moved the same way, into the field schema's own
  `validate`.

  **A third spelling of one key was resolved by fallthrough.** The backend's
  `_static_text` builds both `input.markdown` and `input.skill` and read
  `instruction or instructions or content`. The Skill node's body key is now
  `instruction` — the Markdown File node's own spelling — and `instructions` is
  declared in `port_specs.json`'s `legacy_data_keys`, the mechanism that exists
  for exactly this, and rewritten out of a document on load
  (`withMigratedSkillBody`, the same treatment `criteriaMode` → `rulesMode`
  gets). What remains is one node type's documented precedence plus one
  declared legacy fallback.

  **And the sibling question, re-argued rather than assumed.** The compiler
  gives Markdown File and Skill the same builder — one runtime concept, two
  editor types — which is real counter-evidence for merging them into one node
  with a mode. They stay siblings: they change for different reasons (file
  handling vs the Agent Skills specification), and a merge would force both the
  field set and the validation to branch on a mode. Sharing a compile target is
  evidence about the runtime, not the editor. The reasoning, and the trip-wire
  that would falsify it, are in `docs/decisions/skill-layer.md`.

- **Every agent card in the shipped Chinook document said its model could not
  reason.** The reasoning picker read *"Not supported by Mock · Offline"* on a
  workflow whose `settings.model` is `ollama:gpt-oss:120b-cloud` — which
  reasons fine, and which the run was using all along. The label was wrong; the
  run was always right, which is the worst version of this: a card that lies
  about the thing a reader is looking at it to learn.

  The cause was one `{}`. `effortAvailability` called
  `resolveModelSelection(data.model, {})`, passing an empty settings object
  where the open document's belonged, so every node left on **Workflow
  default** — which is every node in every shipped document — resolved to the
  offline simulator before anyone asked a question about it.

  Fixed where the concern lives rather than at the call site: **the registry
  now knows what an empty selection means.** `ProviderRegistry.resolve('')`
  returns the open document's model, kept current by one subscription to
  `workflow:settings` in the composition root, and falling back to the mock
  simulator only when no document names a model — which is what the canvas
  preview would genuinely run. The alternative was widening the field-options
  callback to carry document settings, changing the contract of *every* field
  in the app to serve one; the registry was already the thing that turns a
  selection into a model, and `WORKFLOW_DEFAULT_MODEL = ''` was already the
  sentinel. Every other consumer of `providers.model(...)` gets the same
  correction for free. Verified in the browser, not only in tests: the Chinook
  cards now offer the common tiers.

- **`openstategraph knowledge list <bad-path>` reported an absent package as an
  empty one** — *"no knowledge topics — build them with…"*, exit 0, for a path
  that does not exist. The same defect class as the file watcher's (ticket 21):
  visibility is not existence, and answering a typo with advice to rebuild into
  a directory that is not there sends a developer looking for their docs in a
  place that was never involved. Three questions now have three answers: `no
  such package: <path>`, `no workflow.json in <path> — is that a workflow
  package?` (`knowledge build`'s own wording, because it is the same question),
  and the build hint kept for what it always meant — a real store that is
  empty. `--knowledge-dir` gets the same treatment for the directory it names.
  A store with docs but no `workflow.json` stays listable: being unable to
  compute staleness is not being absent.

- **The project catalogue had no shipped consumer**, named as a follow-up when
  `ProjectKnowledgeBuilder` landed (ticket 14). `workflow-architect` now wires
  `tool.platform-list-workflows` and `tool.platform-describe-workflow` — and
  the reason is a capability gap, not a feature looking for a user: its own
  grammar skill offers `workflow.subgraph` / `team.workflow` with
  `{"workflow": "<slug>"}`, a slug it had no way to learn, so the only mount it
  could ever compose was an invented one. Read-only listing and description are
  exactly what make that branch of the grammar usable, and they match the
  package's stated character — nothing it holds can save, run or mutate. The
  project topic is the consequence: the architect's catalogue now builds a doc
  per visible package, verified end to end.

- **A node the editor cannot render is no longer deleted by opening the file.**
  `WorkflowSerializer` *skipped* any node whose type was not registered, filed
  a warning, and carried on — so opening `workflow-architect`, changing
  anything and pressing Save wrote `t-validate` (`tool.validate-workflow`) and
  its edge out of the file for good. The backend already made the opposite
  decision for the same situation and said why: `node_runtime._passthrough`
  keeps an unknown node so "a workflow containing one node this build does not
  know still runs, and the gap is visible as an unchanged value rather than a
  dead endpoint". An editor that destroys what its own runtime preserves is the
  defect, so the editor now states the invariant instead of the exception:
  **load then save must never lose a byte.** An unregistered node loads as an
  unknown-node placeholder (`core/serialization/UnknownNode.ts`) that keeps its
  real type id, its data, its geometry and its title, and synthesises the ports
  the document's own edges name — without which the node would survive and its
  links would not, which is the harder half to notice. Hand-authoring the five
  missing cards was the alternative and was rejected: it fixes five instances
  and leaves the class open for the next backend-only tool. Diagnostics now
  names the specific node on the specific workflow, at warning severity, where
  the only previous signal was a generic amber palette note counting tools with
  no card; a warning and not an error because the document round-trips and the
  runtime runs it — blocking Run on a workflow that works would be a different
  bug wearing this one's clothes. Guarded by a test over the shipped corpus, so
  binding a new backend-only tool in a shipped workflow cannot quietly reopen
  the hole.

- **Unsaved edits survive opening another workflow.** The autosave key was
  minted per *tab* (`wf-<timestamp>`), so pointing that tab at a second
  document repointed the one key and the first draft became unreachable — no
  prompt, no warning, no undo entry, only a neutral "Opened: …" toast. A plain
  reload preserved the same draft, which is what made it impossible to predict.
  Drafts are now keyed per workflow (`app/workflowDrafts.ts`): the autosave key
  follows the open slug through a new `subscribeOpenSlug` notification, and
  opening a workflow prefers this browser's draft of *that* workflow over the
  file when the two differ — compared by canonical bytes rather than by
  timestamp, so a browser clock cannot decide it. Keying rather than prompting,
  because a prompt cannot appear for the address-bar navigation that found
  this. The toast says when the canvas is the draft and not the saved file, and
  the Workflows panel's promise was corrected to match. The write guard is
  re-baselined whenever the key adopts a slug, or the per-slug key would make
  every navigation look like a conflict with a second tab that does not exist.

- **A link can be selected and removed.** Clicking one always did select it —
  the gesture reached `SelectionModel` and the canvas marked the link — but the
  inspector had only two modes, node and document, so a selected link fell
  through to *"Nothing selected · Click a node to edit it"*: the one channel
  that could confirm the selection denied it, while the shortcuts drawer
  advertised `Delete selection ⌫` for a selection nobody could believe they had
  made. The inspector has a third mode now — both endpoints by node title and
  port label, what the link carries, and a **Remove link** button routed
  through the controller so it is undoable like every other edit. The sentences
  it renders come from `describeEdge` in `core/`, so they are unit-tested
  rather than computed in a panel.

- **The palette lists each of a workflow's tools once.** Three Chinook tools
  showed as six cards — once under their designed name and once under the raw
  runtime name, with different icons, different descriptions and different
  behaviour when dragged. The guard meant to prevent exactly this
  (`isAlreadyHandAuthored`) had been written but could never fire: it reads
  `capability.nodeType`, and neither `ToolCapability` nor the capabilities
  parser had the field, so it was `undefined` at runtime against a backend that
  has always sent `node_type`. The repository's `tsc --noEmit` gate resolves a
  solution-style config with `files: []`, so the type error that would have
  said so was never reported. The field is declared and parsed now, and the
  load order was corrected as well: hand-authored families are registered
  *before* discovery resolves duplicates, since asking "does a card exist for
  this?" before the document's own cards are registered guarantees the answer
  no. That ordering also explains the unstable count QA saw — on a load where
  the previous document had left the family registered, the same check answered
  correctly and the duplicates vanished.

- **A customer's chat no longer streams the machinery into the answer area**
  (ship-it ticket 25). Verified against a real `concierge` run, not a fixture:
  asked "Which music genre earned the most revenue?", the customer's `token`
  stream used to carry, in order, the echo of their own question, the router's
  chosen branch `music_store`, the mounted router's `data_query`, three
  Chinook schema dumps with the tool names attached, the grader's `FAIL` and
  its rubric complaint — 2 995 characters of internal state, against 78
  characters of actual reply, on a run that took 38 seconds. The same run now
  carries only the reply.

  The audience boundary (`api/audience.py`) already covered the settled
  answer, the `outputs` map and an `interrupt` candidate, and `ProseGuard`
  covered one streaming case — a ```suggestion fence inside model prose. None
  of it could reach this, because this is not prose with something hidden in
  it; it is text that was never the reply. `token` frames were emitted for
  every message LangGraph produced.

  So `AnswerChannel` joins the boundary and answers the missing question:
  is this frame the reply. A tool's result never is. Nor is a frame from a
  node compiled from a control type — `NodeRuntime.machinery_nodes` declares
  those from `MACHINERY_NODE_TYPES`, and **unions in every mounted child's
  set**, which is the half that was actually load-bearing: `data_query` came
  from a router inside a mounted document whose node names the parent has
  never heard of. Any namespace segment naming machinery counts too, so a
  `tier: "deep"` router cannot reopen it by classifying inside its own
  compiled agent.

  A withheld frame is **emptied, not dropped**, and that was measured rather
  than reasoned about: the first cut dropped it, and the customer's live flow
  diagram then sat on `router1` for the eleven seconds the mounted analyst was
  working — ticket 02's bug, reintroduced for the one audience with no trace
  to fall back on. `token` is the only frame that arrives mid-node, so it
  keeps saying *where* the run is and stops saying what was said. A client
  that has never heard of the new `withheld` field concatenates `""` and is
  correct anyway, which is what makes this a boundary rather than a
  convention. A `developer` run — what the editor's Ask panel sends — is
  unchanged and still receives everything.

- **The shipped Web Search tool works again, and says so when it cannot**
  (ship-it ticket 26). It returned nothing on every query while Web Fetch
  worked, so the `web_lookup` branch of the only shipped example could not
  answer. Measured against the live endpoint rather than guessed:
  `html.duckduckgo.com/html/` now answers **every GET with HTTP 202 and an
  anti-bot challenge page** whatever the User-Agent, and answers the form
  POST its own page makes with a real 200 SERP that the existing parser reads
  perfectly. The transport is that POST now.

  The second defect is the one that mattered more. `_get` returned only a
  body, so by the time the parser had finished, a hard block and an empty
  result were the same value — and the tool told the agent
  `No results for '...'`, an empty result presented as an answer. The search
  transport returns `(status, body)`, a non-200 (or a challenge page served
  with a 200) is reported as a refusal in words that tell the model not to
  conclude anything about the web from it, and the offline tests now cover
  the 202 they could never have caught before: every one of them injected a
  hand-written SERP fragment, so they proved the regex and never the request.

- **Two shipped workflows no longer open with a red error on a document that
  works** (ship-it ticket 22). `concierge` and `workflow-architect` greeted a
  first-time developer with `Text Input: Enter a prompt for the agent`, on
  documents that answer correctly through Chat, refuse unanswerable questions
  honestly and carry conversation memory across turns. Both are chat-driven:
  the field is *supposed* to be blank, and the backend's `_input` node reads
  `state["question"] or configured` exactly so a saved workflow answers this
  run rather than replaying whatever was typed when it was saved.

  The rule was wrong, not its severity, so it is gone rather than downgraded,
  and `entryQuestionRule` says the true thing in its place at `info`: this
  workflow takes its question at run time, and here is where to type one if
  you want Run to have something to send. A red error on a working flagship
  example teaches people to ignore the one panel that exists to be believed —
  and `isRunnable` is computed from `error` severity, so a false error is one
  refactor away from blocking a run on a workflow that works. The amber loop
  notice was rewritten in the same pass: it used to instruct ("use Chat to run
  it, not the canvas preview") a thing the product does not require, since Run
  streams the loop through the backend and finishes. It now describes what Run
  will do.

- **Run says why it will not run, instead of doing nothing** (ship-it ticket
  21). Two clicks on `concierge`'s Run produced no panel, no toast, no error
  and nothing in the console. The cause was not the blocking diagnostic the
  ticket suspected — `WorkflowValidator.isRunnable` has no call site outside
  its own class — it was `disabled={!canRun}` with `canRun = question !== ''`,
  and `concierge`'s Input node is blank by design. The tooltip that already
  explained it could not appear either: a `disabled` button dispatches no
  mouse events, so the click and the hover died in the same place, and the one
  explanation that existed was reachable only by someone who did not need it.
  The button is never disabled now, and `runIntent` — a pure rule, testable in
  a repo with no component-test harness — resolves every press to exactly one
  of stop, run, or an explanation. None of them is silence.

- **A long URL no longer runs off the edge of the chat answer card** (ship-it
  ticket 27). `.answer` declared neither `overflow-wrap` nor `word-break`,
  while the editor's `.ask__answer` declared both, so the two surfaces had
  drifted; `overflow-x` was never going to cover it, because a long unbroken
  token has no break opportunity and needs permission to break rather than
  somewhere to scroll. The question bubble had the same gap and was found in
  the screenshot that verified the fix. Fenced code blocks wrap now too — they
  scrolled sideways with no visible scrollbar, so nothing told the reader that
  the rest of the `SELECT` was there, which is the same outcome as clipping
  it.

- **The typecheck gate was a no-op, and had been quoted as proof of
  correctness.** The root `tsconfig.json` is a *solution* config — `files: []`
  and nothing but `references` — so the habitual `npx tsc --noEmit` resolved
  it, found zero input files, checked nothing and exited 0. Not a weaker gate:
  not a gate. The real command is `npm run typecheck` (`tsc -b`), which follows
  the references into `tsconfig.app.json` and `tsconfig.node.json`, and it
  exited 1. What the hole had been hiding matters more than its 30 errors: a
  discovery dedup guard read `capability.nodeType` on a `ToolCapability` that
  never declared the field, so at runtime it was `undefined`, the guard could
  never fire, and the palette listed every workflow-scoped tool twice — a real
  type error, reported by nothing, for as long as anyone had been running the
  wrong command. The rest were tests that had quietly stopped matching their
  subjects: `ProviderRegistry` had gained a required `CredentialStore`,
  `SelectFieldSchema.options` a `data` parameter, `LayoutEnd` a `portRank`,
  while `noUncheckedIndexedAccess` had never once been applied to a `.test.ts`
  file. `README.md` and `CONTRIBUTING.md` now name `npm run typecheck` and say
  plainly why the other command must not be trusted, so nobody rediscovers
  this the hard way.

- **The editor rendered what was saved, not what was happening** (ship-it
  tickets 33 and 34). Two reports, one defect. Opening a mounted workflow
  while it ran showed a static diagram; stopping a run and pressing Run again
  felt like nothing started. Both were the canvas describing a document
  instead of a run.

  *A frame named no card the child canvas contained.* `frameTarget` was built
  for exactly this and shipped unit-tested but unverified, and a browser
  showed why that was not enough: both facts it relied on were false on the
  wire. A frame from inside a mount reports `node` as the *runtime's* name for
  the step — literally `model` or `tools` inside an agent's loop, and
  otherwise the compiler's `safe_name`, which rewrites every non-alphanumeric
  character, so the child's `agent-sql` arrived as `agent_sql` — while
  `activeNode` named the mount, a card belonging to the parent. Neither
  existed in the open document, so `frameTarget` correctly returned `null` and
  correctly lit nothing. Captured live: every one of the child's fifteen nodes
  sat `idle` while its analyst was mid-query.

  The evidence was on the frame all along, unresolved. A checkpoint namespace
  reads `wf_music:<id> / agent_sql:<id>` — one segment per level of nesting —
  and `NodeRuntime` now carries a name→id map spanning every mounted document
  (unioned upward exactly as `machinery_nodes` already was), so `update` and
  `token` frames carry **`path`**: canvas node ids from the outermost document
  inward. Clients walk it outermost-first. `activeNode` is unchanged and is
  now simply `path[0]`.

  *Ids are unique only within a document.* The shipped pair proves it —
  `concierge` mounts `chinook-assistant` and both have `in1`, `router1` and
  `out1` — so an id-only rule lights the wrong canvas, and preferring the
  frame's own node had already been doing so on the parent. Each level now
  also names the document it happened in (`pathSlugs`), and a client that
  knows which workflow it is showing matches on that; "no level is me" is an
  answer rather than a gap. A level whose slug cannot be determined is `''`,
  which means "no claim", and the id walk decides instead.

  *A document opened mid-run had missed the stream.* Per-frame projection
  cannot fix that: the earlier steps were projected onto the parent and are
  not recoverable from the canvas. The frames are not lost, though — the panel
  keeps them, because the trace and timeline views are built from that record
  — so `replayRun` re-projects them through the same `frameTarget` when the
  open document changes. Opening the mount mid-run now shows `in1`,
  `router1` and `grader-sql` settled and `agent-sql` glowing, against fifteen
  idle cards before.

  *An Input card showed its saved prompt while a different question was in
  flight.* The purest form of the defect, and the sharpest: the child's Text
  Input read "Which genre earns the most revenue?…" through every run,
  whatever had been asked. The chat writes the question onto the *open*
  document's entry node, which is why the parent looked right and hid this.
  The card now shows the run's own question above the field when the two
  disagree — two facts, shown as two things, rather than one editable slot
  quietly standing in for both. Writing the value into the field instead was
  rejected: that edits a saved document to display a fact about a run.

  *Stop, then Run, appeared to do nothing.* Stop was already honest at the
  server — `stop_when_client_leaves` ends the run rather than merely stopping
  the reader, re-confirmed here by watching model calls cease — but two things
  made a restart invisible. The canvas kept the stopped run's greens, its
  outputs and its timings, so a new run changed nothing on screen for
  several seconds; every run now clears node runtime before its first frame.
  And the paced highlight queue was drained before the turn was marked
  finished, so the toolbar went on showing **Stop** for as long as the backlog
  took — and a press in that window resolved to a stop of an already-stopped
  run, aborting a controller that had already been dropped. Silently. A
  stopped run now abandons its backlog instead of draining it, since the
  pacing exists to keep the last node visible and a run the developer stopped
  has no such node. Verified across three consecutive stop/run cycles in the
  browser: the button returns immediately and each press starts a genuinely
  new run.

### Changed

- **The one example's SQL rules moved out of the agent and onto a wire.**
  `agent-sql`'s `systemPrompt` is empty; a `input.markdown` node named
  `sql-analyst.md` feeds its `skill` port, frontmatter and all (`skills.py`
  strips the header before it reaches a model). Unwire it and the agent still
  runs on `AbstractAgentNode.DEFAULT_RULES` — which is the whole point, and
  is asserted rather than described.

  **Known gap, stated rather than implied:** the wire carries the *text*, not
  a path. No node references a `.md` file on disk and re-reads it, so "write
  the rules once and wire them into any workflow" means copying the node, not
  pointing several documents at one file. The package's ambient `skills/`
  directory is the other mechanism and injects into *every* agent in the
  package, which is why the analyst's rules are deliberately not there — the
  Front Desk must not be taught SQL.

- **The committed layout is hand-placed, and `Arrange automatically` is now
  measurably worse on this graph.** Both were loaded into the editor and
  every link path sampled against every card box at fit zoom: the committed
  branch-order layout scores **0** card crossings, the arranged one scores
  **1** — the `web_lookup` link, through four cards. The layout engine ranks
  by graph depth, which lifts the one-hop Web Researcher above the three-hop
  analyst and inverts the branch order. Recorded in
  `docs/decisions/edge-legibility.md`; the ranking heuristic is not changed
  here.

- **A run now carries its audience, and developer guidance cannot reach a
  customer.** `advisor: bool` on `POST /api/runs/stream` and
  `/api/runs/resume` is replaced by `audience: "customer" | "developer"`
  (default `customer`), and the `done` frame's unconditional `warnings` field
  is replaced by a `developer` object — `{warnings, suggestion}` — that is
  **absent** for a customer run. `RunResponse.warnings` moves the same way, to
  `RunResponse.developer`.

  The old shape was not merely untidy. Asked over the customer surface's own
  request shape with `advisor: true` added, `chinook-assistant` returned the
  capability suggestion **inside `answer`** — the one field every customer
  surface renders — and `advisor` was an ungated field on the very endpoint
  `/chat` posts to; meanwhile `chat.html` printed authoring diagnostics
  (unbound tool types, mount overrides, node ids) to the customer in red. The
  boundary was a rendering accident, not a boundary.

  Now the suggestion fence is split out of the answer **on every run,
  whatever the audience** — and out of `token` frames, `update.output` and an
  `interrupt`'s `candidate` too, since streamed text reached a client long
  before any `done` frame existed to be cleaned. So a customer's answer cannot
  carry developer guidance because no code path puts it there, which is also
  why a model writing something fence-shaped into its own prose achieves
  nothing. `OPENSTATEGRAPH_AUDIENCE=customer` additionally caps a whole
  deployment: no request can raise itself to `developer`. What this is *not*
  is per-user authorization — see `docs/decisions/audience-boundary.md`, which
  is explicit about that limit and about why `mermaid`, `decisions` and
  `outputs` deliberately stayed on both audiences. Proved over the real
  endpoint in `backend/tests/test_audience_boundary.py`; `docs/api.md` calls
  out the difference from what it previously documented.

- **`load_workflow(checkpointer=…, store=…)` now declare the types they always
  required.** `checkpointer` is `BaseCheckpointSaver[Any] | None` and `store`
  is `BaseStore | None` instead of `Any`; `CompiledWorkflow.as_tool()` returns
  `BaseTool` instead of `Any`. No runtime behaviour changed — the same objects
  were always the only ones that worked — but a caller who was passing
  something else now hears about it from their own type checker rather than
  from a stack trace inside LangGraph. Both names are imported under
  `TYPE_CHECKING`, so `import openstategraph` stays free of langgraph.
  `model` stays `Any` on purpose: a provider string and a built model object
  are both correct.
- **A paused approval now survives a restart, and persists by default.** The
  human-in-the-loop checkpointer was one module-level `InMemorySaver` in
  `api/main.py`; a `human.approval` pause therefore died with the process, and
  the dev stack restarts on every file save. It is now
  `WorkflowServices.checkpointer` — the same assembly point that already owns
  the store and the registries, so HTTP, MCP and `load_workflow` share one
  saver instead of three wirings — defaulting to a SQLite database at
  `<workflows root>/.openstategraph/checkpoints.sqlite`. Startup states which
  one it got, in one line: `approvals persist at …`, or `approvals are
  in-memory and will NOT survive a restart`. Set
  `OPENSTATEGRAPH_CHECKPOINT_PATH` to move the file, or to `memory` to opt out
  of durability deliberately. `load_workflow(checkpointer=…)` still outranks
  everything, and a package's own `settings.checkpointer: "sqlite"` still takes
  its per-workflow file. Listed as breaking because threads are now persistent
  identities: a client reusing a fixed literal `thread_id` resumes the old
  conversation rather than starting a new one.
- **`langgraph-checkpoint-sqlite` is part of the `[server]` extra.** The
  server's default is now sqlite, and a default that needs an undeclared extra
  is a default that degrades for everybody. It did *not* move into the core
  four — it drags `aiosqlite` and the `sqlite-vec` binary wheel, which a
  `load_workflow` consumer who never pauses a run should not pay for. An
  install missing it still degrades **loudly**, naming the install line.
- **The MCP `run_workflow` tool compiles with that checkpointer too.** A
  document containing `human.approval` used to raise at compile time and return
  a stack-trace-shaped error; it now pauses properly and the tool reports the
  pause with the durable `thread_id` to resume through `/api/runs/resume`. A
  resume *tool* over MCP is still not built.
- **The worker ceiling is still one — for a different, smaller reason.**
  Checked against the package rather than assumed: `SqliteSaver` documents
  itself as *"meant for lightweight, synchronous use cases (demos and small
  projects) and does not scale to multiple threads"*, and its only write
  serialisation is a `threading.Lock` held per instance, which two OS processes
  do not share. So a second worker can now *see* the first's threads but would
  race its writes with no coordination. `Dockerfile`, `scripts/dev.sh`,
  `README.md`, `docs/adoption.md`, `docs/decisions/memory-architecture.md` and
  `docs/decisions/mcp-layer.md` all said "in-process state"; all now say this.
- **The distribution is now `openstategraph`** (was `openstategraph-backend`).
  The import package is unchanged, and the old name was never on PyPI. A
  checkout installs with `pip install -e "backend[all,dev]"` — see below for
  why the extras are now required.
- **The core is four dependencies.** `langgraph`, `langchain`,
  `langchain-core`, `pydantic`. Everything else moved behind an extra:
  `[anthropic] [openai] [ollama] [deep] [sqlite] [server] [mcp]`, plus `[all]`
  and `[dev]`. Measured: **78 → 36 distributions**, 40 with one provider. A
  consumer of `load_workflow` no longer installs a web server, an MCP SDK,
  three provider SDKs and the Google GenAI SDK to run a graph in their own
  process. Anyone wanting today's behaviour installs `openstategraph[all]`.
- **A document whose schema version is newer than the build is refused**
  (`SchemaVersionError`, naming both versions) instead of being compiled
  best-effort. Nothing in this repository is affected — every committed
  document is version 2 — but a future document previously loaded silently
  into an older build and compiled into a graph that ran and answered
  differently.

### Changed

- **Links are rigid orthogonal runs, the revise loop has a lane of its own, and
  a point you drag now survives a save** (skills-and-legibility ticket 09;
  `docs/decisions/orthogonal-routing.md`). Asked for by name: *"instead of
  spline would it be possible to have rigid flow line, which user can add points
  and drag?"* The connector is `rounded` over a `manhattan` route, with each end
  pinned to the side its port actually sits on — the same fact the curve's
  tangents carried, since `LinkView.sourceBBox` is a port's 10px hit circle once
  links attach to magnets and any "nearest side" guess degenerates to "whichever
  way the target lies". On the graph a fresh browser opens on, card crossings
  went **3 → 0** and edge crossings **6 → 2**. `rightAngle` was measured (2 card
  crossings — it does not avoid obstacles) and `metro` was measured (it produces
  diagonals, which the brief rules out, and with pinned end directions it found
  no route at all and fell back to a router that crossed 5 cards).

  **A correction this carries.** `docs/decisions/edge-legibility.md` stated that
  an obstacle-avoiding router was a paid JointJS feature, and wrote off a real
  defect on the strength of it. It is false — the free package ships
  `manhattan`, `metro`, `normal`, `oneSide`, `orthogonal`, `rightAngle` — and
  the correction is recorded in that document in place rather than edited away.

  **The back-edge needed more than a router.** `manhattan` clears every card by
  itself, but the corridor it picks for the grader's `revise` return is the band
  reserved for the tool shelf, so it then cuts across all three tool bindings.
  `AutoLayout` now places that run in a lane past the far edge of the whole
  arrangement — expressed as ordinary waypoints, so it is the same field a user
  can drag.

- **Edges carry `vertices`.** Through `EdgeModel`, the serializer, an undoable
  `SetEdgeVerticesCommand` and the backend's tolerance, so adding, dragging and
  removing a point survives save and reload. The gesture already existed —
  `linkTools.Vertices` has always been attached; the points simply had nowhere
  to live. **The schema version does not move**: `vertices` is an optional field
  an older build ignores harmlessly, which is exactly the "do not bump" case
  `openstategraph/schema.py` documents, and the compiler's indifference to it is
  now pinned by a test. Non-finite coordinates are filtered at the model's door,
  since one `NaN` would make the whole document unwritable.

  **Arrange automatically replaces every waypoint** and re-seeds the back-edge
  lanes. A hand-placed point was chosen against where the cards were; once they
  have all moved it is a point nobody chose. The discard is not silent: it lands
  in the *same* undo step as the moves and the frame re-fits, so one Cmd-Z
  restores the positions and the hand-routing together.

- **A skill arrives from the left, like every other input** (skills-and-legibility
  ticket 08; the reversal is recorded in `docs/decisions/edge-legibility.md`
  rather than quietly applied). Hours earlier the same day, `skill` was
  declared a *binding* and moved to the card's bottom edge, which took the
  Markdown File card out of the flow ranks and stopped its wire crossing the
  Text Input above it. It also left a hole: the footer legend is the card's
  complete list of ports, so an Agent went on listing `prompt`, `feedback`,
  `skill` down its left side with a dot beside only two of them — repairable
  only by styling the odd row differently, which decorates the symptom. Three
  cards feed an agent and three wires arrive; they arrive from the left.
  `skill` (and `Markdown File`'s matching output, since both ends of a wire
  must agree which axis it travels) drops its `side` and takes the default,
  declared once in `src/nodes/skillLayer.ts`.
  - **`tools` is unchanged, and the distinction is now sharper.** What makes a
    bus a bus is *many wires converging on one point* — that needs a drawn form
    of its own (the pill) and an axis of its own. A skill is one file on one
    wire; it never had that reason to leave the reading axis, only a tool's
    company.
  - **`side` stays one field.** It drives both the drawn dot and
    `isBindingEdge`'s layout classification, so moving the dot also moved the
    card back into the ranks. Splitting it into a `role` and a `side` was
    rejected: a port that was equipment for layout but drawn on-axis would sit
    on the shelf *below* its consumer while its wire entered from the *left* —
    the long way round to a dot it started beside.
  - **The accepted cost, stated:** the Markdown→Agent crossing is back. It
    belongs to the obstacle-avoiding router (ticket 09), which turns out to be
    available in the free JointJS package — contrary to the constraint the
    original decision was reasoning under. Nothing crosses the compile boundary:
    `port_specs.json` never carried `side`, so every saved `workflow.json` and
    every compiled graph is unchanged.
- **The schema tool stops pretending to be configured per table, and shows the
  database instead.** `tool.chinook-get-schema` shipped a `Table` select — a
  hardcoded list of eleven Chinook table names typed into TypeScript,
  defaulting to `Artist`. The tool that actually runs takes `table` as a
  *model* argument and declares no `configure()`, so the control reached
  nothing: it changed no run and told every reader that this node fetched
  Artist's schema. The control is gone. In its place the card shows what the
  tool can genuinely reach — every table of the wired database, read from the
  file itself through the new `GET /api/workflows/{slug}/sql-schema`, with each
  table expanding to the columns, types and foreign keys the agent gets. The
  agent sees all of them and picks; the card now says so. A document saved with
  the old `tableName` in its data still loads silently — the key is ignored, no
  field renders it, and the compiler never read it, so nothing about what a
  document compiles to changed and the schema version does not move. The
  generic `tool.sql-*` family never had the equivalent control and needed no
  change; the same endpoint covers it.
- **`CHINOOK_SCHEMA` is gone — the browser preview refuses instead of copying
  the database.** `ChinookDatabaseNode.ts` carried a second declaration of
  every Chinook table's columns and types so its offline executors could
  answer. Duplicated knowledge with no drift guard becomes wrong quietly, and a
  *schema* that is quietly wrong produces SQL that parses and answers the wrong
  question. The two schema-shaped tools now refuse in the browser preview and
  name where the answer lives, joining the honest-refusal pattern the other
  backend-only executors already follow. The query tool's `SAMPLE_DATA` stays:
  it fabricates rows, not structure, and no schema decision is taken from it.
- **Pointing OpenStateGraph at a directory no longer writes into it**
  (scale-and-adopt ticket 03). READ location and WRITE location are now
  separate questions with separate answers: `openstategraph.workflows_root`
  and the new `openstategraph.state_dir`. Inside this checkout **nothing
  moves** — state is still `<workflows root>/.openstategraph`, which is where a
  developer expects it and where `.gitignore` already covers it. Installed and
  pointed at somebody else's folder, state goes to the platform's per-user
  state directory instead (XDG `$XDG_STATE_HOME`/`~/.local/state` on Linux,
  `~/Library/Application Support` on macOS, `%LOCALAPPDATA%` on Windows),
  keyed per project so two projects never share a thread namespace.
  `OPENSTATEGRAPH_STATE_DIR` names it outright;
  `OPENSTATEGRAPH_CHECKPOINT_PATH` stays authoritative above both. A read-only
  workflows root now lists, compiles and runs, and when a write genuinely
  cannot be made durability degrades loudly rather than the process failing.
  Two writes moved with it: the email tool's dry-run outbox
  (`<workflows root>/_outbox` → `<state dir>/outbox` — a `.eml` is diagnostic
  output, not content the user authored, and it was not gitignored), and a
  package's own `settings.checkpointer: "sqlite"` file, which was `./.dev/`
  **relative to the working directory** and so created `~/.dev/` for anyone who
  ran a workflow from their home directory.

### Added

- **A project's second brain, as a *source* rather than a new scope**
  (one-chinook-honest ticket 14). The owner asked for a knowledge base for
  *the project*, which is a scope `docs/decisions/knowledge-architecture.md`
  never covered — it reasoned about a workflow's sources and a root's
  children. The answer refuses the premise of the map's open question ("one
  root store, or per-package stores with a root index?"): **there is no
  project-level store, and deliberately never will be.** A store is only worth
  writing where an agent is bound to read it, and binding is per package — one
  open document is one package is one `knowledge/` directory. A directory at
  the workflows root would be Markdown no runtime reads.

  So the project joins the escalation ladder the way every other source does,
  by **recognition from the wiring**. A `tool.sql-*` node's connection field
  means "a database is a source here"; a mount means "a child is"; a
  `tool.platform-list-workflows` / `tool.platform-describe-workflow` node
  means **"the project is"**, because a workflow holding one can enumerate and
  describe every package on the platform. `ProjectKnowledgeBuilder`
  (`source=project`) writes one *catalogue* page per package into that
  workflow's own `knowledge/`, reached by the `knowledge_lookup` it already
  has ambiently. A project's second brain is therefore the union of the
  per-package ones — **pointers, not copies**, applied to the scope that
  tempted us to break the rule.

  **The visibility gate inverts ticket 16's, and that is the point.** The
  topic set is the packages the platform tools show, minus this package, minus
  the ones this document mounts — and the gate is *imported from the tools*
  (`prebuilt_platform.visible_to_platform_tools`, promoted from `_visible` for
  this second reader) rather than restated. Ticket 16 **removed** the publish
  gate from `RootKnowledgeBuilder` because a mount compiles its child as a
  subgraph and `document_loader` consults neither flag; this builder **keeps**
  it because a platform tool enforces both. One rule — the gate belongs to the
  mechanism that reaches the destination — two opposite outcomes, and neither
  is a preference. A mounted child is subtracted because it earns the strictly
  better routing doc, which keeps invariant 5's collision machinery a backstop
  instead of something that fires on every build of a gateway.

  A catalogue doc is a different genre from a routing doc: it says *this
  exists, here is what it is for, and here is when it is the wrong answer*,
  and is instructed never to tell the reader to route into a workflow this
  document has no edge to. That last clause is what makes it knowledge rather
  than introspection — `platform_list_workflows` already answers *what exists*
  live, and a generated copy of a live enumeration would be the copy-that-rots
  this record forbids one level up. Neither live tool answers *when not to
  recommend it*.

  `RootKnowledgeBuilder` and `ProjectKnowledgeBuilder` are now siblings under
  `AbstractWorkflowPointerBuilder`, which owns the one thing they share — what
  a brief about *another workflow* is — while each concrete owns the two they
  differ on. Verified live on a scratch workflows root with a real model:
  a gateway mounting one child and seeing three others wrote one `root` doc
  and one `project` doc, zero collisions; the draft and hidden packages got
  neither; and the gateway's ambient lookup reached its own two pointers and
  refused the child's topic.

  **No skill is generated from knowledge, and the refusal is recorded.** A
  skill is *rules*, loaded into every prompt of every agent it is wired to;
  knowledge is *reference*, fetched on demand only on the path taken.
  Distilling one into the other spends exactly the budget the three-tier
  design exists to save (eleven Chinook pages in every prompt), creates a
  second lossy copy of an authority store that rots on the next build, and
  puts model output in the highest-priority editable layer — which outranks
  the inline prompt *because a human chose it*. The need underneath ("the
  agent should know the store is there") is already met by the free index tier
  and the unknown-topic menu.

- **`docs/second-brain.md` — how a developer checks that a store is right**,
  and `openstategraph knowledge list` now prints what the check needs
  (one-chinook-honest ticket 14). Ownership and staleness were recorded from
  the first build and surfaced **only** by the editor's curation panel, which
  is the wrong place for the one question someone verifying a knowledge base
  asks. The command now prints each topic's owner (`[yours]` /
  `[generated: <builder>]`) and `STALE` beside its index hint, from the same
  `knowledge_curation.list_topics` the panel uses; `--knowledge-dir` drops the
  badges, because a store outside a package has no source to recompute and
  unknown is not stale. Nothing new is recorded on disk to make this work.

  The page is the procedure end to end — build and read the four report
  lists, read the index *as the menu a model gets on a miss*, a one-line
  coverage `diff` against the source's own enumeration, following the
  provenance footer, the ablation that answers whether the store earns its
  place at all (move the directory, since seeking is ambient), and three
  checks worth pinning in `workflows/<slug>/tests/`. Its centre is the
  distinction nothing else states: **stale is not wrong**. Stale means the
  *source* moved and the doc's correctness is unknown; wrong means the source
  is unchanged and the doc misdescribes it. The fixes are opposite, and a
  claimed doc can be either.

  One latent defect fell out of it: `current_source_hashes` named
  `SqlKnowledgeBuilder` and `RootKnowledgeBuilder` literally, so any *other*
  mechanical builder's docs — a plugin's, or this ticket's own — could never
  be badged stale. It now reads the `BUILDERS` registry and filters on a
  builder's own `mechanical` flag.

- **`GET /api/workflows/{slug}/summary` — existence, asked separately from
  visibility** (one-chinook-honest ticket 21). The editor kept announcing
  *"This workflow was deleted on disk — your open copy is no longer backed by
  a saved file"* over files that were sitting right there and being served
  `200`. The cause was one endpoint answering two questions:
  `GET /api/workflows?surface=editor` returns everything **non-hidden**, which
  is correct and deliberate — it draws a picker — and `workflowFileWatch.ts`
  scanned that list for its own slug and read a miss as a deletion.
  `concierge` and `workflow-architect` are both `hidden: true`, so opening or
  drilling into either produced the warning one poll later, every time.

  The listing keeps its job and now says so in `docs/api.md`: **absence from
  it means no surface advertises the package, never that the package is
  gone.** The new endpoint answers the other question for one slug — every
  package the store can name, hidden ones included and flagged `hidden`, with
  **404 the only answer that means gone**. A package present but unreadable
  (a file caught mid-write) comes back with `findings` and an empty
  `saved_at`: damaged, not deleted. A malformed slug is a 422, so a typo
  cannot be mistaken for a deletion either.

  The file watch polls it for its own slug, and `decideFileWatchAction` now
  takes one row or `null` instead of a whole listing. The genuine-deletion
  warning is unchanged and pinned from both sides —
  `src/app/workflowFileWatch.test.ts` asserts a hidden workflow baselines
  normally *and* that `null` still warns; `backend/tests/test_api.py` walks a
  package from listed, to hidden-but-summarised, to deleted-and-404. Two
  further false positives went with it: a hidden package could never record a
  `savedAt` baseline at all, so it also never noticed a *real* external change,
  and an unreachable backend stays an `Err` rather than becoming "deleted" —
  "I could not ask" is not "the answer is no".

  *Correction to an earlier record.* This toast was observed during ticket
  09's verification, confirmed against a present file and a 200 response, and
  filed as "not investigated". That was the wrong call; it was a reproducible
  defect in the seam, not an anomaly.

- **Exactly one second brain per workflow, and a rule for where every
  build-time action lives** (one-chinook-honest ticket 16). The owner asked to
  drag and drop a second-brain builder, one per workflow — which collides with
  the knowledge record's invariant 3, *build-time only*: everything draggable
  on this canvas compiles to something, and a builder compiles to nothing.

  Nothing new is draggable. The **Knowledge atom is a run-time node hosting a
  build-time affordance** — it compiles to the `knowledge_lookup` tool an
  agent really calls, while the "Build second brain" button beside it is not
  part of the compile at all, so invariant 3 is now structural rather than
  conventional: there is no compile path from the button, and no trainer can
  run during a customer run because nothing in the emitted graph can reach
  one. The atom says so on its own card and in its palette description, rather
  than only in a decision record.

  The atom declares `maxInstances: 1`, and the existing mechanism already
  counted the right thing — `model.countOfType` is over the **open document**,
  and one document is one package is one `knowledge/` directory. That also
  answers the collision question mechanically: a mounted child is a *different*
  document, so a root and a `data-analytics` team may each hold one. Verified
  end to end against a scratch workflows root — compiling a real
  `workflow.subgraph` mount produced two ambient knowledge bindings, the
  parent's agent reaching only the parent's store and the child's only the
  child's.

  The question generalises, and is recorded as a pattern rather than one
  node's special case: `docs/decisions/build-time-affordances.md`. **A
  build-time action is an affordance on the run-time declaration it acts upon;
  where there is none — publish, an eval run — it is a panel action scoped to
  the open workflow. It is never a node of its own.**

- **Reasoning effort, on every node that drives a model, degrading loudly on
  every model that has none** (one-chinook-honest ticket 12). A **Reasoning**
  picker sits directly beneath the model picker on the Agent, Router, Grader,
  Supervisor and Worker, and it is one declaration — `src/nodes/effortField.ts`
  gives it to any definition that already carries the model field, at the
  catalogue's registration point, so a sixth model-driven family cannot ship
  without it. Declaring it five times is the exact defect `modelField.ts` was
  created to undo, and doing so again would have been a slower way to make the
  same mistake. The backend reads it in `_resolve_model` — one method, the one
  place a model becomes a model, asserted by a test that refuses to let a
  factory apply it on its own.

  **The interesting half is the degradation, and there are two of them.** A
  reasoning parameter meeting a model that has none fails in two ways that look
  nothing alike: OpenAI *rejects* it on a non-reasoning model, killing a run for
  a setting nobody meant to be load-bearing, while `ChatOllama` — this project's
  zero-configuration default — has no `reasoning_effort` field at all and drops
  it with no error, no warning, and no trace in `model_dump()`. So neither
  "pass it through" nor "catch the exception" is the fix. `openstategraph/
  reasoning.py` sends the parameter only where it is known to be carried, and
  every refusal is stated on the run's `warnings` — the same channel that
  reports an unresolved tool, so it reaches the run response, the CLI and the
  MCP preview with no per-surface plumbing.

  **Capability is discovered, never listed**, because a hardcoded set of
  reasoning-capable model ids is wrong within a month. Two real sources, each
  answering a different question: the partner package's own `reasoning_effort`
  field annotation says whether the *integration* can carry the value and which
  spellings it accepts (`langchain-core>=1.5.2`'s standard parameter), and
  `model.profile["reasoning_effort_levels"]` — models.dev data shipped inside
  each partner package — says whether *this model* reasons and at which tiers.
  Both move with an installed-package update rather than with an edit here.
  A silent profile is treated as **unknown, not as a refusal**: `claude-haiku-4-5`
  reasons and publishes no tiers, and reading that as "no" would deny a setting
  that works.

  **The picker states which of the three it is.** A model whose provider
  declares tiers gets exactly those; a model discovered at run time, where the
  editor genuinely cannot know, gets the `low`/`medium`/`high` that every
  provider spells the same way — the intersection, not the union, so the
  fallback is never the riskiest option on the list; and a model known not to
  reason gets **no tiers at all**, one line naming the model instead. That last
  case is the house rule the Table listbox and the five model-less pickers are
  both in this file for: a control that reaches nothing is worse than no
  control. Defaults to *Model's default*, which sends nothing — seeding a tier
  would have changed how every existing workflow runs while looking cosmetic,
  since providers disagree about their own default. `SelectFieldSchema.options`
  may now be a function of the node's data, mirroring `INodeDefinition.ports`,
  which is what lets one field say three different things.

  Two things found on the way, both fixed here. `CompletionRequest.effort` had
  existed on the provider interface since the browser adapters were written,
  documented as "reasoning depth, mapped per provider" — and nothing ever set
  it: `AnthropicProvider` hardcoded `output_config: { effort: 'high' }` and the
  other two adapters sent nothing at all. It is a real control now, and each
  adapter drops a tier its vendor does not have rather than forwarding it into
  a 400. And `defineNode`'s `create` closes over the definition it builds, so
  extending a definition by spreading it gave the palette the new field and
  every *node instance* the old list — invisible to a test that inspects a
  definition, visible immediately in the running editor, which is where it was
  found. `extendFields` is now the supported way to add to a definition, and it
  says why at the seam.

- **All five model-driven node types now take a skill, and share one
  extend/replace switch** (skills-and-legibility ticket 05,
  `docs/decisions/skill-layer.md`). The Router, the Grader and the Supervisor
  gained the `skill` input the Agent and the Worker already had — the compiler
  had been reading `plan.skill_bindings` for all five, so three of them offered
  no way to wire the thing they were ready to read. Both halves are declared
  **once**, in `src/nodes/skillLayer.ts`: the port (an ordinary left-hand
  input, beside `prompt` and `feedback` — see the Changed entry below, which
  reverses the binding treatment this entry originally described) and
  `rulesModeField()`, which is the Grader's `criteriaMode` generalised. A saved
  document carrying `criteriaMode` is rewritten to `rulesMode` as it loads,
  before schema defaults are merged, so it keeps its behaviour exactly and
  re-saves under one key instead of two that could disagree; the backend's
  `criteriaMode` fallback stays for documents the editor has never opened. The
  mode rides on the card where the rules do — Router and Grader — and in the
  inspector where they do not.
- **`port_specs.json` now emits `accepts_skill`**, asserted against the
  compiler's own factory table in `backend/tests/test_skill_layer_contract.py`
  the way `drives_model` already is: both sides read from source, neither from
  a hand-kept list. It earned its place on the first run — it caught that the
  Worker's builder never called `_replaces_rules`, i.e. that a `rulesMode`
  select on a Worker card would have reached nothing.

- **A mount now announces itself before a word is read** (skills-and-legibility
  ticket 03). A Team or Workflow card carries a `graph` chip beside its
  subtitle and a tinted header band, so a card that stands for another
  workflow's whole graph is visibly a different *kind* of thing from an atom.
  The chip states the **kind**, never the shape: "there is a graph in here" is
  true of every mount and knowable from the node type alone, whereas a badge
  reading *loop* would be a lie on every `workflow.subgraph` mount and on any
  Team whose grader has no wired `revise` edge. That claim already has one
  honest owner — `summarizeComposition` derives it, and the census line prints
  "loops until its grader passes" only when it holds. Verified live on both
  kinds pointing at the same child: identical `graph` chips, and the loop
  sentence on the Team alone.
  - **One badge vocabulary, not two.** The existing `workflow` scope chip and
    the new mount chip are the same `.node__chip` — same size, same voice, same
    line. The mount chip takes the card's own accent tokens
    (`--accent-tint` / `--accent-on-tint`), which `theme.css` already rebuilds
    from alpha on dark, so nothing here invents a colour.
  - **The wordless half matters more than the word.** A chip is legible only up
    close; the canvas is read at zoom levels where no caption survives. The
    tinted header band does survive, and costs no space at all.
  - Which node types are mounts is now declared once, in
    `src/view/nodes/mountKind.ts`, and both the card and the body registry read
    it — a card can no longer be badged as holding a graph while showing no
    composition, or the reverse.

- **A wired Skill now composes into a node's RULES, and the output contract
  still comes last** (skills-and-legibility ticket 04;
  `docs/decisions/skill-layer.md` is the contract). A skill file is Markdown —
  optionally with the Agent Skills specification's own `name`/`description`
  frontmatter, which is parsed and kept out of the model's prompt rather than
  pasted into it. `SystemPrompt` gained a third rules layer, so the block a
  model sees is `default rules → inline systemPrompt → wired skill`, and the
  locked preamble, generated context and output contract sit around it exactly
  as before. All four prompted families compose it — agent (and therefore
  worker), router, grader, supervisor — so ticket 05 has only to declare the
  port and the field.
  - **This corrects a real inversion.** A wired skill used to ride in
    `context`, i.e. *below* the rules — and later text wins ties, so wiring a
    skill into a prebuilt agent quietly lost every disagreement with the
    inline prompt it was meant to override. The package's ambient
    `skills/*.md` stay context, deliberately: they are house style for every
    agent in the package, not a choice about one node.
  - **Both supplied is decided, not silent.** Inline prompt and wired skill
    *concatenate*, inline first; `rulesMode: replace` keeps the topmost
    supplied layer and drops the ones beneath it. An empty layer falls back
    rather than wiping.
  - **`criteriaMode` is generalised into `rulesMode`, not duplicated.** Same
    verb, same layers, one more layer above — and with no skill wired the
    behaviour is byte-identical to before, so saved documents and shipped
    templates are unaffected. The backend reads `rulesMode` and falls back to
    `criteriaMode`; the fallback goes when nothing carries the old spelling.
  - **One behaviour change worth naming:** a skill wired to a Worker now
    *extends* its built-in tool directive instead of replacing it. That
    directive is what stopped a worker answering a database question from
    parametric memory, and a skill author has no reason to restate it;
    `rulesMode: replace` drops it deliberately.

- **One example, and it is the whole story: `chinook-assistant`**
  (one-example ticket 01). A horizontal, eight-node text-to-SQL assistant over
  the bundled Chinook database. A router splits the five intents a real
  assistant meets — a data question, a greeting, an off-topic question, a
  general-knowledge question, and something that needs the live web — and each
  branch goes somewhere different: the data branch into a mounted analyst, the
  web branch to an agent holding the search and fetch tools, the rest to a
  conversational agent. Every node is explainable in one line, which was the
  bar it had to clear.
  - **The analyst is a `workflow.subgraph`, not a Team, and that is the
    decision worth recording.** A Team means a supervisor planning a fan-out
    over workers; here there is exactly one worker role and one verifier, so a
    supervisor would spend a model call per question planning a fan-out of one.
    The mounted `chinook-nl-to-sql` package is agent → grader → revise: the
    same retry semantics, without the planner. A Team earns itself when the
    subtasks genuinely differ and can run at once — which is the shape the
    deleted `page-analytics` had, and this workflow does not.
  - **Domain knowledge is knowledge, not a persona.** What a "domain expert"
    agent would recite — that revenue is `UnitPrice × Quantity` from
    `InvoiceLine`, not the pre-rounded `Invoice.Total` — lives in the analyst's
    `knowledge/`, retrieved on demand, editable, versioned, costing no model
    call and unable to hallucinate.

- **An evaluation harness that measures the thing the field measures**
  (one-example ticket 02): `openstategraph eval ./workflows/chinook-nl-to-sql`,
  the `openstategraph.evaluation` package, and `docs/evaluation.md`.
  - **Execution accuracy**, not string similarity and not "an LLM said it was
    good": the generated SQL and the gold SQL run against the same database and
    their **result sets** are compared. It is what Spider's official test-suite
    evaluator and BIRD both report, and `evaluation/denotation.py` is a
    faithful port of upstream's `result_eq` — bag semantics, order significant
    only when the gold query says `ORDER BY`, column order insignificant. Two
    deliberate deviations from upstream, both toward a reproducible number, are
    named in the doc rather than left for a reader to discover.
  - **36 golden Chinook cases**, graded easy/medium/hard, and **five of them
    are unanswerable on purpose** — a question about data the schema does not
    hold, one that needs the live web, one that is just a greeting. A harness
    that only asks answerable questions cannot tell a workflow that knows its
    limits from one that confabulates, and confabulation is the failure this
    product exists to prevent.
  - Whether an LLM judge adds anything for *phrasing* stays deliberately
    unanswered until the first scorecard shows where the failures actually are.

- **Past runs — history the editor can read** (one-example ticket 03).
  `GET /api/threads` and `GET /api/threads/{id}` read what the checkpointer
  already stored, filtered by workflow, user or session; `RuntimeClient`
  exposes them as `pastRuns()` / `pastRun()`; and a **History** toggle in the
  Chat panel lists them, newest first, expanding to the run checkpoint by
  checkpoint.
  - **No second store, and no new node type.** Identity already rode in
    `configurable` and already namespaced memory, and LangGraph already
    checkpoints every superstep — so the missing piece was never storage, it
    was a way to *ask*. The one thing added to the graph is the
    `tool.session-identity` tool, which takes no arguments: a prompt can read
    who is asking, and a model can never claim to be someone else.
  - **"Past runs", never "replay".** Opening one calls no model and no tool.
    A run parked at an approval says so and points back at the chat, so there
    is exactly one way to continue a run rather than two.

- **A published API contract, so "build your own UI" is checkable**
  (scale-and-adopt ticket 05). Both shipped surfaces already went through
  public HTTP endpoints, but nothing said so in a form a stranger could read:
  no OpenAPI document, no guide, no example.
  - **`docs/openapi.json`** is generated from the app and committed, so an
    endpoint changing shape appears in a pull-request diff next to the code
    that changed it, and anyone can run
    `npx openapi-typescript docs/openapi.json` without booting a server first.
    Regenerate with `python3 scripts/generate_openapi.py`. Two gates keep it
    honest: a byte comparison on every backend test leg, and a
    `generated-openapi` CI job that regenerates and diffs — the same
    belt-and-braces `port_specs.json` already had. The same suite fails an
    endpoint with no description, or a JSON response with no named schema;
    `/api/health`, `/api/node-contracts` and `/api/workflows/{slug}/graph`
    returned bare dicts and now have models.
  - **`docs/api.md`** carries the half OpenAPI structurally cannot: the SSE
    event vocabulary of `/api/runs/stream`, `/api/runs/resume` and
    `/api/events`, the guarantee that exactly one of `done`/`interrupt`/`error`
    ends every stream, and the five calls a custom chat needs with request and
    response examples captured from a running server. Plus a complete
    forty-line client, `docs/examples/minimal-client.html`, verified in a
    browser against a live server.
  - **`OPENSTATEGRAPH_ALLOWED_ORIGINS`** lets a browser client on your own
    origin call the API. Comma-separated, **added** to the editor's dev
    origins rather than replacing them, and `*` is refused rather than
    silently dropped — this process holds provider keys.
  - **No npm client, deliberately.** A package is a version to maintain for a
    surface a `fetch` covers, in one language out of three people ask in, and
    it would still hand you an untyped `fetch` for the three streaming
    endpoints that matter most. The schema plus the example is the answer.

- **Named templates, shipped inside the wheel** (scale-and-adopt ticket 04). A
  `pip install` user started in an empty folder with nothing to imitate: the
  two example workflows live in this repository and were never in the package.
  Three starting points now ship as ordinary package data under
  `openstategraph/templates/`, and `openstategraph new --list-templates` prints
  them:
  - **`minimal`** — input → agent → output. **Still the default**, deliberately:
    a stranger's first run must cost one model call and contain nothing that
    can reject the answer.
  - **`routed-qa`** — input → router → agent → grader → output, with a second
    branch that skips the grader. The shape most assistants end up with, and
    the one that teaches branches, the revise loop and typed feedback ports.
  - **`team`** — the existing supervisor + worker + grader package, now reached
    as `--template team`.

  They are **data files, not Python builders**: a template is a `workflow.json`,
  and the person about to own one should be able to read it first.
  `openstategraph new my-flow --template routed-qa` works from an empty
  directory on a machine that never cloned this repository — the wheel-contents
  check in `scripts/clean_install_proof.sh` asserts the files are in the
  artifact, and the proof scaffolds, validates and compiles **every** template
  from the installed wheel. Each scaffolded package now gets an `AGENTS.md`
  written for its own shape: what was created, and the obvious next step.

  A template is a **scaffold input** — it produces a document and stops
  existing. It is not a node type beside Team and Workflow, and no saved
  document records which template made it.

  **`openstategraph new --team` is deprecated but still works**, as an alias
  for `--template team`; it prints one line naming its replacement. The command
  line follows the Tier 1 policy, so it is not being removed in this release.
  An unknown `--template` exits **2** with the valid names — a typo in a flag
  is a usage error, and CI must be able to tell it from a failed run.
- **`GET /api/templates`, and the editor's New Workflow picker uses it.**
  "Start from" in the Workflows panel offers `Blank canvas` plus the same three
  templates, rendered by the backend from the same catalogue `openstategraph
  new` reads — one list, not two. Blank stays the editor's default, because a
  canvas may legitimately be empty while a scaffolded *package* must run.
- **`Workflows` — a catalogue, so a directory is named once** (scale-and-adopt
  ticket 02). `load_workflow(path)` is the right shape for one package and the
  wrong shape for twenty: the root is restated at every call site, and there is
  no way to ask what is in a directory without compiling it.
  `Workflows(root, **defaults)` has exactly four members — `.root`, `.list()`,
  `.published()` and `.load(slug)` — and `.load()` returns the same
  `CompiledWorkflow` through the same `load_workflow`, so there is no second
  wiring path. **Listing never compiles**: it reads one `workflow.json` per
  package through the store's existing traversal, imports neither LangGraph nor
  LangChain, and needs no API key. A package whose `workflow.json` will not
  parse comes back as a **row carrying `error`** rather than an omission or an
  exception — the HTTP listing still omits it, because a customer surface must
  not show rubble, but "what have I got" is exactly the question you ask when
  something is broken. `.published()` mirrors `?surface=chat`.
  `load_workflow(path)` is unchanged.
- **`workflows_dir:` in `openstategraph.yaml`.** The workflows root now
  resolves through all four layers of the project-wide precedence rule —
  convention `./workflows` < config file < `OPENSTATEGRAPH_WORKFLOWS_ROOT` <
  the explicit argument — with each adjacent pair pinned by its own test. A
  relative value is resolved against the **config file**, never the working
  directory, so one committed line cannot mean a different directory per
  developer. There is deliberately no module-level setter.

- **The wheel carries the canvas** (scale-and-adopt ticket 01). We called this
  a *visual* workflow builder and shipped 276 KiB of Python with no UI: the
  canvas existed only for someone who cloned the repository or ran Docker.
  `npm run build`'s output now ships as package data through a hatchling build
  hook (`backend/hatch_build.py`), so `pip install "openstategraph[server]" &&
  openstategraph serve` opens the real product on a machine that has never seen
  the repository — editor at `/`, customer chat at `/chat`, API under `/api`,
  one process, one origin, one workflows directory. Sourcemaps are excluded;
  the measured cost is 2.7 MB of a 2.9 MB wheel (1,553 KiB editor + 952 KiB of
  Mermaid for the `/chat` flow view) against the ~72 MB a `[server]` install
  already puts in `site-packages`, which is why it rides in the main wheel
  rather than a separate `openstategraph-editor` distribution. A build with no
  editor anywhere now **fails** instead of quietly producing a canvas-less
  "visual builder"; editable installs stay exempt, so the contributor path
  needs no Node.js.
- **`openstategraph serve` grew the port behaviour a first five minutes needs.**
  No flag takes 8000, or the **next free port** if 8000 is busy — running two
  copies is a normal thing to want and `Address already in use` is not an
  answer to it. `--port N` means exactly N and fails with the way out (`try
  --port 0`). `--port 0` lets the OS choose. In every case the URLs it actually
  landed on — editor, chat, health — are the last thing printed before the
  server's own log, flushed, so a script or a supervisor can read them.
  `--host` defaults to `127.0.0.1` and the help text says why it is not
  `0.0.0.0`; `--open` launches a browser and is off by default.
- **A source checkout that never ran `npm run build` gets a sentence, not a
  404.** `serve` there serves a page at `/` (503) naming the two ways out. A
  bare 404 is indistinguishable from a broken install, which is the failure
  this replaces.
- **The clean-install proof now proves the product, not just the compiler.**
  After installing the wheel in an empty venv outside the checkout, it starts
  `openstategraph serve --port 0`, waits for readiness and asserts `/` is the
  editor SPA, `/chat` is the chat page, `/api/workflows` is JSON and
  `/chat/mermaid.js` is served from the wheel. Without it the canvas could
  silently stop shipping and everything else would stay green.

- **`openstategraph.extensions.reset_entry_point_cache()`**, and with it a
  process-lifetime cache covering **all three** entry-point groups rather than
  one. Entry-point discovery re-walks every installed distribution's metadata
  on every call — about 12 ms per group on a development checkout. That cost
  was previously memoised for tools only, at a call site in `api/registries.py`,
  leaving `entry_point_knowledge_builders` (11.99 ms → 0.0005 ms) and
  `entry_point_providers` (11.84 ms → 0.0005 ms) paying it in full;
  `providers.load_provider_catalogue()` went 12.07 ms → 0.004 ms end to end.
  The cache now lives in `extensions`, which owns the mechanism, and importing
  that module is still free of any `sys.path` scan. Only a `pip install` can
  change the answer, and that means a restart — except in a test suite, which
  is what the new public reset is for. `api.registries.reset_process_tool_layer`
  keeps working and now clears every group.
- **CI runs the Python versions the package advertises.** The classifiers claim
  3.11, 3.12 and 3.13; CI ran 3.12 and only 3.12, so two thirds of the promise
  on the PyPI page had never executed a line of this code. The backend job is
  now a matrix over the floor and the ceiling of that claim (3.11 and 3.13),
  each leg running the full suite and the coverage ratchet, with ruff and mypy
  on the floor leg — where `target-version` and `python_version` are both pinned
  anyway. `backend/tests/test_python_support.py` parses both `pyproject.toml`
  and the workflow file and fails if the claim and the matrix disagree in either
  direction, so widening one without the other cannot merge.
- **A tool an installed distribution ships now appears in the editor palette**
  (register PK-06). `pip install`-ing a plugin has made a tool *bindable* since
  0.3.0's entry-point work, but nothing put it in the palette, so nobody could
  wire the thing they had just installed — "extend without forking" was half a
  promise. `GET /api/workflows/{slug}/capabilities` now also reports
  `plugin_tools` (name, node type, description, argument schema, the
  distribution that shipped it, and the card fields the tool declares) sourced
  from the same cached registry layer `build_tool_registry` binds, so the
  palette can never offer a tool the runtime lacks. A plugin's card is
  app-scoped — available in every workflow, distinct from the "This workflow"
  section — and a plugin that replaces a built-in says so on the card and in a
  warning.
- **`openstategraph.abc.ToolField`** — the declaration a plugin author writes to
  get controls on their tool's card (`node_fields` on `BaseTool`), read by
  `configure()` at runtime. One declaration, two consumers, no hand-mirrored
  type across the boundary. A third party cannot add a TypeScript file to this
  repository, so this is how they get a configurable card.
- **`warnings` on the capabilities response** — the half-authored error. A tool
  that exists in Python but has no editor card (no node definition, no plugin
  declaration) is bindable and invisible, and used to produce no message
  anywhere; it is now named, with both ways to fix it, and surfaced in the
  palette. `extensions.Discovered` gained a `sources` field
  (`node_type -> distribution`) so a capability can name who shipped it; the
  loader already computed it.
- **A type gate for the backend: `mypy`, configured in `backend/pyproject.toml`
  and run in CI beside `ruff`.** Chosen over pyright because the backend CI job
  is Python-only and pyright needs Node.js in it. Nine strictness flags are on
  and clean — including `disallow_untyped_defs`, `disallow_any_generics` and
  `warn_return_any` — which is what makes the checks reach inside function
  bodies at all. It caught 35 real typing defects on the first run, among them
  a `list[str]` parameter on `Router` that narrowed its base's
  `list[str | dict | Branch]` (a Liskov violation an adopter passing `Branch`
  objects would have hit), and a table of four ABCs whose only inferred
  supertype was `ABCMeta`, so reading `.PREAMBLE` off it was unchecked.
  `warn_unused_ignores` is deliberately off: one ignore's necessity depends on
  whether the `[mcp]` extra is installed, and a gate that passes in CI and
  fails in a lean checkout is worse than the ignore it polices.
- **`load_workflow` and `CompiledWorkflow` are context managers**, and
  `CompiledWorkflow.close()` releases the sqlite handles the load opened. A
  script that loads one workflow and exits never needed it; a service that
  loads them on demand did.
- **The provider set is open: `openstategraph.providers` + the
  `openstategraph.providers` entry point group.** Adding a vendor was three
  literal lists that had to be edited together and never were — an
  `if os.getenv(...)` chain in `resolve_model` (so a fourth vendor could never
  be the default), a four-name `ACCEPTED_CREDENTIAL_KEYS` frozenset (so its key
  was *silently dropped* from a run request), and a five-prefix
  `PROVIDER_EXTRAS` dict (so its missing package produced no install hint).
  All three now derive from one `ProviderCatalogue`. A third party registers a
  `ProviderSpec` with a `pyproject.toml` stanza and no fork; the bundled three
  go through the identical `register()` with no privileged field, so anything a
  built-in can do a plugin can do. Precedence is
  built-in < installed plugin < config file.
- **`openstategraph.yaml` — a versioned config file, secrets excluded by
  construction.** Declares which providers exist, their models and the default;
  schema-validated with pydantic, `extra="forbid"` so a typo is refused rather
  than ignored, and errors that name the file and the field or line. It can
  never hold a credential: a key-shaped *field name* and a key-shaped *value*
  are both rejected, each with a message pointing at `.env`. It may name the
  environment variable holding a key, which is the useful half without the
  secret. YAML because PyYAML already ships transitively with `langchain-core`
  — so it costs no distribution — and because a file meant to be edited by a
  human or a coding agent needs comments; `openstategraph.json` also works.
  Precedence, documented and tested pair by pair:
  `config file < environment < workflow settings.model < node's own model <
  caller's model= argument`.
- **`errors.MissingProviderKey`** — naming a provider whose key is unset now
  fails at resolution with the exact fix (`set ANTHROPIC_API_KEY in .env — see
  .env.example`) instead of the vendor SDK's own error, which names its own
  variable and knows nothing about this project's `.env.example`.
- **`openstategraph providers` and `openstategraph env-example` CLI
  commands** — what is registered and whether it is configured (names only,
  never values), and the generated provider block of `.env.example`. That block
  is produced from the registry, and a test asserts the committed file matches
  it exactly, so a newly registered vendor documents itself.
- **`load_workflow(..., store=, tools=, functions=, middleware=)`** — the
  remaining collaborators are now the caller's to supply, closing the
  asymmetry where `checkpointer` was injectable but its sibling the long-term
  memory `Store` was built internally from the environment. `store` is the
  object the prebuilt memory tools read and write; `tools`/`functions`/
  `middleware` are explicit mappings keyed exactly as a document names them
  (`{"tool.my-thing": instance}`, `{"function.my_fn": callable}`,
  `{"summarization": middleware}`). **Precedence: built-in < installed plugin
  < the package's own files < these arguments** — an explicit mapping is the
  most specific source, and a collision with a discovered capability is a
  deliberate substitution, so it is never reported on `.warnings`. All four
  are keyword-only with `None` defaults, and `None` means exactly what it
  meant before the parameter existed. `docs/adoption.md` has the table.
- **`openstategraph.errors`** — `OpenStateGraphError` and the failures the
  loader raises. Every class also inherits the builtin it used to be
  (`PackageNotFound` is a `FileNotFoundError`, `InvalidPackageName` is a
  `ValueError`), so existing `except` clauses keep working.
- **`openstategraph.abc` exports the ladders** — `ITool`/`BaseTool`,
  `IRouter`/`BaseRouter`, `IGrader`/`BaseGrader`, the agent nodes, the
  orchestrator, `SystemPrompt`, `MiddlewareSlotTable`. The package's
  `__init__.py` was empty; the deep module paths still work.
- **`openstategraph.schema`** — `normalize_document`, `migrate_document`,
  `document_version`, `SCHEMA_VERSION`, `MIN_SUPPORTED_VERSION`, `MIGRATIONS`.
  One seam for envelope-peeling and the version policy, replacing the private
  `api.registries._document_of` that the public loader imported and the
  second, subtly different normalizer in `mcp_server`.
- **`openstategraph.__version__`**, from the installed distribution's metadata.
- **The `openstategraph` console script** (ticket 08) — `run`, `validate`,
  `graph`, `new`, `knowledge build|list`, `serve`, `mcp`. argparse only, so it
  adds nothing to the four-package core, and every command wraps a seam that
  already existed. Exit codes are fixed: `0` success, `1` run or validation
  failure, `2` usage error, `3` a required extra is missing (the message names
  the `pip install` line). `openstategraph run ./workflows/my-thing "…"` is now
  the shortest path from a package to an answer.
- **`RunResult`** — what `CompiledWorkflow.ask()` returns. It **subclasses
  `str`**, so it *is* the answer and every existing consumer is untouched
  (`.strip()`, `+`, `json.dumps`, `re.search`, `isinstance(x, str)`), while
  `.answer`, `.decisions`, `.outputs`, `.warnings` and `.attempts` remove the
  need to drop to `.graph.invoke()` with hand-seeded state to find out why an
  answer was wrong. The trade-off, and the plan to revisit it at 1.0, are
  recorded in the module docstring and `framework-packaging.md` §3.2(b).
- **`CompiledWorkflow.as_tool(name=…, description=…)`** — a whole workflow as
  one LangChain `StructuredTool`, so a team already on `create_agent` adopts
  without restructuring. Adapted at the seam, never subclassed. The workflow
  runs as its own graph and sees only the question: the same subagent
  isolation this codebase already states. There is deliberately **no**
  middleware equivalent — it would need a routing policy, and a router is
  something we already express as a document.
- **`load_workflow(..., knowledge_dir=…, trace_file=…)`** — both keyword-only,
  both defaulting to today's behaviour. `knowledge_dir` overrides the
  `<package>/knowledge` convention for knowledge shared between packages or
  living outside the repository; `trace_file` appends one JSON line per run
  (question, slug, decisions, attempts, warnings, duration, and the answer's
  **length** — never its text). An unwritable trace path warns and never fails
  the run.
- **`openstategraph.scaffold`** — the workflow/team scaffold, moved out of
  `scripts/` so it ships in the wheel. `scripts/new_workflow.py` and
  `scripts/new_team.py` keep their exact command lines and now call it, which
  is what stops `openstategraph new` from becoming a second copy that drifts.
- **`openstategraph.extensions`** — extension without forking (ticket 05). A
  third party ships their own distribution with
  `[project.entry-points."openstategraph.tools"]` (or
  `"openstategraph.knowledge_builders"`) and their tools register on install,
  with no edit to this repository. Layered as a third discovery source under
  the two that existed: **built-in < third-party < workflow-local**, so a
  plugin may replace a bundled default and a package's own `tools/` still wins
  over anything in the venv. Every entry point loads in its own jail — a
  failure logs one WARNING **naming the distribution**, lands on
  `CompiledWorkflow.warnings`, and never stops the other plugins. Nothing is
  enumerated at import time, and `OPENSTATEGRAPH_DISABLE_PLUGINS=1` switches
  the whole mechanism off for a reproducible run. There is deliberately **no**
  `openstategraph.functions` group — see `docs/building-an-atom.md`.
- **`docs/what-is-this.md`** — the positioning page. What OpenStateGraph is
  (a document format, a compiler for it, and the node semantics it emits —
  with the canvas, HTTP API and MCP layer as *optional surfaces*), what it adds
  over raw LangGraph, what it deliberately does not own, the dependency picture
  measured rather than estimated, the escape hatches, and when not to use it at
  all. The site, the README and `docs/adoption.md` no longer imply the checkout
  is the only path.
- **`docs/stability.md`** — the three tiers, what is deliberately not public,
  and the deprecation policy. Pre-1.0, a breaking change bumps the **minor**,
  never the patch.
- **A release pipeline with a gate that cannot be waved through.**
  `scripts/clean_install_proof.sh` builds the wheel and sdist, runs `twine
  check`, installs into an **empty venv outside the checkout**, and drives the
  CLI and `load_workflow` with `cwd` outside the repository and `PYTHONPATH`
  empty. It runs on every pull request (`clean-install` in CI) and gates
  publication: `.github/workflows/release.yml` publishes on a `v*` tag —
  pre-release tags to TestPyPI, final tags to PyPI — and `publish` **needs**
  the proof. Required repository secrets: `PYPI_API_TOKEN`, and
  `TEST_PYPI_API_TOKEN` for pre-releases.
- **`py.typed`** (PEP 561), `backend/LICENSE`, `backend/README.md`,
  classifiers, project URLs and a `[build-system]` table — the wheel had none
  of these.

- **A mounted workflow says what it achieves, not only what it contains.**
  A **Data Analyst** card announced `chinook-nl-to-sql · 1 agent · 1 grader ·
  3 tools` — an inventory of machinery, which is not what a reader wants from
  a box they cannot see into. Packages now carry `settings.purpose`, one
  sentence, and every mount of a package shows it above the census. Authored
  once in the child rather than per mount, because it is a fact about the
  package: two mounts describing one workflow two ways would leave at least
  one of them wrong, and per-*mount* difference is what `overrides` is for.
  A package that never wrote one shows the census alone — an invented summary
  that mis-describes what runs is worse than a quiet card.

- **A skill wired to a Worker no longer deletes its tool directive.**
  `_worker` composed the wired text as `wired or default` — `replace`
  hardcoded, and the one prompted family whose `rulesMode` reached nothing. The
  directive is now the `default_rules` layer the decision record names it as,
  so a skill is *added* to it and only `rulesMode: "replace"` drops it. That
  directive is what stopped a worker answering a database question from
  parametric memory, so losing it silently was the expensive direction. Wired
  skill text is also passed through `skill_text()` here now, so YAML
  frontmatter on a picked `SKILL.md` never reaches the model.

- **An agent's card says what the agent is for.** `systemPrompt` is
  `onCard: false` — correct for a paragraph of rules, and the reason a
  carefully instructed agent read on the canvas exactly like an empty one.
  Reported as a design question (*"the main agent doesn't have any skill
  saying what to do — is that by choice?"*); it was not, the instruction was
  simply never shown. Model-driven cards now carry a one-line intent
  **derived** from the first sentence of the text that will actually be sent
  (`promptIntent`), so there is no second field to write and none to fall out
  of step with the prompt. Applies to the Agent (`systemPrompt`) and the
  Worker (`role`); a Router already shows its `rules` and a Grader its
  `criteria`.

- **Two unrelated things were both called Concierge** — `chinook-assistant`'s
  tool-less chat agent, and `workflows/concierge/`, the gateway that fronts
  every published workflow. The agent is now **Front Desk**, which is what its
  own prompt calls it. A sweep of every shipped package for titles colliding
  with a workflow name found no others (a mount titled after the workflow it
  mounts is naming, not colliding).

### Fixed

- **The run followed the router without ever framing it — the tallest card
  was the one the camera refused to enlarge** (one-Chinook ticket 19,
  `src/canvas/follow/followDecision.ts`). Reported from live use as *"any node
  in focus should be fit/zoomed in — the glow works, but the Intent/router
  does not get zoomed in"*. `focusZoomFor` sized a focused node to fill
  `CANVAS.follow.fill` of its **constraining** axis, `min(width, height)`. But
  `NODE.width` is fixed for every card while height is content: measured in the
  running editor on `chinook-assistant` at a 768×952 canvas, the cards run from
  252×100 (a tool) to **288×1068** (Intent — five branch rows, a rules
  textarea, a model picker, a rules-mode select). The height term therefore put
  the router's ideal scale at **0.37** while its neighbours got 1.03–1.25, so a
  run starting zoomed out magnified every node *except* the one with the most
  to read, and a run starting at 1:1 actively zoomed **out** to a third to fit
  1068 units of card on screen. The dead band was not the mechanism; the ideal
  itself was wrong.

  Readable is now a **width** rule — the one dimension design fixes, so the
  ideal is the *same* for every card and nothing is singled out for being
  informative — and "too big to frame" is a width question too. Height did not
  disappear: it decides *which part* of a tall card the camera commits to. A
  card taller than the comfort box is framed from its **top**, where the
  header, name and running dot are, rather than centred on an anonymous band of
  its middle. That anchoring is also what lets such a card settle at all —
  `contains` can never hold for a rectangle taller than the box it is tested
  against, so without it the follower would re-issue a move on every streamed
  frame for exactly the nodes it was trying to help. Both invariants the band
  exists for are asserted on the router itself: focusing it once yields `stay`,
  and a run that starts already framed at 1:1 does not move the camera. A
  fan-out still fits by zooming out only. `followDecision.test.ts` grew a suite
  driven by the eight real card rects measured off the running editor; five of
  its six new cases fail against the old rule.

- **`POST /api/runs` declared a `thread_id` and threw it away.** The
  non-streaming endpoint has always accepted `thread_id`, `session_id`,
  `user_email` and `workflow_slug` on its request, and built **no
  `configurable` block at all** — so none of them reached the run. Three calls
  on one thread were three unrelated first turns: measured on
  `chinook-assistant`, the follow-up *"how did you work that out?"* classified
  `general_knowledge` there, while the identical conversation over
  `/api/runs/stream` classified it `data_query`. This is the same defect the
  editor's Ask panel had — a client with no history is always on turn one, so
  the router has no antecedent — surviving on a second endpoint. A declared
  field that reaches nothing is worse than an absent one, because it looks
  supported. The endpoint now passes the block the streaming one already
  built, and returns `thread_id` on `RunResponse` so a caller can continue.
  - **It also compiled with no checkpointer**, which is why passing the config
    alone would not have been a fix: no saver, no persisted `messages`, no
    antecedent. It now compiles from the same per-workflow saver cache the
    streaming endpoint uses.
  - **A pausing workflow used to return `200` with an empty answer.** Silently
    — a caller could not tell "finished with nothing to say" from "stopped
    halfway waiting for a human". The checkpointer is what makes
    `__interrupt__` visible, so the honest report became possible in the same
    change that made it necessary: **409**, naming `/api/runs/stream` and the
    thread. Listed here rather than as breaking because the previous behaviour
    was a blank success, and nothing could have been relying on it correctly.

- **A gateway was taught to route where it has no edge, and left ignorant of
  the child it actually mounts** (one-chinook-honest ticket 16).
  `RootKnowledgeBuilder` was documented as writing "one coarse doc per child",
  and read that two different wrong ways: it enumerated *every published,
  non-hidden workflow on the platform* and used the mounts only as a yes/no
  gate on whether to fire at all. Both halves of the inversion were sitting in
  the committed tree, not hypothesised — `workflows/concierge/knowledge/` held
  routing pointers for `page-analytics` and `chinook-metrics-team`, neither of
  which the concierge mounts or can reach, and held **no** doc for
  `workflow-architect`, which it does mount, because that child is
  `hidden: true` and `WorkflowStore.list()` drops hidden packages.

  Topics are now the distinct slugs this document's own `workflow.subgraph` /
  `team.workflow` nodes name, and nothing else. **The mount is the routing
  fact:** `published`/`hidden` describe a package's visibility on the `/chat`
  surface and say nothing about whether a parent can invoke it, because a
  mount compiles the child as a subgraph and `document_loader` consults
  neither flag. Ticket 04's `published_only` gate is therefore removed from
  this builder — it answered *"may a routing doc send a customer to a draft
  they cannot open?"*, which is not the question a mount asks — and a mounted
  slug whose package will not load is now a **warning** beside the unopenable
  SQL sources, never a doc and never a crash. The slug special case
  (`concierge` was root "by definition") is gone with it: a workflow that
  mounts nothing routes nowhere, so it has nothing to write a routing doc
  about. `docs/decisions/knowledge-architecture.md` states the corrected rule
  and calls out the difference from what it previously claimed.

- **A follow-up question got an unrelated answer because the run that
  answered it was never in the conversation** (one-chinook-honest ticket 11).
  Reported from live use as *"follow up did not work — I got random response
  when asking about relevant data"*, and charted with two candidate designs —
  a `follow_up` router branch, or giving the router history. Both were the
  wrong question, and neither is what shipped: the router already carries a
  locked follow-up instruction in its preamble, and `_thread_question` already
  renders the thread's last turns as context. What it was given was an empty
  conversation. `thread_id` is optional on `POST /api/runs/stream`; when a
  client omits it the server mints a fresh one per request, so `messages`
  starts empty on every send and every question is turn one. Recorded live,
  same document, same model, same four questions, differing only in whether
  one `thread_id` was sent: with a thread, "How did you get that?" reaches the
  router as `Conversation so far: …` and is answered with the join that
  produced the figure; without one it reaches the router as that bare sentence
  and comes back as "I'm set up to answer questions about the Chinook
  music-store database…". The fourth turn, without a thread, never finished at
  all — with no antecedent for "the top genre" the analyst re-read the schema
  seven times and then called a tool that does not exist. Both recordings are
  committed as `backend/tests/data/recorded_chinook_followup_thread.json` and
  drive `test_follow_up_conversation.py`.
  **The fix is disclosure**: `done` and `error` now carry `threadId` exactly
  as `interrupt` always did, so a client can continue the conversation it just
  had. Until now the client that most needed continuity — the one that had not
  named a thread — was the only one that could not learn which thread it had
  been given, and `docs/api.md` described `thread_id` as the thing "a client
  that wants to answer an approval should choose", which reads as *a thread is
  an approval handle*. It is not; a thread is the conversation. That page now
  says so, and its paste-able client keeps the thread across asks instead of
  minting `chat-${Date.now()}` on every one.
  **Known remaining:** the editor's own Ask panel still sends no `thread_id`,
  so follow-ups in the editor remain single-shot until it holds one. That file
  is ticket 13's live working area and was deliberately not touched here.
  *(Closed by ticket 17, immediately below.)*
- **…and the editor's Ask panel now holds that thread, which is where the bug
  was reported from** (one-chinook-honest ticket 17 — the other half of 11).
  The panel takes the thread off whichever terminal frame arrives — `done`,
  `interrupt` or `error`, all three name the same one — and sends it back as
  `thread_id` on the next question. A failed turn counts: it still happened in
  a conversation, so forgetting the thread there would silently open a second.
  Verified through the panel against a live backend on the recorded four
  turns: "Which genre earned the most revenue?" → **Rock, $826.65**; "How did
  you get that?" → the two-join `GROUP BY` explained rather than the generic
  "I'm set up to answer questions about the Chinook database"; an unrelated
  question routed to `b-general`; "remind me what the top genre was" → Rock,
  $826.65, finishing cleanly where the un-threaded recording produced no
  terminal frame at all.

  **A conversation ends three ways, and the reasoning is the feature.** A
  **New** button in the panel header, which forgets the thread and leaves the
  transcript — a run's trace is evidence, and "start over" should not also mean
  "delete what the last conversation showed me", so the next turn draws a
  `New conversation` rule across the thread instead. **Opening a different
  workflow** starts one automatically: LangGraph's checkpointer is keyed by
  thread id *alone*, so carrying one across documents replays the previous
  graph's `messages` into a different graph, and the thread is therefore held
  as a `{slug, id}` pair so that is a property of the type rather than of a
  call site. **Reloading the editor** starts one — the single place this
  panel diverges from `/chat`, which persists per slug in `localStorage`.
  Neither surface persists its *transcript*, so restoring the id alone yields
  a conversation whose earlier turns exist on the server and nowhere on
  screen: an answer with an invisible antecedent, the same defect class as the
  one being fixed and considerably harder to spot. It is also wrong
  specifically *here*, because a reload in an editor usually follows an edit,
  and the checkpointed history belongs to the graph as it was.

  `RunRequest.threadId` and `RunResult.threadId` join `RunInterrupted`'s, and
  the `error` stream event carries one too. An **empty** `threadId` means "this
  frame said nothing about its thread" — the non-streaming `POST /api/runs`
  names none, and neither does an older backend — never "there is no thread",
  so it leaves a held thread untouched rather than clearing it. The two rules
  that decide all of this live in `src/view/ask/thread.ts` and are unit-tested,
  because a thread is a server object: sending a question into the wrong
  conversation, or into none, looks identical on screen until something is
  asked that needs an antecedent, which is exactly how this survived so long.
  `docs/getting-started.md` gains "The Chat panel is a conversation, not a
  series of questions"; `docs/api.md` records why the two surfaces answer the
  persistence question differently.
- **A Supervisor's rules came from a field nobody could write, and the whole
  class of that defect is now a test** (one-chinook-honest ticket 07).
  `NodeRuntime._orchestrator` composed the supervisor's prompt with
  `rules=_text(data, "instruction")`, but `instruction` is that node's input
  **port** id and a port id is not a data key: the editor declared exactly one
  field on `orchestrate.supervisor`, `maxSubtasks`. So every supervisor ever
  built dispatched with empty rules, a developer could not shape how work was
  assigned to worker archetypes at all, and nothing raised — a factory reading
  a key nobody writes simply gets `""` forever. The node now declares a
  `Dispatch rules` textarea (spelled `rules`, the same as the Router's, since a
  fifth name for the layer `docs/decisions/skill-layer.md` already names would
  be the duplication that record rejects), sitting in the `Prompt` group beside
  the `Rules mode` switch that was, until now, switching between two layers
  while claiming three.

  **The third instance of one defect, so the guard was generalised rather than
  the symptom patched.** The first two were the model picker (declared on
  `agent.llm`, read for six node types) and the Worker's rules mode (`replace`
  hardcoded), each closed by a generated cross-language contract pinning one
  field — `drives_model`, `accepts_skill`. `port_specs.json` now also emits
  every node type's `field_keys`, and `backend/tests/test_data_key_contract.py`
  extracts the literal `data` keys each factory reads — following `_text(data,
  "k")`, `data.get("k")`, module constants, and any helper handed the data dict
  — then fails on any key no field declares. Reads that resolve to no literal
  are a failure too, not a skip: an extractor that shrugs at what it cannot
  parse stops guarding while still passing. The one sanctioned exemption is the
  editor's own `legacy_data_keys` (today just `criteriaMode`, a migration
  fallback), emitted from `src/nodes/skillLayer.ts` rather than kept as a
  hand-written Python list. The reverse direction is deliberately not asserted:
  `maxRetries`/`timeoutSeconds` are read by graph assembly and a worker's
  `role` is read by the *supervisor's* factory, so "declared but unread" is not
  evidence of anything. `NodeRuntime.builder_for(node_type)` was extracted from
  the dispatch closure inside `factory()` so the test can ask which factory
  runs for each catalogue type without a second hand-kept list. The artifact's
  `schema_version` is 2.

  **It found a fourth instance on its first run**, which is the point: all five
  prompted families read `reasoningEffort` (`openstategraph/reasoning.py`)
  while the editor declared no field for it. That work was in flight and its
  field landed the same day, so the fourth instance is the first one to have
  been caught before shipping rather than after.

- **A tool result was rendered as if the model had said it, so the longer it
  was the less of it you could read.** LangGraph's `messages` stream mode
  carries every message a node emits, not only model tokens, so each
  `ToolMessage` rode the same frames as the model's prose and the editor
  concatenated both into one `thinking` string. Two consequences, both seen on
  a real Chinook run: `list_all_tables`' eleven-row Markdown table was glued to
  the tail of a sentence, so once the turn settled and the blob was rendered as
  Markdown the whole table collapsed onto one wrapped line; and reasoning and
  results shared a single 160px region, so a long schema listing pushed the
  reasoning out of reach and vice versa. A token frame now declares `kind`
  (`"ai"` or `"tool"`) plus the tool's `name` and the `tool_call_id` it
  answers, and the chat panel folds tool frames into their own record. Each
  result gets its own block, attributed to the tool that returned it,
  whitespace preserved, capped at 220px and scrollable — bounded rather than
  clipped or unbounded, however much comes back. Both fields are additive: a
  client that ignores them behaves exactly as before. **One renderer for every
  tool, deliberately**: `list_all_tables` and `get_table_schema` return
  different shapes, but the chat trace knows only that *a tool returned this
  text*, so splitting on shape would put Chinook-specific knowledge in the chat
  panel and demand a third renderer for the next tool. What is genuinely shared
  — what a bounded tool result looks like — is declared once. The `Get Table
  Schema` **card** needed no change: it already lists all eleven tables behind
  its own 220px scroll region, and its data path was verified against the live
  endpoint.
- **An output dot sat beside the wrong input, because CSS was asked to decide
  which row it belonged on.** The port footer is a two-column grid — inputs
  left, outputs right — with the *column* declared per port and the *row* left
  to auto-placement. Sparse auto-placement advances one cursor for the whole
  grid and never moves it backwards, so the first output landed on the row of
  the **last** input rather than the first: an agent declaring `prompt`,
  `skill`, `feedback`, `result` drew `result` three rows down beside
  `feedback`, with row one's right-hand cell empty. Two inputs and two outputs
  came out worse — four ports over three rows, none of them paired. This was
  never only cosmetic: `NodeCard` measures a port's `y` from its own row's
  rect, so a row placed oddly *is* a dot placed oddly, and the wire arrived
  where the reader was not looking. Each column is now numbered independently
  from one, so the nth input and the nth output share the nth row by
  construction.
  - Bindings whose dot is on a card edge rather than on the flank beside their
    row — an agent's `skill`, a tool's `tool` — keep their footer line (the
    footer is the card's legend and names every port) but sink to the foot of
    their own column and are drawn back, so the rows a wire can actually reach
    stay contiguous instead of being interrupted by a dotless gap.
  - A bus capsule no longer loses its dot in vertical flow. CSS draws
    `.node__pill` at the card's bottom centre in both directions, but its
    *port* rotated onto a flank with the rest of its side, so the link arrived
    at the left edge while the capsule it binds to stayed drawn at the bottom.
    A pill is now its own anchor and follows the rendered capsule.
  - The arithmetic is `src/view/nodes/portLayout.ts`, pure and unit-tested
    beside `bottomPorts.ts`, with `NodeCard` doing only measurement and wiring.
    Being pure is what makes the real bar affordable: the test asserts over
    **every registered node type in both flow directions** that each declared
    port has a position, that flank dots are on the edge they claim, and that
    no two ports land on one point — rather than eyeballing one card.

- **Arrange automatically moved every card in a group and left the group
  behind.** Frames are excluded from the ranking — correctly, since a frame has
  no edges and dagre would park it in a rank of its own — but nothing put them
  back, so on the seeded demo the "Ask the database" frame ended up floating
  over cards it has nothing to do with. Containers are now re-wrapped around
  wherever their children were just placed, in the **same**
  `history.transact('Auto layout', …)`, so one Cmd-Z still reverses the whole
  arrangement rather than leaving frames fitted to positions nothing occupies.
  - The arithmetic is `src/core/model/containerFit.ts`, pure and unit-tested,
    with `AutoLayout` doing only the wiring. It handles nesting (innermost
    first, so an outer frame measures the *fitted* inner one), a childless
    frame (left exactly as it is — collapsing it would read as the layout
    deleting a label), and the asymmetric padding (`top: 128` for the title
    bar, with the minimum size growing the frame right and down only).
  - It lives in `core/model/` rather than beside the other layout modules
    because `GroupingController` needs the same arithmetic when it *creates* a
    frame, and `controller/` may not import from `canvas/`. That controller now
    calls the shared `fitAround` instead of its own copy of the formula.
  - One subtlety worth recording: the adapter applies a move with
    `{ deep: true }`, so a frame's move shifts children the graph already has
    positions for while the model moved only the frame. Moves are therefore
    emitted ancestors-first, which makes each node's own absolute position the
    last write for it.

- **A Markdown File was laid out as a stage of the flow instead of as the
  agent's equipment.** `MarkdownFileNode` declared its `skill` output as
  `BINDING_SIDE.provider`, but the `skill` *input* on `agent.llm` — and on
  `orchestrate.worker` — declared no side at all. `isBindingEdge` requires both
  ends to agree, correctly, since a `result` arriving at a bus-shaped port is a
  real step and classifying it as equipment would hide it under a card. So the
  wire read as flow, the markdown card took a rank of its own, and its line
  climbed across the Text Input above it. The port contract had already named
  "a tool, a **skill**, a worker pool" as bindings, so declaring
  `side: BINDING_SIDE.consumer` finishes a declaration rather than making a new
  claim. A skill still takes exactly one file, and a tool still cannot be
  dropped into the skill port — connection validation never reads `port.side`,
  and `src/nodes/skillBinding.test.ts` pins both, because two ports sharing one
  edge is exactly where a reader would assume otherwise.
  - **A latent rendering bug had to be fixed first.** That edge had only ever
    held one port, and two rules agreed on its dot's position *by coincidence*:
    CSS draws the bus pill at `left: 50%`, and an even spread of one port is
    also the halfway point. A second port would have moved the bus dot to two
    thirds while its pill stayed drawn at the middle, so links would arrive
    beside the thing they bind to. `src/view/nodes/bottomPorts.ts` inverts the
    rule — the dot follows the *measured* pill, and plain dots take the space
    the pill leaves, so a longer label moves them with no constant to edit.
  - Measured on the seeded demo afterwards: the Markdown File lands on the same
    row as all three tools, centred under the agent; the `tools` dot sits on
    the pill's centre and the `skill` dot clear to its left.

- **A tool no longer sits in the flow, and the spacing around it was derived
  rather than guessed.** `Arrange automatically` handed the whole graph to
  dagre, which reads a `tool → agent` wire as an ordinary predecessor: the two
  tools of `chinook-assistant` landed in a column beside the router, read as a
  *stage* of the workflow, and one of their curves ran straight across the card
  it was bound to. But the model already draws the distinction — `BINDING_SIDE`
  puts a capability's output on a card's top and the bus that gathers them
  underneath, "so a binding never looks like a stage of the flow" — layout had
  simply never been told. Bindings and the equipment that provides them are now
  withheld from the ranking and hung under their consumer as a shelf, with the
  space that shelf needs added to the consumer's box *on both axes before*
  dagre runs, so neighbouring ranks are kept clear of it and nothing has to be
  nudged afterwards. The rank and node gaps are now fractions of `NODE.width` —
  the one card dimension design fixes — instead of the four constants that were
  chosen once and never re-derived when the card settled at 252px: ¾ of a card
  between ranks, half of that within one, measured by sweeping the gap and
  counting crossings rather than picked for looking right. Edges are also
  *sorted* into port order before dagre sees them, because its
  crossing-minimisation sweep is seeded from arrival order and the reverse order
  costs seven crossings. `chinook-assistant` goes from one line over a card and
  three over each other to **none of either**, in both reading directions.
  Two crossings remain on `chinook-nl-to-sql` — a grader's `revise` back-edge,
  which no non-routing connector can steer around the ranks it returns across,
  and a `skill` wire whose two ends disagree about being a binding — both named
  with screenshots rather than glossed. Before/after images, the measurement
  method, the swept tables, and the rejected alternatives (edge stubs, dagre's
  `ranker`, label-driven rank widening) are in
  `docs/decisions/edge-legibility.md`.
- **A revise loop that ran out of attempts said nothing at all.** Found while
  verifying the two fixes above in the editor: a mounted analyst's grader
  rejected twice, hit `maxAttempts: 3`, and the chat reported *"No answer was
  produced."* directly above *"3 attempts before the grader passed it."* — two
  contradictory sentences and nothing to act on. Forcing `pass` at the ceiling
  is right (a loop that cannot finish is worse than a mediocre answer), but the
  last candidate was empty and was passed through verbatim, so every surface
  downstream claimed success and showed a blank. The ceiling now reports
  itself — naming the cap, which is the actionable part — and **only when it
  has nothing to hand on**: a candidate the grader merely disliked is still the
  workflow's answer and is still passed through untouched, because replacing it
  with our commentary would be the worse failure.

- **Five node types drove a model that nobody could choose.**
  `NodeRuntime._resolve_model(data)` reads `data["model"]` for the agent, the
  router, the grader, the supervisor and the worker — and its own docstring
  claimed the router and grader shipped the same select the agent does. They
  did not: `agent.llm` was the only node type that ever declared the field. So
  five node types ran whichever model the request happened to resolve, their
  cards offered no way to say otherwise, and nothing failed — a wrong model
  does not raise, it just answers slightly worse, which is the hardest shape
  of defect to notice. The picker is now **one descriptor**
  (`src/nodes/modelField.ts`) that every model-driven family imports, in the
  same shape as the shared `OVERRIDES_FIELD` — declared once, per CLAUDE.md,
  rather than pasted five times.
  - **The two sides can no longer drift.** `port_specs.json` now carries
    `drives_model` per node type, emitted from the TypeScript catalogue, and
    `backend/tests/test_model_field_contract.py` asserts it against the
    compiler's own factory table — read from the source, not from a
    hand-kept list, since a third list is the same bug again. It earned its
    place immediately: it rejected a model picker added by reflex to
    `function.format_report`, which is a *function* node that joins worker
    results with no LLM call, and would have promised a choice that changed
    nothing.

- **An unconfigured card said "Mock · Offline" about a node that would run a
  real model.** The field's default was `mock/mock-offline`, while
  `_resolve_model` maps `mock` to "no override" exactly as it maps empty — so
  the label named a fake model for a node using the shared one. Reported from
  live use as *"why is the Concierge mock offline? web researcher mock
  offline?"*. The empty selection is now **Workflow default**, listed first
  and in its own group. Mock stays selectable: it is a genuine offline
  simulator for the local canvas preview, and choosing it is different from
  landing on it. Documents that already store `mock/mock-offline` are left
  exactly as they are — rewriting somebody's saved choice to guess at intent
  would be worse than a stale label.
  - The preview's fallback chain is now one tested function
    (`resolveModelSelection`), which also fixes a mismatch it exposed:
    `workflow.settings.model` is written `ollama:gpt-oss:120b-cloud` for
    `init_chat_model` while a node field is written `ollama/gpt-oss:120b-cloud`
    for `ProviderRegistry`. Every shipped workflow carries the colon form, so
    without conversion the browser preview reported "Unknown model" for a
    workflow the backend runs perfectly.

- **The canvas did not follow a run unless you found the toggle.**
  `RunFollower` started with following **off**, so the focus-and-zoom
  behaviour — built, tuned and unit-tested — never fired for anyone who had
  not discovered the crosshair button, and the owner's report was simply that
  active nodes are never brought close enough to read. It is on by default and
  the choice persists (`PreferencesStore.followRun`). Safe as a default only
  because the follower already surrenders the camera to the first real
  gesture; a *gesture* still only pauses following for that run, while a
  *click* on the toggle is what records a decision about every run after it.

- **Loading a document left the camera pointing at the previous one**
  (one-example ticket 04b, `src/canvas/features/FrameOnLoadFeature.ts`).
  Drilling into a Team or Workflow mount — or coming back out, or loading
  anything from the Workflows panel — replaced the model without moving the
  camera, so the nodes and edges of the document you just opened were off
  screen or at a scale from a different graph. A wholesale replacement is a new
  coordinate space, and a transform chosen for one graph means nothing for the
  other. Framing now happens once, on `workflow:reset` only, in one installed
  feature rather than in the three of six call sites that had remembered to
  hand-write a `requestAnimationFrame(fit)`. Ordinary edits still never move
  the camera: a canvas that re-fits while you work is worse than one that never
  fits at all.

- **Following a run brought the active node on screen without making it
  readable** (one-example ticket 04a, `src/canvas/follow/followDecision.ts`).
  A single active node was deliberately a pan, never a zoom — but at the scale
  people use to see a whole graph, a card is a coloured box, so following it
  faithfully still showed nothing. One node now resolves to a `focus` decision
  that scales it to a readable share of the viewport, under a ceiling, with a
  dead band wide enough that the editor's default 1:1 zoom is already inside it
  — starting a run does not move a camera that was fine. Several active nodes
  (a `Send` fan-out) still resolve to `fit` and still zoom **out** only:
  magnifying a fan-out would throw away the context that makes it legible.

- **The editor bundle called `http://localhost:8000` absolutely**
  (`src/core/runtime/RuntimeClient.ts`, `WorkflowFileClient.ts`, two view
  components). True of exactly one deployment — Docker published on port 8000
  — and false of the one that now matters: served from the wheel on any other
  port, the editor loaded perfectly and every API call inside it went to a port
  with nothing on it. The base URL is resolved once
  (`src/core/runtime/runtimeBaseUrl.ts`) and is **same-origin relative** in a
  production bundle, so it follows the page to whatever host and port it was
  opened on. The dev stack keeps its absolute URL, because Vite on :5273 and
  uvicorn on :8000 are genuinely different origins and CORS still names exactly
  those two; `VITE_RUNTIME_BASE_URL` overrides either mode. Both modes are
  pinned by tests. Consequence: `docker-compose.yml`'s host port is no longer
  required to be 8000.
- **The static mount had no answer for an installed distribution.** It read a
  relative `dist` from the process's working directory, so it worked in the
  container and nowhere else. Resolution now has an order —
  `OPENSTATEGRAPH_STATIC_DIR`, then the wheel's own copy, then a checkout's
  `dist/` — in one module (`api/editor_assets.py`) that both the container and
  `openstategraph serve` go through. No second serving path was forked.

- **The editor's browser autosave could lose work three ways, all silently**
  (register UX-04). (1) A failed write was invisible: `saveWorkflow` returned an
  outcome and the autosave call site *discarded* it, so an exhausted ~5MB quota
  — or Safari's private mode, where every `setItem` throws — left the user
  editing a document nothing was recording. Failures now carry a typed kind
  (`quota`, `too-large`, `conflict`, `error`) and a sentence the editor shows,
  once per distinct failure rather than once per keystroke; an oversized
  document is refused *before* the write so the message names the document
  instead of blaming the disk. (2) A corrupt entry read back as `null`, which is
  indistinguishable from "nothing saved" — the user silently got the seeded demo
  instead of their graph. The reader now returns `ok`/`missing`/`corrupt`, says
  so, and *quarantines* the unreadable bytes under a separate key rather than
  deleting them (they are that user's only copy) or leaving them to fail every
  subsequent load. (3) Two tabs shared one autosave key and the last write won,
  so the losing tab displayed work it was overwriting. A claim record with a
  10-second heartbeat stops a second live tab adopting the id at all — it starts
  a blank workflow and says why — and a compare-and-set on every write catches
  the race the claim cannot. The compare is against *the version this tab last
  saw*, not the writer's identity, because an owner-based check would lock a
  workflow forever the first time its author closed the tab. Browser storage is
  still browser storage; the Workflows panel now says so out loud, and the
  server-side design is written up in the register.
- **`pip install 'openstategraph[mcp]'` was broken by an unpinned dependency.**
  `mcp` 2.0.0 removed `mcp.server.fastmcp`, which `openstategraph.mcp_server`
  imports, so a fresh install of the MCP extra failed at the transport's one
  entry point. Pinned to `mcp>=1.25,<2`, matching the LangChain pins' policy
  that majors are where these projects put breaking changes. Found by installing
  into a clean Python 3.11 environment while adding the CI version matrix — a
  developer machine with a cached 1.25 could not see it.
- **SQLite connections were never closed.** `with sqlite3.connect(...) as conn:`
  is a *transaction* manager, not a close — it commits and leaves the file
  descriptor open. Both read-only SQL surfaces used it: the `tool.sql-*`
  explorer tools an agent calls on every turn, and the knowledge builder's
  schema introspection, which opens a nested connection per table. A long
  agent loop leaked one descriptor per tool call. Both now use
  `contextlib.closing`, pinned by a test that asserts the connection actually
  refuses a query afterwards.
- **Nothing released the checkpointer or the memory store either.** langgraph's
  `SqliteSaver` and `SqliteStore` define neither `close()` nor `__exit__`, so
  every `load_workflow` call left two sqlite handles open for the life of the
  process, and a document with `settings.checkpointer: "sqlite"` opened a
  *fresh* connection to the same file on every run, stream and resume.
  `WorkflowServices` and `CompiledWorkflow` are now context managers with an
  idempotent `close()`, and the per-workflow saver is opened once per workflow
  and owned by the services object. What the caller injected is never closed —
  it is still theirs.
- **The installed-plugin scan ran on every request.**
  `importlib.metadata.entry_points()` re-walks every installed distribution's
  metadata, and `build_tool_registry` called it per run, per stream, and again
  per subgraph child. Measured on this checkout: `runtime_for` cost 14.8 ms
  steady-state, 12.2 ms of it in that one scan. The built-in and plugin layers
  are now resolved once per process (they cannot change without a restart);
  `runtime_for` is **1.05 ms**.
- **The knowledge curation panel read every document twice** — once for the
  index hint, once for the marker and claim hashes — and saving a topic wrote
  the file and then read the same bytes back to extract one line. One read per
  document now; a 60-topic listing went from 120 reads / 16.2 ms to 60 / 8.8 ms.

- **Four modules resolved the workflows root inside the virtualenv once
  installed.** Each computed `Path(__file__).resolve().parents[N] /
  "workflows"`, which is the repository only while the file sits in a
  checkout; from a wheel it is `<venv>/lib/python3.13/workflows`. The symptom
  was not a crash — `platform_list_workflows` answered **"No workflows exist
  yet."** with the adopter's packages in their project directory, every
  `tool.sql-*` database path was refused, and an un-configured
  `tool.email-send` dry run wrote the user's report into their virtualenv. New
  `openstategraph.workflows_root` answers the question once, **per call**:
  `OPENSTATEGRAPH_WORKFLOWS_ROOT`, else the checkout (so every in-tree
  behaviour is byte-identical), else `./workflows` — which is where
  `openstategraph new` already writes. Found by the clean-venv proof, which no
  amount of green test suite could have replaced.
- **`WorkflowStore(root="…")` with a string root** raised `TypeError:
  unsupported operand type(s) for /: 'str' and 'str'` one call later, in
  another module. The root is coerced to a `Path`.
- **`settings.checkpointer: "sqlite"` degraded silently to in-memory** in every
  install that existed, because `langgraph-checkpoint-sqlite` was imported but
  never declared and is not a transitive of `langgraph`. A user who asked for
  durable threads got a log line and would have found out when a restart ate a
  conversation. The dependency is now `[sqlite]` and the fallback says so, in
  as many words, naming the install command. Same fix for
  `OPENSTATEGRAPH_MEMORY_PATH`.
- **A missing optional dependency now names its extra.** `deepagents is
  required for tier='deep' agent nodes — pip install 'openstategraph[deep]'`,
  rather than a bare `ModuleNotFoundError` an adopter has to map back to one of
  seven extras themselves.
- **An edited tool in a workflow package could be invisible to the run that
  used it** (docs-and-gaps ticket 10, gap PF-01,
  `backend/openstategraph/api/capability_discovery.py`). The ticket asked what
  should invalidate a *hypothetical* cache of discovered modules; the answer
  was that the caching had already happened and nobody had chosen its policy.
  `spec.loader.exec_module` is a `SourceFileLoader`, so discovery wrote a
  `__pycache__/*.pyc` **inside the developer's own workflow package** and
  validated it on the next call against `(source mtime in whole seconds,
  source size in bytes)`. Both halves of that key are coarse, and together they
  are wrong for a folder a developer is actively editing: **an edit that keeps
  the file's byte length and lands in the same second as the previous one was
  served stale.** Measured, not reasoned about — changing a tool's description
  from `"Greets someone by name."` to `"Greets someone, warmly."` gave back the
  old string, and it is not an exotic edit (flip a `<` to a `>`, change a digit
  in a row cap, rename a variable to another of the same length). Worse than a
  stale panel: `discover_tool_instances` binds these classes into the run, so
  the *agent* got the old tool. Discovery now compiles the source bytes itself
  instead of handing the file to the loader, which also stops littering
  `__pycache__` through workflow packages. The policy is written down where
  someone would go to "optimise" it, with the measurement that justifies it
  (~1.5 ms/call for the largest shipped package) and the rule for any future
  cache: key on the file's **content hash**, never mtime, never process
  lifetime.

### Removed

- **`page-analytics` and `chinook-metrics-team` are gone** (one-example ticket
  01). They existed to prove the platform could express a large graph, and they
  did — twenty nodes, thirty links, a supervisor fan-out, an approval gate and
  an email dispatcher. But a first-time reader met a diagram nobody can hold in
  their head, and a gallery of three examples answers "what can it do" while
  leaving "what should I build" unanswered. `chinook-assistant` is the one
  visible example now, `chinook-nl-to-sql` is what it mounts, and
  `workflow-architect` and `concierge` remain as platform surfaces rather than
  examples. Everything the deleted graphs exercised — supervisors, approvals,
  fan-out, the email tool — is still supported, still tested, and still
  documented in `docs/patterns.md`; it is no longer all crammed into one
  picture.
- **The Tabular Data and Code Workshop node families are gone** (docs-and-gaps
  ticket 08, gap UX-03). Eight palette entries — generic CSV/Parquet-over-DuckDB
  and a sandboxed coding loop — with no backend tool, no workflow that used
  them, and for Tabular not even the DuckDB dependency its own docstring named.
  The deciding evidence was the backend rather than the palette: a `tool.*`
  node resolves through `NodeRuntime._bound_tool`, which looks the type up in
  the shared registry and, finding nothing, appends it to `unresolved_tools`
  and binds no capability at all. So an agent could be wired to one of these
  and silently gain nothing — a palette entry that produces an unrunnable node
  is worse than an absent one. `workflowScoped.ts` loses two families and
  `port_specs.json` eight node types; Chinook remains the one workflow-scoped
  hand-authored family, alongside discovered tools.
- **Three design-system barrel exports with no consumer** (docs-and-gaps ticket
  12, gap UX-06). `Spinner` and `Progress` are deleted outright — component,
  styles and barrel line; `formatShortcut` is now module-local to
  `Indicators.tsx`, where `Kbd` and `shortcutText` are its only two callers. A
  barrel export is a promise somebody has to keep, and nobody was holding
  these.
- **`openstategraph/middleware/`** (docs-and-gaps ticket 12, gap PK-09) — an
  empty directory holding only `__pycache__`, tracked by nothing and already
  correctly absent from the wheel.

### Internal

- `__all__` removed from every module under `openstategraph/api/`, which is
  Tier 3: in Python `__all__` reads as "this is the public surface", and those
  lists were the names each module hands its own siblings.
- New guards, run on every PR: a distribution-metadata test (the core is
  exactly four, each extracted name is in the extra that claims it), a
  signature snapshot of the public API, and a check that no Tier 1 module
  imports a private name out of `openstategraph.api`.

## 0.2.0 — 2026-08-09

The first release under the project's own name, plus the work that made the
conversational surface actually usable across workflow boundaries.

### Changed — breaking

- **Renamed Dyflow → OpenStateGraph.** The Python package is now
  `openstategraph` (import paths, `uvicorn openstategraph.api.main:app`), and
  the backend environment variables are `OPENSTATEGRAPH_OLLAMA_MODEL` and
  `OPENSTATEGRAPH_LOG_LEVEL`. Any existing
  `.env` or shell profile carrying the old names must be updated — the old
  spellings are not read as fallbacks. `workflow.json` is unaffected: the
  serialized format did not change.

### Added

- **Memory.** Conversation memory generalised beyond a single workflow, plus
  three-scope long-term memory (user / workflow / thread) over the LangGraph
  Store, with prebuilt save and search tools.
- **The conversation crosses the subgraph boundary.** A routed child subgraph
  now receives the parent thread's dialogue instead of starting amnesiac, and a
  `PackageAssets` loader gives a child its *full* package rather than a bare
  `workflow.json`.
- **Live flow view in `/chat`.** The compiled graph renders beside the
  conversation with active nodes lit during a run; the layout is a fixed
  420px chat column that stacks under 900px.
- **OpenWiki.** 13 generated concept pages as a single source of truth the
  concierge can read, refreshed by a weekly PR-on-change workflow.
- **Playwright smoke suite** driving real gestures against the canvas, wired
  into CI alongside the unit suites.

### Improved

- **Concierge and Workflow Architect** routing sharpened: build requests and
  how-does-it-work questions no longer collide, and tool-call chatter is never
  presented as the answer.
- **`api/main.py` split** (973 → 570 lines) into `schemas`, `model_resolution`,
  `registries` and `streaming`; runtime collaborators are passed as a
  `RuntimeServices` parameter object rather than threaded individually.
- **Coverage ratchets in CI.** Frontend statements 58% → 73.5% (367 tests);
  backend measured at 91%. Both floors are enforced, so a PR cannot lower them
  to go green.
- Palette level labels, and `scripts/dev.sh stop` now escalates past a
  graceful-shutdown hang instead of waiting forever.

### Removed

- `.scratch/` and `HANDOVER.md` are no longer tracked — internal planning stays
  local and out of the published repository.

## 0.1.0 — 2026-08-08

First coherent release: a visual workflow builder that compiles to LangGraph.

- **Editor**: JointJS-core canvas (registry-driven palette, undo/redo,
  snaplines, minimap, auto-arrange in both flow directions), schema-driven
  inspector with locked prompt sections, compiled-graph Mermaid overlay,
  execution trace tree with JSON export.
- **Runtime**: `workflow.json` → LangGraph `StateGraph` compiler (routers,
  graders with rubric rows, supervisor fan-out with worker archetypes, HITL
  approval, subgraph + Team nodes, per-node retry/timeout), agent tiers
  (ReAct / deep / custom) over a middleware slot table.
- **Memory**: long-term Store namespaced per user with prebuilt save/search
  tools, durable sqlite checkpointing opt-in, procedural skills per package.
- **Customer surface**: `/chat` with workflow selector, an Auto concierge
  gateway (read-only platform introspection + keyless web search), and a
  Workflow Architect that composes compile-validated workflows from a
  description — saving stays a human click.
- **Workflows shipped**: Chinook NL-to-SQL, video-game analytics, open-API
  explorer, code workshop (+review), research team, data-analyst team.
- **Quality**: 505 pytest + 339 Vitest, strict tsc, ruff + ESLint + Prettier,
  CI, supervised dev stack (`scripts/dev.sh`).
