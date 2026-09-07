# A package's `tools/` has to import the project it lives in

`launch-readiness/195`. Decided 2026-08-30.

## The defect, as measured

A project that already exists, with a workflow package whose `tools/` imports
the application's own module — which is the whole point of a package `tools/`
folder in an adopted codebase:

```
myapp/inventory.py                    def stock_level(sku) -> int
workflows/stock-agent/workflow.json   an agent bound to tool.stock-level
workflows/stock-agent/tools/stock.py  from myapp.inventory import stock_level
```

Three invocations, one package, one directory, three answers:

| Invocation | Answer |
| --- | --- |
| `python -c "load_workflow('workflows/stock-agent', …)"` | no warnings |
| `openstategraph validate workflows/stock-agent` | exit 1, three problems |
| `PYTHONPATH=. openstategraph validate workflows/stock-agent` | `VALID`, exit 0 |

The mechanism is ordinary and arguably correct: `python script.py` and
`python -c` put the invocation directory on `sys.path`; a console script
installed into a virtualenv does not. `capability_discovery._import_module`
loads the tool module *by path*, so the file is always found and always
executed — its own `import myapp` is what fails.

Two things are wrong with that, and only one of them is a behaviour question.

## The message was wrong regardless

The remedy printed was:

> Copy the package's `tools/` folder next to `workflow.json`, or install the
> plugin that provides it.

The folder was already next to `workflow.json`. That is how discovery found
the module it then failed to import. A reader who follows the advice literally
moves a directory to where it already is, sees no change, and concludes the
tool system is broken — while the actual cause, `ModuleNotFoundError: No
module named 'myapp'`, was two lines further down in the same output and had
no remedy attached to it at all.

`CLAUDE.md`'s standing rule is that an id which resolves to nothing is
reported **by name**. This message named the wrong noun. It is fixed
independently of everything below, and the fix has two halves: the import
failure names the module the interpreter could not find and says what to do
about it, and the binding finding asks the *disk* which remedy applies — a
`tools/` folder that is not there is a folder to copy, and a `tools/` folder
that is there has a different problem.

## Then: does the CLI make the project root importable?

### Prior art, from primary sources

**pytest** states the rule as a negative, and it is the most directly relevant
sentence anybody has written on this:

> rootdir is **NOT** used to modify `sys.path`/`PYTHONPATH` or influence how
> modules are imported.
> — [Configuration](https://docs.pytest.org/en/stable/reference/customize.html)

pytest *does* modify `sys.path` — under `prepend` (its default) and `append`
import modes it inserts the directory containing each test module — but that
is a consequence of how it imports **test files**, not a service it offers a
project for importing its own code. For that it has an explicit ini option,
`pythonpath`, whose entries are resolved relative to rootdir and inserted at
the head of `sys.path` for the session. And its recommendation for new
projects is the `importlib` import mode, which
"[does not have any of the drawbacks above, because `sys.path` is not changed
when importing test modules](https://docs.pytest.org/en/stable/explanation/goodpractices.html)".

**The packaging ecosystem's answer** is not a path at all. `pip install -e .`
is *Development Mode* — "[installing from local src in Development Mode, i.e.
in such a way that the project appears to be installed, but yet is still
editable from the src tree](https://packaging.python.org/en/latest/tutorials/installing-packages/)"
— and pytest's own good-practices page recommends exactly this: "`pip install
-e .` which lets you change your source code (both tests and application) and
rerun tests at will".

The difference between the two is not convenience. An editable install makes
the module importable from **every** tool, forever — this CLI, a notebook, a
production entrypoint, a colleague's debugger — and it is recorded in a file
that already exists to say what this project is. A path entry makes it
importable from one tool, and only while that tool is the one running.

**A comparable tool solved exactly this, and the way it solved it is the
shape adopted here.** Alembic's `prepend_sys_path`, from the commit that
introduced it:

> Added new config file option `prepend_sys_path`, which is a series of paths
> that will be prepended to `sys.path`; the default value in newly generated
> `alembic.ini` files is ".". This fixes a long-standing issue where for some
> reason running the alembic command line would not place the local "." path
> in `sys.path`, meaning an application locally present in "." and importable
> through normal channels, e.g. python interpreter, pytest, etc. would not be
> located by Alembic […]
> — [sqlalchemy/alembic@d6b0c1a](https://github.com/sqlalchemy/alembic/commit/d6b0c1af3df98b50c6ec52781aa411592c4e0c32)

That is our defect, in a migration tool, with the reporter's own words for the
symptom that made it confusing: *importable through normal channels, and not
by this command*.

### What was rejected

**Implicit discovery — walk up for a `pyproject.toml` and prepend it.** It is
the obvious move and it is the one the prior art argues against most directly.
Three costs, and the third is the one that settles it:

- It changes what an untrusted package can shadow. A prepended project root is
  a directory that outranks the stdlib for every module the process loads
  afterwards. That is a real consequence of a decision nobody made.
- It is invisible. There is no file to grep, no line in review, and no way for
  a reader to tell whether `import myapp` worked because of the project's
  layout or because of us.
- **It would not be turn-off-able without inventing a second mechanism** — a
  flag or an environment variable whose only job is to undo an implicit
  behaviour. A setting that exists only to disable a default nobody asked for
  is a worse surface than the setting that enables it.

**A command-line flag.** A path a run needs is a property of the project, not
of the invocation. As a flag it has to be typed on every command by every
person and every CI step, and the first thing anybody does is wrap it in a
shell alias — which is `PYTHONPATH` again, with more syntax.

### What was chosen

**Nothing is injected implicitly. The opt-in is a key in the committed config
file, and it is spelled the way Alembic spells it.**

```yaml
# openstategraph.yaml
prepend_sys_path:
  - "."
```

- **Relative to the file, never to the working directory** — the rule
  `workflows_dir:` already follows, for the reason that file is committed:
  its meaning must not depend on which subdirectory a colleague was standing
  in.
- **Process-level only.** `console_main` applies it; `main` does not. This is
  the boundary `.env` loading already observes one line up: a *process* the
  user launched may reconfigure their interpreter from a file on disk, and a
  *function* this repository's own tests call in-process may not, or every
  test that runs afterwards inherits it.
- **A directory that is not there is not added**, and the return value says
  what was.
- **`openstategraph init` writes it**, with `"."`, and with a comment saying
  what it does and that deleting the line turns it off. That is Alembic's
  default-in-generated-files precedent, and it is what makes the opt-in an
  opt-in rather than a footnote: a setting nobody is told about is not a
  choice anybody made.

**It is the second-best answer and the messages say so.** The import failure
names `pip install -e .` first, because that is what the ecosystem
recommends and what buys importability everywhere rather than here. The
config key is for code that is not a distribution and is not going to become
one — a `scripts/` directory, a service laid out flat, a repository whose
build is somebody else's problem this quarter.

## What this does not change

The library path is untouched. `load_workflow` and `Workflows()` import a
package's `tools/` with the interpreter's own `sys.path` and add nothing,
which is why the in-process column of the table above was already clean: the
process that called them had put its own directory there.
