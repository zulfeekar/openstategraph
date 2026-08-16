# The stability contract

**Status: in force from 0.3.0.** Resolves wayfinder ticket 03; the reasoning
is in `docs/decisions/framework-packaging.md` §3.3.

This page answers one question: *if I import it, can it be taken away from me?*

---

## The tiers

| Tier | Where | Promise |
| --- | --- | --- |
| **1 — public** | `openstategraph.__all__`, `openstategraph.abc`, `openstategraph.errors`, `openstategraph.schema`, `openstategraph.providers`, `openstategraph.extensions` (the entry-point **group names**), the `openstategraph` **command line**, and the `workflow.json` schema itself | Covered by the deprecation policy below. Changes are announced, shimmed, and visible in `CHANGELOG.md`. |
| **1 — public, but the *objects* are somebody else's** | the collaborators you inject: `load_workflow(model=, checkpointer=, store=, tools=, functions=, middleware=)` | **The parameter** is Tier 1 — its name, its keyword-only-ness, and its `None` default are ours to keep. **The object** you pass is LangGraph's or LangChain's (`BaseStore`, a checkpoint saver, `AgentMiddleware`) or your own `openstategraph.abc` subclass; those contracts are theirs and ours respectively, not this page's. We will not silently start requiring a different type. |
| **2 — provisional** | `openstategraph.compile`, `.knowledge*`, `.evaluation`, `.plugin_interop`, `.prebuilt_*`, `.memory`, `.readable_tree`, `.scaffold`, `.templates`, `.cli`, `.workflows_root`, `.state_dir`, `.config_file` | Importable and documented. May change in a **minor** release with a changelog note. No deprecation window. |
| **3 — internal** | `openstategraph.api.*`, `openstategraph.mcp_server`, and any `_`-prefixed name anywhere | No guarantee at all. May be renamed, split or deleted in a **patch**. These are surfaces we operate, not libraries you build on. |

Most modules also state their tier in their own docstring. Not all of them do —
several Tier 2 modules say nothing — so **this table is the contract** and a
silent module means "look here", not "unclassified". (Until 2026-08-16 this
line promised the docstring was always there, which sent a reader to a file
that does not answer the question.)

### Tier 1, exactly

```python
from openstategraph import (
    load_workflow, CompiledWorkflow, RunResult,
    Workflows, WorkflowInfo,
    DEFAULT_RECURSION_LIMIT, __version__,
    OpenStateGraphError, WorkflowPackageError, PackageNotFound,
    InvalidPackageName, DocumentError, SchemaVersionError,
)
from openstategraph.abc import (
    ITool, BaseTool, ToolResult, NoArgs, Field, ToolField,
    IRouter, BaseRouter, Router, Classification,
    IGrader, BaseGrader, Grader, Verdict,
    IGuardrail, BaseGuardrail, Guardrail, GuardrailRule, Redaction, Screening,
    IAgent, AbstractAgentNode, BaseAgentNode, ReactAgentNode, DeepAgentNode,
    CustomGraphNode, agent_node_for_tier,
    INodeFamily, BaseNodeFamily, NodeBuildContext,
    IOrchestrator, BaseOrchestrator, Orchestrator, Archetype, Subtask,
    SystemPrompt, MiddlewareSlotTable,
    Progress, report_progress,
)
from openstategraph.errors import (
    OpenStateGraphError, WorkflowPackageError, PackageNotFound,
    InvalidPackageName, DocumentError, SchemaVersionError,
    CredentialError, MissingProviderKey, MissingProviderPackage,
    NoProviderInstalled, ProviderRefusedCredential, UnknownProvider,
    GENERIC_FAILURE_MESSAGE,
)
from openstategraph.schema import (
    SCHEMA_VERSION, MIN_SUPPORTED_VERSION, MIGRATIONS, Migration,
    normalize_document, migrate_document, document_version,
)
from openstategraph.extensions import (
    TOOLS_GROUP, KNOWLEDGE_BUILDERS_GROUP, PROVIDERS_GROUP,
    NODE_FAMILIES_GROUP, ENTRY_POINT_GROUPS,
    DISABLE_PLUGINS_ENV, Discovered,
    entry_point_tools, entry_point_knowledge_builders,
    entry_point_providers, entry_point_node_families,
    plugins_enabled, reset_entry_point_cache,
)
from openstategraph.providers import (
    ProviderSpec, ProviderEnvironment,
    ProviderCatalogue, ProviderDefault, ProviderGap,
    provider_catalogue, load_provider_catalogue, reset_provider_catalogue,
    builtin_specs, provider_readiness, missing_key_diagnosis,
    credential_env_vars, env_example_section, OPTIONAL_ENV_VARS,
    ENV_EXAMPLE_BEGIN, ENV_EXAMPLE_END,
)
```

**"Exactly" is now checked rather than asserted.** This block is pinned against
`backend/tests/public_api.txt` — the committed signature snapshot CI already
diffs — by `backend/tests/test_stability_contract.py`, which fails if a Tier 1
name exists and is not listed here, or is listed here and does not exist. It
was written because this list had drifted by **37 names**: the whole
`openstategraph.providers` surface, the guardrail and node-family ladders in
`abc`, two entry-point groups, and the provider error hierarchy in `errors`.

### Two directories, and only one of them is ours to write in

`Workflows(root)` — and every environment variable and config key behind it —
names where packages are **read** from. It is never where anything is
**written**. Those are separate questions with separate answers, and conflating
them is a defect an adopter discovers as either litter in their repository or a
crash on a read-only mount:

| | Answered by | Default |
| --- | --- | --- |
| **read** | `openstategraph.workflows_root` | convention `./workflows` < the checkout, when this file is inside one < config file `workflows_dir:` < `OPENSTATEGRAPH_WORKFLOWS_ROOT` < the explicit argument |
| **write** | `openstategraph.state_dir` | `OPENSTATEGRAPH_STATE_DIR`, else `<workflows root>/.openstategraph` **inside a checkout**, else the platform's per-user state directory (XDG `~/.local/state`, `~/Library/Application Support`, `%LOCALAPPDATA%`), keyed per project |

`OPENSTATEGRAPH_CHECKPOINT_PATH` remains the most specific answer of all for
the checkpoint file itself, above both, including its `=memory` opt-out.

**There is no module-level setter for either.** Both are functions resolved per
call, and a catalogue freezes its own answer at construction. A
`set_workflows_root()` would be process-wide mutable state, which is how two
callers in one process come to disagree about which directory they read with
nothing in either call to explain the difference.

### The entry-point group names are the least reversible thing here

`"openstategraph.tools"`, `"openstategraph.knowledge_builders"`,
`"openstategraph.providers"` and `"openstategraph.node_families"` are written
into a **third party's** `pyproject.toml`. Renaming one does not break a build
or raise an import error — it silently stops their plugin from registering, in
their users' installs, and the first symptom is a workflow that answers less
well than it looks. So the strings are pinned by a test that asserts the
literals, not merely their existence, and they move only under the deprecation
policy below (an old group is read for at least one minor release).

`backend/tests/public_api.txt` is the machine-readable form, and
`backend/tests/test_public_api.py` fails when it drifts. That is deliberately a
*signature* snapshot: a test asserting `"load_workflow" in dir(...)` passes
while a parameter is renamed, a default flips, or a keyword-only argument
becomes positional — each of which breaks an adopter at runtime, in their
service, months later.

### `workflow.json` is the most public thing here

More public than any Python symbol, because a document is what you commit to
*your* repository and diff in *your* pull requests. A document written against
schema version *N* loads on every release that claims to support *N*. The
version policy — what bumps the number, what is refused, the migration chain —
lives in `openstategraph/schema.py`, whose module docstring is the normative
statement. In short:

- **Bump the version** for a removal, a rename, a changed meaning, a changed
  port id or node-type id, or changed edge semantics.
- **Do not bump** for anything additive an older build ignores harmlessly.
  Additive-only kept us on 2 for a long time; the number is **3** now, because
  collapsing `team.workflow` into `workflow.subgraph` removed a node-type id
  and that is precisely a bump. `SCHEMA_VERSION` in `openstategraph/schema.py`
  is the value, not this sentence.
- A document **newer** than your build is **refused** with a message naming
  both versions — never best-effort compiled, because the failure would
  otherwise be a graph that runs and answers differently with nothing in the
  output that looks wrong.
- A document older than `MIN_SUPPORTED_VERSION` (currently 1) is refused;
  anything between is migrated through `MIGRATIONS`, one step per version.
- `MIN_SUPPORTED_VERSION` rises only in a major release.

### What is deliberately *not* public

- **The registries.** `build_tool_registry`, `discover_tool_registry`,
  `discover_function_callables`, `CapabilityRegistries`, and
  `WorkflowServices` itself. Extension is a
  supported *seam*, not a reachable object, and there are now two of them:
  publish `[project.entry-points."openstategraph.tools"]` from your own
  distribution (see
  [Building an atom](building-an-atom.md#publishing-an-atom-as-your-own-distribution)),
  or hand the capability straight to `load_workflow(tools=…, functions=…,
  middleware=…)` — which outranks every discovered source, and is the answer
  when the capability is *this process's*, not a package's. If neither seam
  fits and you find yourself importing a registry, that is a gap — please
  report it.
- **`openstategraph.api.main:app`.** Use `openstategraph serve` — the console
  script is the supported way to mount the HTTP server, and the import path
  behind it stays Tier 3 and free to move.

---

## The command line is Tier 1 too

More people will type `openstategraph run` than will import `load_workflow`,
so the *commands* carry the same promise as the Python names: a command is not
removed or renamed without a minor release in which it still works.

**Exit codes are the contract CI consumes**, and they are fixed:

| | |
| --- | --- |
| `0` | success |
| `1` | the run failed, or validation found blocking findings |
| `2` | usage error — bad arguments or an unknown command |
| `3` | a required extra is not installed; the message names the `pip install` line |

New flags are additive; a flag's *meaning* never changes under you. Output
formats are not frozen — parse `--json`, not the human text.

## `RunResult` is a `str`, on purpose and for now

`CompiledWorkflow.ask()` returns a `RunResult`, which subclasses `str`. That is
the compatible shape: `.ask()` shipped returning a plain string, so anything
else would have broken `.strip()`, `+`, `json.dumps` and `isinstance(x, str)`
at run time in an adopter's service rather than at import.

**Recorded intent:** at 1.0, where a major bump makes it affordable, this
becomes a plain frozen dataclass with `.answer`. Build on `.answer`,
`.decisions`, `.outputs`, `.warnings` and `.attempts` — not on the several
dozen string methods it currently also has.

---

## Deprecation policy

**Pre-1.0, which is where we are: a breaking change bumps the MINOR version,
never the patch.** Read `0.x` as "breaking changes ship in minors", the same
way `deepagents` does — not as semver-stable.

1. A Tier 1 name is never removed without at least **one minor release in which
   it still works** and emits a `DeprecationWarning` naming its replacement.
2. New parameters on Tier 1 callables are **keyword-only**, always. Not a
   habit — a rule, so that adding one can never reorder an existing call.
3. Every Tier 1 change carries a `CHANGELOG.md` entry under **Added /
   Changed / Deprecated / Removed**, and updates `backend/tests/public_api.txt`
   in the same commit.
4. A removal or a signature change ships its shim in the same commit as the
   change, not "before the release".
5. **Post-1.0**: removals only in majors; deprecations live at least one minor;
   the Python floor moves only in a major.

### Errors are additive by construction

Every class in `openstategraph.errors` inherits from **both**
`OpenStateGraphError` and the builtin the failure used to raise —
`PackageNotFound` is a `FileNotFoundError`, `InvalidPackageName` is a
`ValueError`. Existing `except FileNotFoundError` handlers keep working
untouched; `except OpenStateGraphError` is the new, narrower option. A new
hierarchy that broke existing handlers would be a worse trade than the untyped
errors it replaced.

### If you need something that is not Tier 1

Open an issue rather than importing it anyway. Promoting a name is cheap —
adding it to `__all__`, the snapshot and this page — and it is how the surface
grows on purpose instead of by accident.
