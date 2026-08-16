"""Where `workflows/<slug>/` lives when nobody names a root.

**Tier 2, provisional.** One module, one question, because until the wheel was
installed in a clean venv there were **four** different answers to it, all
computed the same wrong way:

    Path(__file__).resolve().parents[2] / "workflows"

That is the repository root *when this file is inside the checkout*. Inside an
installed wheel it is `<venv>/lib/python3.13/workflows` — a directory that does
not exist and never will. The clean-venv proof (ticket 06) caught what that
costs, and it is the failure class this codebase treats as the worst kind:
`tool.platform-list-workflows` answered **"No workflows exist yet."** — calmly,
confidently, with the adopter's workflows sitting right there in their project
— because it was looking inside site-packages. The SQL tools refused every
database path for the same reason, and the email tool's dry-run `.eml` files
would have been written into the virtualenv.

So the root is resolved **per call**, from five sources in order — the
project-wide precedence rule, `convention < the checkout < config file <
environment < explicit argument`, with the explicit argument owned by the caller
(`Workflows(root)`, `WorkflowStore(root=)`, `load_workflow`'s package path)
and the other four answered here:

1. **`OPENSTATEGRAPH_WORKFLOWS_ROOT`** — the deployment's own answer, and the
   only one that works when the workflows live somewhere unguessable.
2. **`workflows_dir:` in `openstategraph.yaml`** — the project's committed
   answer, resolved relative to the config file (see
   `config_file.configured_workflows_dir` for why not the cwd). Below the
   environment for the same reason every other key is: the file is shared, the
   environment is the machine in front of you.
3. **The checkout**, when this file is genuinely inside one. Keeps every
   in-tree behaviour byte-identical: the editor, the tests and `./start dev`
   see exactly what they saw before.
4. **`./workflows` under the process's working directory** — the convention
   `openstategraph new` already writes to, so the first thing an adopter
   scaffolds is in the first place we look.

Per call, not per import, because a constant frozen at import time is how (3)
became a wrong answer that nothing could override. And a *function*, never a
`set_workflows_root()`: process-wide mutable state is how two callers in one
process come to disagree about which directory they are reading, with no
argument anywhere in either call to explain the difference.

**This module answers where we READ.** Where we WRITE is
`openstategraph.state_dir`, and they are deliberately not the same question —
see that module.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The deployment's explicit answer. Absolute, and it wins over everything.
WORKFLOWS_ROOT_ENV = "OPENSTATEGRAPH_WORKFLOWS_ROOT"

#: `backend/openstategraph/workflows_root.py` → the repository root, *if* this
#: file is inside a checkout. Resolved once because a file does not move.
_MAYBE_CHECKOUT = Path(__file__).resolve().parents[2]


def checkout_root() -> Path | None:
    """The repository this module was imported from, or None when installed.

    Both markers are required. `workflows/` alone would match a venv that
    happened to have one beside it; `backend/` alone would match nothing
    useful. Together they say "this is the OpenStateGraph source tree".
    """
    if (_MAYBE_CHECKOUT / "workflows").is_dir() and (_MAYBE_CHECKOUT / "backend").is_dir():
        return _MAYBE_CHECKOUT
    return None


def workflows_root() -> Path:
    """The directory that holds `<slug>/workflow.json` packages."""
    configured = os.environ.get(WORKFLOWS_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    # Lazy: `import openstategraph` must stay cheap, and this pulls pydantic.
    from openstategraph.config_file import configured_workflows_dir

    from_file = configured_workflows_dir()
    if from_file is not None:
        return from_file
    checkout = checkout_root()
    return (checkout / "workflows") if checkout else (Path.cwd() / "workflows")


def content_root() -> Path:
    """The jail for the read-only platform tools — one level above the packages.

    In a checkout that is the repository, which is what those tools were
    written against. Installed, it is the adopter's project directory rather
    than the interpreter's `lib/`, which is both more useful and much less
    alarming than handing an agent a read grep over site-packages.
    """
    return workflows_root().parent


__all__ = ["WORKFLOWS_ROOT_ENV", "checkout_root", "content_root", "workflows_root"]
