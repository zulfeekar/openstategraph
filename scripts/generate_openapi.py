#!/usr/bin/env python3
"""Regenerate the committed OpenAPI snapshot at `docs/openapi.json`.

    python3 scripts/generate_openapi.py

All the reasoning — why a document FastAPI already serves is also committed,
and what it structurally cannot cover — is in
`openstategraph/api/openapi_document.py`, which is also where the one
implementation lives. This file is the command line and nothing else, so the
snapshot the drift test compares against and the snapshot this writes cannot
be produced two different ways.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openstategraph.api.openapi_document import write_snapshot  # noqa: E402


def main() -> int:
    print(f"wrote {write_snapshot()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
