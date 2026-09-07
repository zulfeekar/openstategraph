"""`api.audience` binds `capability_gap` twice, and both bindings are real.

Ruff reports `F811 Redefinition of unused capability_gap` here, and the obvious
reading of that — the reading `organisms-first-class` 47 was filed with — is
that a field is declared twice and the first is silently dead. It is not. The
two bindings live in **different namespaces**:

- module level, line 104: `from openstategraph.developer_channel import
  capability_gap as capability_gap` — a re-export of the *function*, deliberate
  and marked as such by the redundant alias, because this module is where every
  transport caller already reaches for the split.
- class body, on `DeveloperChannel`: `capability_gap: str | None` — a **field**
  of a frozen dataclass.

A class body is its own scope and does not leak; the module-level function is
untouched by the field, and the field is untouched by the function. Ruff's F811
is scope-insensitive for this pair, so the violation is a false positive and is
silenced at the field with a reason rather than fixed.

That silence is only safe while both bindings genuinely still work, which is
what this file pins. Neither name may be renamed to make a linter quieter: the
function is a published re-export and the field is on the customer-facing `done`
frame, so both are contract.
"""

from __future__ import annotations

import dataclasses

from openstategraph.api import audience
from openstategraph import developer_channel


class TestBothBindingsSurvive:
    def test_the_module_level_name_is_the_re_exported_function(self) -> None:
        assert callable(audience.capability_gap)
        assert audience.capability_gap is developer_channel.capability_gap

    def test_the_class_level_name_is_a_field_of_the_developer_channel(self) -> None:
        fields = {f.name: f for f in dataclasses.fields(audience.DeveloperChannel)}

        assert "capability_gap" in fields
        assert audience.DeveloperChannel().capability_gap is None

    def test_the_field_carries_its_value_onto_a_developers_frame(self) -> None:
        """The half that would actually break if the wrong binding won."""
        channel = audience.DeveloperChannel(capability_gap="no tool reads a PDF")

        payload = channel.payload(audience.Audience.DEVELOPER)

        # `capabilityGap` on the wire, `capability_gap` on the dataclass: the
        # frame is camelCase because `src/core/runtime/RuntimeClient.ts` reads
        # it as `capabilityGap`. Asserting the snake_case spelling here is what
        # this test did first, and it went red for the right reason.
        assert payload["developer"]["capabilityGap"] == "no tool reads a PDF"

    def test_a_customer_is_never_told_what_the_canvas_lacks(self) -> None:
        channel = audience.DeveloperChannel(capability_gap="no tool reads a PDF")

        assert channel.payload(audience.Audience.CUSTOMER) == {}
