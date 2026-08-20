"""The shape a generated module must have — one place, read by a test and a skill.

`every-workflow-green` 34. A run that finds nothing in the library for what it
was asked shows a door — *"Nothing here does this. Build one for this
workflow?"* — and pressing it seeds the chat with a brief. That door shipped on
2026-08-19. What did not ship is this: **a single contract the brief, the build
skill and a test all read**, so the module that comes back is checked rather
than hoped for.

## Why the contract is data and not prose

Because prose has no way to fail, and this file's own subject proves it.

The brief's central rule read *"it reads state, context and memory through
`ToolRuntime`, not around it"* — and `ToolRuntime` **does not exist in this
platform**. It is a LangChain construct we do not surface;
`docs/decisions/special-agents-2026-08.md` records the mechanism as *"new
mechanism — flagged, not decided"*, with `grep` for `Runtime[` across the
backend returning nothing. Seven tests held that sentence, all green, because
every one of them asked whether the **words** were there. None asked whether
the thing the words name **exists here**.

So a clause carries its `seam`: the symbols in *this installation* it depends
on. `resolve_seam` imports each one, and a clause naming something unresolvable
fails a test rather than shipping as an instruction.

## What a tool can actually reach here

Worth stating plainly, because the wrong answer was published for a day:

- **its node's config** — `BaseTool.configure(data)`, reading exactly the keys
  its `node_fields` declare;
- **the run** — `langgraph.config.get_config()["configurable"]`, which is how
  `prebuilt_session.SessionIdentityTool` learns who it is talking to;
- **memory** — `langgraph.config.get_store()`, as `memory.py` does;
- **graph state — not at all.** `BaseTool.run` validates `**kwargs` into
  `Args` and calls `_execute(args)`. There is no third argument and no ambient
  accessor. A design needing graph state belongs in a node, not a tool.

## What this checker does not do

It reads the module with `ast`; it never imports it. Discovery imports a
workflow's `tools/` and says so as a known risk (`api/capability_discovery.py`:
*"Import executes code"*); a **gate** that must execute the thing it is gating
is not a gate. The cost is that everything here is structural: a class that
subclasses `BaseTool` through an alias, or a key assembled at run time, is
invisible — the same limit `test_data_key_contract` accepts for the same
reason, and for the same fix (keep the key a literal at the point of use).
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import dataclass
from pathlib import Path

from openstategraph.config_file import SECRET_VALUE_PREFIXES

__all__ = [
    "CLAUSES",
    "Clause",
    "Violation",
    "check_generated_module",
    "resolve_seam",
]


@dataclass(frozen=True)
class Clause:
    """One rule of the shape, in the words the developer is handed."""

    #: Stable slug. A `Violation` and the brief's mirror test both key on it.
    id: str
    #: The single line printed in the brief. Kept short on purpose — it has to
    #: read as an instruction in a chat composer, not as documentation.
    rule: str
    #: The evidence that put it here. A gate whose reason is lost gets argued
    #: away by the next person.
    why: str
    #: Symbols in *this* installation the rule depends on. Every one must
    #: resolve, or the rule is a promise the platform cannot keep.
    seam: tuple[str, ...] = ()


@dataclass(frozen=True)
class Violation:
    clause: str
    detail: str


#: Named, not derived — the lesson of gate 13's `SECRET_VALUE_PREFIXES`, where
#: an elegant rule ("a credential always contains a hyphen") was false and a
#: literal list was correct.
#:
#: A seam here may well be importable from some installed distribution. That is
#: exactly why a plain "does it import?" check is not enough: `ToolRuntime` is
#: real in LangChain and unreachable from a tool built on *our* `BaseTool`,
#: whose `run()` calls `_execute(args)` with no runtime argument at all. A
#: module naming one of these was written against a different product's docs.
UNWIRED_SEAMS: dict[str, str] = {
    "ToolRuntime": (
        "ToolRuntime is LangChain's injected-runtime seam and this platform "
        "does not surface it — a tool receives its validated Args and nothing "
        "else. Take config through configure(data), the run through "
        "langgraph.config.get_config(), and memory through get_store()."
    ),
    "get_state": (
        "A tool cannot read graph state here; BaseTool.run calls "
        "_execute(args). A design that needs state belongs in a node."
    ),
}


CLAUSES: tuple[Clause, ...] = (
    Clause(
        id="package-own-tools",
        #: `{package}` is the one placeholder in any clause. The brief fills
        #: it with the workflow's slug, because a developer can act on a path
        #: faster than on a description of a path.
        rule=(
            "it lives in the {package} package's own tools/ folder, beside "
            "its workflow.json — never in the installed package"
        ),
        why=(
            "`workflows/` is only the convention: the root is resolved per call "
            "from OPENSTATEGRAPH_WORKFLOWS_ROOT, then workflows_dir: in "
            "openstategraph.yaml, then the checkout, then ./workflows. A brief "
            "naming a literal path is wrong for anyone who configured one and "
            "wrong inside a wheel — the exact failure workflows_root.py exists "
            "to end. 'Never the installed package' is the half that is "
            "testable and root-independent."
        ),
        seam=("openstategraph.workflows_root:workflows_root",),
    ),
    Clause(
        id="run-seams",
        rule=(
            "it takes config through configure(data), the run through "
            "langgraph.config.get_config(), and memory through get_store() — "
            "a tool cannot read graph state"
        ),
        why=(
            "The clause this replaced named ToolRuntime, which does not exist "
            "in this platform, and seven green tests never noticed because "
            "they asked whether the words were present rather than whether the "
            "seam was. These three are what prebuilt_session and memory.py "
            "actually use."
        ),
        seam=(
            "openstategraph.abc.tool:BaseTool.configure",
            "langgraph.config:get_config",
            "langgraph.config:get_store",
        ),
    ),
    Clause(
        id="ladder",
        rule=(
            "it is a concrete leaf on the existing tool ladder — a BaseTool "
            "subclass that implements _execute"
        ),
        why=(
            "Interface -> Abstract -> Base -> Concrete, and a free function "
            "that happens to be callable is on none of it. Discovery agrees: "
            "folder scopes where to look, subclassing decides what counts."
        ),
        seam=(
            "openstategraph.abc.tool:BaseTool",
            "openstategraph.abc.tool:BaseTool._execute",
        ),
    ),
    Clause(
        id="declared",
        rule=(
            "it declares its card fields in node_fields and reads exactly those keys in configure"
        ),
        why=(
            "Honesty gate 7. A factory reading an undeclared key does not "
            'fail — it reads "" forever, and that defect shipped three times '
            "before test_data_key_contract made the fourth impossible."
        ),
        seam=(
            "openstategraph.abc.tool:ToolField",
            "openstategraph.abc.tool:BaseTool.node_fields",
        ),
    ),
    Clause(
        id="no-credential-value",
        rule="any credential is named as an environment variable, never a value",
        why=(
            "A package is committed. Gate 13, and the reason the check is a "
            "list of known prefixes rather than a rule: ghp_aaaa... is a "
            "GitHub token and a legal variable name at the same time."
        ),
        seam=("openstategraph.config_file:SECRET_VALUE_PREFIXES",),
    ),
)


def resolve_seam(symbol: str) -> object | None:
    """`module:dotted.attr` -> the object, or `None` if it is not here.

    Deliberately returns rather than raises: the caller is a test reporting
    *every* unresolved clause at once, and one exception would hide the rest.
    """
    module_name, _, attribute_path = symbol.partition(":")
    try:
        target: object = importlib.import_module(module_name)
    except Exception:
        return None
    for part in filter(None, attribute_path.split(".")):
        target = getattr(target, part, None)
        if target is None:
            return None
    return target


def _is_installed_package(path: Path) -> bool:
    import openstategraph

    installed = Path(openstategraph.__file__).resolve().parent
    try:
        path.resolve().relative_to(installed)
    except ValueError:
        return False
    return True


def _package_dir_of(path: Path) -> Path | None:
    """The package a `tools/` module belongs to — `workflow.json`'s own folder.

    Anchored on the document rather than on a directory name, so it holds
    whatever the root is called.
    """
    parent = path.resolve().parent
    if parent.name != "tools":
        return None
    package = parent.parent
    return package if (package / "workflow.json").exists() else None


def _tool_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Name) and base.id == "BaseTool")
            or (isinstance(base, ast.Attribute) and base.attr == "BaseTool")
            for base in node.bases
        )
    ]


def _node_type_of(cls: ast.ClassDef) -> str:
    for node in cls.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "node_type" for t in node.targets)
            and isinstance(node.value, ast.Constant)
        ):
            return str(node.value.value)
    return ""


def _catalogue_keys(node_type: str) -> frozenset[str]:
    """Keys the editor's own field schema declares for this node type.

    The second legitimate spelling of the same schema, and the reason this is
    not simply `node_fields`: a **built-in** node's card is TypeScript, so its
    keys arrive through `port_specs.json` — which is what
    `test_data_key_contract` reads and what `ExecuteSqlTool`'s `maxRows` is
    declared by. A *generated* module has no TypeScript half (a third party
    cannot add a file to this repo), so for anything this contract gates the
    catalogue is empty and `node_fields` is the only route left. Consulting it
    anyway is what lets the contract be calibrated against a module that
    already ships rather than against a fixture written to pass it.
    """
    if not node_type:
        return frozenset()
    try:
        from openstategraph.compile.node_catalogue import load_catalogue

        return load_catalogue().field_keys.get(node_type, frozenset())
    except Exception:
        return frozenset()


def _declared_keys(cls: ast.ClassDef) -> set[str]:
    """Every `ToolField(key=...)` in this class's `node_fields`."""
    keys: set[str] = set()
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name != "ToolField":
            continue
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant):
                keys.add(str(keyword.value.value))
        if node.args and isinstance(node.args[0], ast.Constant):
            keys.add(str(node.args[0].value))
    return keys


def _read_keys(cls: ast.ClassDef) -> set[str]:
    """Every literal key read out of `data` inside `configure`."""
    keys: set[str] = set()
    for node in cls.body:
        if (
            not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            or node.name != "configure"
        ):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "get"
                and inner.args
                and isinstance(inner.args[0], ast.Constant)
                and isinstance(inner.args[0].value, str)
            ):
                keys.add(inner.args[0].value)
            if (
                isinstance(inner, ast.Subscript)
                and isinstance(inner.slice, ast.Constant)
                and isinstance(inner.slice.value, str)
            ):
                keys.add(inner.slice.value)
    return keys


def check_generated_module(path: Path, *, exists_check: bool = True) -> tuple[Violation, ...]:
    """Every clause this file can check structurally, against one module.

    `exists_check=False` lets a caller ask about a path that has not been
    written yet — which is the interesting question, since the whole point is
    to refuse before the write rather than after it.
    """
    path = Path(path)
    violations: list[Violation] = []

    if _is_installed_package(path):
        violations.append(
            Violation(
                "package-own-tools",
                f"{path} is inside the installed distribution, which is the "
                "framework we ship and is read-only in every real install.",
            )
        )
    elif _package_dir_of(path) is None:
        violations.append(
            Violation(
                "package-own-tools",
                f"{path} is not a tools/ module beside a workflow.json.",
            )
        )

    if exists_check and not path.exists():
        return tuple(violations)
    if not path.exists():
        return tuple(violations)

    source = path.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return (*violations, Violation("ladder", f"{path} does not parse: {exc}"))

    for name, reason in UNWIRED_SEAMS.items():
        if any(
            (isinstance(node, ast.Name) and node.id == name)
            or (isinstance(node, ast.Attribute) and node.attr == name)
            or (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value == name
            )
            or (isinstance(node, ast.alias) and node.name == name)
            for node in ast.walk(tree)
        ):
            violations.append(Violation("run-seams", f"{name}: {reason}"))

    classes = _tool_classes(tree)
    # `__init__.py` is a package's re-export file, never the module the
    # interview produced. Discovery draws the same line for the same reason —
    # a bare "any public class" rule would count a re-export as a capability —
    # so a caller sweeping a whole `tools/` folder does not get a false
    # violation for the one file that is allowed to hold no tool.
    if not classes and path.name != "__init__.py":
        violations.append(
            Violation(
                "ladder",
                f"{path} defines no BaseTool subclass, so nothing in it is a "
                "capability — discovery would list none of it.",
            )
        )
    for cls in classes:
        implemented = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_execute"
            for node in cls.body
        )
        if not implemented:
            violations.append(
                Violation(
                    "ladder",
                    f"{cls.name} never implements _execute, so it stays "
                    "abstract and can never be instantiated.",
                )
            )
        declared = _declared_keys(cls) | set(_catalogue_keys(_node_type_of(cls)))
        undeclared = sorted(_read_keys(cls) - declared)
        if undeclared:
            violations.append(
                Violation(
                    "declared",
                    f"{cls.name}.configure reads {undeclared} which no "
                    'node_fields entry and no field schema declares — it will read "" forever.',
                )
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(SECRET_VALUE_PREFIXES):
                violations.append(
                    Violation(
                        "no-credential-value",
                        f"a literal beginning {node.value[:6]!r} is a credential "
                        "value; name the environment variable instead.",
                    )
                )

    return tuple(violations)
