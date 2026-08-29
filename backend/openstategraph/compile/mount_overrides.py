"""Per-mount configuration: how a parent narrows the package it mounts.

Carved out of `compile/node_runtime.py` (`docs-and-gaps/03`, step 2 of the
recommended order), unchanged. It came out first because it is the cheapest
seam in the file: four names, no `self`, no `RunState`, no model — a pure
function over two dicts that `test_mount_overrides.py`,
`test_mount_adversarial.py`, `test_mount_effective_document.py` and
`test_override_target_is_named.py` already cover as a unit.

**The one reason to change is the override contract itself** —
`docs/decisions/mount-overrides.md` — and that is a different reason from
"what a node does when it runs", which is what the file it left owns. The two
had been sharing a module only because the mount *builder* is the caller.

Every name here is re-exported from `compile.node_runtime`, underscore ones
included, because the seam is ours and an importer's spelling is not:
`api/mount_resolution.py` and `api/routes/workflows.py` both name
`apply_mount_overrides` as this system's single owner of the merge, and they
say so in prose that would have to be re-verified if the import moved.
"""

from __future__ import annotations

import copy
import json
from typing import Any


#: Override keys that are refused rather than applied.
#:
#: `workflow` names the package a mount runs, so overriding it does not
#: *configure* the mount — it replaces what the mount **is**, from a data field
#: nothing surfaces. The card would go on naming the original package while the
#: run executed a different one, and `MountEditScope` already refuses shape
#: changes per instance in the editor; this closes the same door on the data
#: path. Reserved rather than blessed (owner decision, 2026-08-13): an override
#: narrows a mount, it never redirects it.
#:
#: Safe as a bare key name: `workflow` is declared by `workflow.subgraph` and
#: by no other node type, so reserving it cannot shadow an unrelated field.
RESERVED_OVERRIDE_KEYS = frozenset({"workflow"})


def _as_override_map(value: Any) -> dict[str, Any] | None:
    """One override blob as a dict, accepting both spellings, or None.

    The inspector writes a JSON *string*; a hand-authored document and the
    compiler's own recursion write a dict. Both are one contract, so both are
    parsed in one place rather than at each call site.
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return value if isinstance(value, dict) else None


def _merge_override_maps(existing: Any, incoming: Any) -> tuple[Any, list[str]]:
    """Merge two override blobs, field by field, with `incoming` winning ties.

    **`overrides` is the one key this system may merge**, and the distinction
    is the whole reason this function is narrow. Every other field is opaque
    node data — a developer's prompt, a threshold, a model name — and merging
    those would mean inventing semantics for lists and nested objects the
    document never promised. `mount-overrides.md` rejected that outright, and
    it still is rejected: a plain field is replaced, exactly as before.

    But `overrides` is *ours*. Its shape is `{childNodeId: {field: value}}`,
    defined by this module, and shallow-replacing it destroys information
    nobody asked to discard: a package that pins its own grandchild's setting
    loses it the moment an ancestor overrides any *other* field of that same
    mount. That is the defect this exists to fix — silent, and the run reported
    no warning at all.

    Recursive, because a nested `overrides` may itself contain one: an edit at
    the root can address a great-grandchild, and every level down is the same
    merge with the same rule.
    """
    base = _as_override_map(existing)
    over = _as_override_map(incoming)
    if over is None:
        # An unreadable incoming blob must not delete a readable existing one.
        return (existing if base is None else base), (
            [] if incoming in (None, "", {}) else
            ["a nested overrides value is not valid JSON — the deeper override was ignored"]
        )
    if base is None:
        return over, ([] if existing in (None, "", {}) else
                      ["a nested overrides value is not valid JSON — it was replaced"])

    merged = dict(base)
    warnings: list[str] = []
    for node_id, fields in over.items():
        current = merged.get(node_id)
        if not isinstance(current, dict) or not isinstance(fields, dict):
            merged[node_id] = fields
            continue
        combined = dict(current)
        for key, value in fields.items():
            if key == "overrides":
                combined[key], notes = _merge_override_maps(current.get(key), value)
                warnings += notes
            else:
                combined[key] = value
        merged[node_id] = combined
    return merged, warnings


def apply_mount_overrides(
    child_document: dict[str, Any],
    overrides: Any,
    *,
    applied: list[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Per-mount configuration for a shared package (docs/decisions/mount-overrides.md).

    ``overrides`` is the mount node's ``data.overrides``:
    ``{"<childNodeId>": {"<fieldKey>": value}}`` — plain JSON keyed by the
    child document's own vocabulary. Applied shallowly, per field, to a COPY;
    the package on disk is the single source of truth and the compile seam
    stays one-directional. An unknown child node id warns loudly and runs on
    the package default — a typo degrading audibly beats a run that cannot
    start.

    ``applied``, when passed, is appended to in place with one
    ``(child_node_id, field_key)`` pair per field this call actually wrote —
    this is the one place that knows which write succeeded, so it is the one
    place that can say so (`launch-readiness` 40). An out-parameter rather
    than a wider return, deliberately: this function is the single owner of
    the merge (`api/mount_resolution.py`'s docstring says so) and over a dozen
    call sites destructure a 2-tuple; widening the return would touch every
    one of them for a fact only the mount-resolution call site needs.
    """
    if not overrides:
        return child_document, []
    if isinstance(overrides, str):
        # The inspector edits this field as a JSON textarea, so a saved
        # document carries the string form; both spellings are one contract.
        try:
            overrides = json.loads(overrides)
        except ValueError:
            return child_document, ["overrides is not valid JSON — the package defaults ran"]
        if not overrides:
            return child_document, []
    if not isinstance(overrides, dict):
        return child_document, [
            f"overrides must be a mapping of child node id -> fields, got {type(overrides).__name__}"
        ]

    warnings: list[str] = []
    document = copy.deepcopy(child_document)
    by_id = {n.get("id"): n for n in document.get("nodes") or []}
    for node_id, fields in overrides.items():
        target = by_id.get(node_id)
        if target is None:
            warnings.append(
                f'override targets unknown child node "{node_id}" — the package default ran'
            )
            continue
        if not isinstance(fields, dict):
            warnings.append(
                f'override for "{node_id}" must be a mapping of field -> value — ignored'
            )
            continue
        data = target.setdefault("data", {})
        for key, value in fields.items():
            if key in RESERVED_OVERRIDE_KEYS:
                warnings.append(
                    f'override for "{node_id}" tried to set "{key}" — that field '
                    "selects which workflow the mount runs, and an override may "
                    "narrow a mount, never replace it. Ignored."
                )
                continue
            if key == "overrides":
                # The one key whose shape this module owns, so the one key it
                # may merge rather than replace. See `_merge_override_maps`.
                data[key], notes = _merge_override_maps(data.get(key), value)
                warnings += notes
                if applied is not None:
                    applied.append((node_id, key))
                continue
            if value is None:
                # Applied, not skipped — `None` may be a legitimate value for a
                # nullable field and this module does not get to decide the
                # author meant something else. But it is reported, because the
                # editor never writes one: `MountContext.clearOverride` removes
                # the key instead, precisely so a "cleared" field is not an
                # override of `null` that the card keeps counting. A `null`
                # here is therefore always hand-written, and ambiguous between
                # "make it null" and "I meant to remove this".
                warnings.append(
                    f'override sets "{node_id}.{key}" to null, which overrides the '
                    "package value rather than restoring it — remove the key to "
                    "restore the default"
                )
            data[key] = value
            if applied is not None:
                applied.append((node_id, key))
    return document, warnings


__all__ = [
    "RESERVED_OVERRIDE_KEYS",
    "apply_mount_overrides",
]
