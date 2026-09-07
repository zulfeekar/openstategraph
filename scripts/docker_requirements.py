"""Flatten pyproject extras into requirements.txt for the Docker image.

The image must install exactly what ``openstategraph[all]`` means — no more.
Two facts make the naive flattener (every extra except ``all``/``dev``) wrong:

1. Extras may be **self-referential** (``server = ["openstategraph[sqlite]",
   …]``). Copied verbatim into a requirements file, pip goes looking for
   ``openstategraph`` on an index it is not published to and the build dies
   with ``No matching distribution found`` — which is how this script was
   born (the compose build had been red since the extra gained the
   self-reference).
2. ``all`` is a **curated** union, and its exclusions are decisions:
   ``bastion`` stays out on licence grounds (see the guardrails map). A
   flattener with its own exclusion list is a second copy of that decision,
   and second copies drift. This script has no list of its own — it walks
   whatever ``all`` names.
"""

from __future__ import annotations

import pathlib
import re
import sys
import tomllib

_SELF_REF = re.compile(r"^openstategraph\[(?P<extras>[^\]]+)\]\s*$")


def flatten(pyproject: pathlib.Path) -> list[str]:
    project = tomllib.loads(pyproject.read_text())["project"]
    optional = project.get("optional-dependencies", {})

    requirements: list[str] = list(project["dependencies"])
    seen: set[str] = set()

    def expand(extra: str) -> None:
        if extra in seen:
            return
        seen.add(extra)
        for requirement in optional[extra]:
            match = _SELF_REF.match(requirement)
            if match:
                for nested in match.group("extras").split(","):
                    expand(nested.strip())
            else:
                requirements.append(requirement)

    expand("all")
    return requirements


if __name__ == "__main__":
    target = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("requirements.txt")
    lines = flatten(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "pyproject.toml"))
    target.write_text("\n".join(lines) + "\n")
