"""One implementation of a guard, sixteen packages that must all run it.

`osg-agent-experience/58`. A concept whose fifteen specialists became fifteen
mounted packages needs every one of them to run the *same* check, because
sixteen copies of an allowlist check is sixteen checks that can drift apart —
and one that has drifted **wide** fails open. So each package's
`functions/honest_findings.py` loaded the one implementation and re-exported
it:

    honest_findings = _module.honest_findings

`validate` said VALID. The run said *No function found for
"function.ask_back" — the step passed its input through unchanged.*
`discover_function_callables` skips any member whose `__module__` is not the
module being scanned, and a re-export's `__module__` is the module it was
written in.

The guard is right about what it was written for — without it, every
`from textwrap import dedent` in a package function file would register as a
package function. What was wrong is its reach: it asked *which module* rather
than *whose tree*. A module inside the workflows root is a package's own code,
by definition, and sharing one implementation across sibling packages is the
thing the guard was accidentally forbidding.

So: a re-export is admitted when the function was written inside the workflows
root, and the case that stays skipped — a shim binding something from outside
it — says so by name instead of being dropped in silence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.api.capability_discovery import (
    discover_function_callables,
    discover_functions,
)

SHARED = '''
"""The one implementation, in a package of its own."""


def honest_findings(text: str) -> str:
    """Resolve every cited table against the pins."""
    return f"checked: {text}"
'''

#: The shim each specialist package carries. Loaded by path rather than by
#: `import`, because a package folder is named by its slug and a slug may hold
#: a hyphen — which is never a legal module name.
SHIM = '''
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "shared-guards" / "functions" / "guards.py"
_spec = importlib.util.spec_from_file_location("shared_guards_guards", _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

honest_findings = _module.honest_findings
'''

#: The case that is genuinely lost, and the reason the guard exists: a module
#: that defines nothing of its own and binds a name from outside the tree.
OUTSIDER = '''
from textwrap import dedent

trim = dedent
'''


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    packages = tmp_path / "workflows"
    (packages / "shared-guards" / "functions").mkdir(parents=True)
    (packages / "shared-guards" / "functions" / "guards.py").write_text(SHARED)
    (packages / "cargo-lens" / "functions").mkdir(parents=True)
    (packages / "cargo-lens" / "functions" / "honest_findings.py").write_text(SHIM)
    return packages


class TestOneImplementationServesTwoPackages:
    def test_the_shared_function_is_bindable_from_the_package_that_re_exports_it(
        self, root: Path
    ) -> None:
        registry = discover_function_callables(root / "cargo-lens", "cargo-lens")
        assert "function.honest_findings" in registry
        assert registry["function.honest_findings"]("two tables") == "checked: two tables"

    def test_it_is_listed_as_a_capability_of_that_package(self, root: Path) -> None:
        names = {f.name for f in discover_functions(root / "cargo-lens", "cargo-lens")}
        assert "honest_findings" in names

    def test_the_package_that_defines_it_still_owns_it(self, root: Path) -> None:
        registry = discover_function_callables(root / "shared-guards", "shared-guards")
        assert "function.honest_findings" in registry


class TestWhatIsStillSkippedSaysSo:
    def test_a_shim_binding_a_name_from_outside_the_tree_is_named(self, root: Path) -> None:
        package = root / "outsider"
        (package / "functions").mkdir(parents=True)
        (package / "functions" / "trim.py").write_text(OUTSIDER)
        warnings: list[str] = []
        registry = discover_function_callables(package, "outsider", warnings=warnings)
        assert "function.trim" not in registry
        assert warnings, "a whole file that binds nothing must not be silent"
        assert "functions/trim.py" in warnings[0]
        assert "trim" in warnings[0]

    def test_an_ordinary_helper_import_beside_a_real_function_is_not_a_finding(
        self, root: Path
    ) -> None:
        package = root / "quiet"
        (package / "functions").mkdir(parents=True)
        (package / "functions" / "shape.py").write_text(
            "from textwrap import dedent\n\n\ndef shape(text: str) -> str:\n"
            "    return dedent(text)\n"
        )
        warnings: list[str] = []
        registry = discover_function_callables(package, "quiet", warnings=warnings)
        assert "function.shape" in registry
        assert warnings == [], warnings
