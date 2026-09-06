"""One product, one version — pinned, because the drift was silent.

`backend/pyproject.toml` said `0.3.0rc1` and `package.json` said `0.2.0`, a
whole minor apart, and nothing anywhere failed. It could not fail: the editor
is `"private": true`, is never `npm publish`ed, and ships *inside* the Python
wheel, so its version string is read by nobody. `release.yml` takes the version
from `pyproject.toml` alone.

That is precisely why it needed a pin rather than a one-time correction. A
number no process reads is a number that drifts, and the next reader — a
release engineer deciding what they are shipping, or an adopter reading the
repo — finds two answers and no way to tell which is the product.

**The two can never be string-equal, and that is not a defect to normalise
away.** Python versions are PEP 440 (`0.3.0rc1`); npm versions are SemVer
(`0.3.0-rc.1`). Each file is correct in its own grammar. What must agree is the
*release they describe* — the `major.minor.patch` core — so that is what this
compares, and the pre-release suffix is deliberately not compared: it moves
several times inside one release cycle and syncing it would be churn with no
reader.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _release_core(version: str) -> tuple[int, int, int]:
    """The `major.minor.patch` a version string describes, in either grammar."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    assert match, f"unparseable version {version!r}"
    return (int(match[1]), int(match[2]), int(match[3]))


def test_the_wheel_and_the_editor_describe_one_release() -> None:
    pyproject = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())
    package = json.loads((REPO / "package.json").read_text())

    python_version = pyproject["project"]["version"]
    editor_version = package["version"]

    assert _release_core(python_version) == _release_core(editor_version), (
        f"backend/pyproject.toml is {python_version!r} and package.json is "
        f"{editor_version!r}. These are one product: the editor ships inside "
        "the wheel. Bump both, or explain here why they diverge."
    )


def test_the_editor_is_still_unpublished() -> None:
    """The premise of the test above.

    If the editor ever *is* published to npm, its version stops being cosmetic
    and starts being a contract someone installs — at which point comparing
    only the release core is no longer enough, and this file should be
    revisited rather than quietly kept passing.
    """
    package = json.loads((REPO / "package.json").read_text())
    assert package.get("private") is True, (
        "package.json is no longer private, so its version is now a published "
        "contract. Revisit test_the_wheel_and_the_editor_describe_one_release."
    )
