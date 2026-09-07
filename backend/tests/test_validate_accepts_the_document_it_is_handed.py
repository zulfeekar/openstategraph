"""The architect's one mandatory tool rejected what the architect sends.

`every-workflow-green` 13. `workflow-architect` is instructed *"ALWAYS call
this before presenting a workflow"*, and `validate_workflow` typed its only
argument `str` — the document as a JSON string. The model passed the document
as a JSON object, which is the obvious move when the field is called
`document`. Every call came back

    document: Input should be a valid string

and every retry re-appended the whole document to the conversation until the
provider itself answered 500 and the run died with a bare reference id.

The string shape is a real caller's shape — `cli.py` passes `json.dumps(...)`
— so it keeps working. What changes is that encoding the document is no longer
mandatory for a tool whose first act is to decode it.
"""

from __future__ import annotations

import json

from openstategraph.prebuilt_architect import ValidateWorkflowTool

DOCUMENT = {
    "version": 2,
    "name": "Refund or bug",
    "nodes": [
        {"id": "in1", "type": "input.text", "data": {}},
        {"id": "out1", "type": "output.formatted", "data": {}},
    ],
    "edges": [
        {
            "source": {"nodeId": "in1", "portId": "text"},
            "target": {"nodeId": "out1", "portId": "result"},
        }
    ],
}


class TestEitherShapeIsAccepted:
    def test_a_json_string_still_works(self) -> None:
        """`cli.py:251` passes exactly this. It must not regress."""
        result = ValidateWorkflowTool().run(document=json.dumps(DOCUMENT))
        assert "Topology" in str(result)

    def test_a_plain_object_is_accepted(self) -> None:
        """What the model actually sends, and what used to be refused."""
        result = ValidateWorkflowTool().run(document=DOCUMENT)
        assert "Topology" in str(result)

    def test_both_shapes_reach_the_same_verdict(self) -> None:
        as_string = str(ValidateWorkflowTool().run(document=json.dumps(DOCUMENT)))
        as_object = str(ValidateWorkflowTool().run(document=DOCUMENT))
        assert as_string == as_object

    def test_an_envelope_is_still_unwrapped(self) -> None:
        """A saved file is `{"document": {...}}`; both shapes carry it."""
        result = ValidateWorkflowTool().run(document={"name": "x", "document": DOCUMENT})
        assert "Topology" in str(result)

    def test_junk_is_still_refused_clearly(self) -> None:
        assert "JSON" in str(ValidateWorkflowTool().run(document="{not json"))
