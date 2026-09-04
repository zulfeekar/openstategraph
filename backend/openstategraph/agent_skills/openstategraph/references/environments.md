# Which environment am I in?

Read this when step 11 of `SKILL.md` is the step you are on, or whenever an
install does not behave.

## Two installs, and they are not the same thing

Most projects end up with both. They answer different questions and they are
versioned separately.

| | **The library** | **The tool** |
| --- | --- | --- |
| Why | the service **imports** it at runtime | it is a developer tool, like a linter |
| Where | the project's own dependencies, pinned and committed | once, globally, outside every project |
| How | `pip install "openstategraph[<provider>]"` in the project's environment | `uv tool install "openstategraph[server,<provider>]"`, or `pipx install` |

**The tool's environment is isolated from the project's.** That is the fact
that decides most of what follows: the editor, the compiler, the board and the
MCP server all run from the tool's own virtualenv and share nothing with the
project's pins. The *library* install shares them completely.

## Case 1 — a fresh folder

Nothing to work around.

```
openstategraph init
```

It creates the workflows root, installs the skills into both skill roots, and
writes the agent config files that register the local MCP server. Then start
the interview.

## Case 2 — an existing project, no LangGraph

Also fine, and this is the common case. `openstategraph init` is additive: it
writes the skills, the agent config files and the workflows root, and it
touches no dependency of theirs. Run it in the project root.

If they already have an MCP config with other servers in it, `init` merges
into it and leaves the foreign entries alone. It refuses to overwrite only one
thing: an existing `openstategraph` entry that differs from ours — somebody
deliberately turned runs on, and silently turning them back off would be worse
than reporting it. That case is reported as `kept`, and the developer decides.

The MCP server starts from the **tool's** environment, not the project's
virtualenv. A project venv with no `openstategraph` in it still gets a working
server.

## Case 3 — a project that already uses LangGraph

The tool path is unaffected: the developer can draw, validate, compile and use
the board today regardless of what their project pins.

The library path shares their resolver, and this package requires
**`langgraph>=1.0,<2`**.

- **They pin LangGraph 1.x.** `pip install openstategraph` into their
  environment succeeds and shares the pin. Nothing special to do.
- **They pin LangGraph 0.x.** Two different things happen, and which one you
  get depends on whether the pin is *stated to the resolver*. This was
  measured, not assumed (ticket `26`, 2026-09-04).

  **When the pin is stated** — `uv add`, or `pip install -r requirements.txt`,
  or `pip install -c constraints.txt`, or anything reading a `pyproject.toml`
  that declares it — the install is refused, and the refusal is correct. It
  looks like this:

  ```
  ERROR: Cannot install langgraph<1 and openstategraph==<version> because
  these package versions have conflicting dependencies.
  The conflict is caused by:
      The user requested langgraph<1
      openstategraph <version> depends on langgraph<2 and >=1.0
  ERROR: ResolutionImpossible
  ```

  uv words it differently and means the same thing: *"your project depends on
  langgraph<1 and openstategraph, we can conclude that your project's
  requirements are unsatisfiable."*

  **When the pin is not stated** — a bare `pip install openstategraph` into a
  virtualenv that merely *has* LangGraph 0.x installed — pip does **not**
  refuse. It uninstalls their LangGraph and installs 1.x, along with
  `langgraph-checkpoint`, `langgraph-prebuilt` and `langgraph-sdk`, and says
  so only in the `Successfully installed` line nobody reads. Their service
  now imports a LangGraph it was never tested against, and the failure lands
  far from the install that caused it.

  So: **check `pip show langgraph` after any library install into a project
  you did not pin yourself**, and never treat "the install succeeded" as
  evidence the clash was absent. Either way, say this:

  > Your project pins LangGraph 0.x and OpenStateGraph requires 1.x, so the
  > library install cannot honour both. The developer tool is unaffected —
  > it runs from its own environment — so you can draw, validate and compile
  > today. Importing a workflow inside your service needs the LangGraph 1.x
  > upgrade first.

  **Do not force it.** Not with a resolver override, not with a flag that
  ignores dependencies, not by vendoring a copy of anything. A forced install
  produces a service that imports two incompatible LangGraphs and fails at
  runtime, somewhere far from the install that caused it. Upgrading their
  LangGraph is a real piece of work and it belongs on the board as its own
  card, with the developer deciding when.

## What to check when something is wrong

1. **`openstategraph --version`** — is the tool even installed, and which
   version?
2. **Which environment answered.** A `python -c "import openstategraph"` that
   works while the command is missing means they have the library and not the
   tool; the reverse is the normal state.
3. **The two versions drift, and nothing warns you.** The tool has its own
   virtualenv and the project has its own. A workflow drawn by a newer editor
   and loaded by an older library fails at load, not at draw. If that matters
   to them, install the tool from the same pin their project carries.
