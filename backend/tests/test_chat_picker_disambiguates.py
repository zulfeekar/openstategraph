"""Two published packages of one name reach `/chat` as two identical options.

The-editor-makes-a-real-package 07. A new document is called "AI Workflow"
(a constant), most people save before renaming at least once, and the second
save minted a second package in silence. The customer picker then rendered:

    <option value="ai-workflow-tsi934">AI Workflow</option>
    <option value="ai-workflow">AI Workflow</option>

Two indistinguishable choices, the default one arbitrary from the customer's
side, and selecting the "wrong" one and asking a question is not an error
anyone can detect.

Source assertions, for the reason `test_terminal_frame.py` records: `chat.html`
is a dependency-free page with no JS test harness in this repository, and the
alternative to pinning it here is pinning it nowhere.
"""

from __future__ import annotations


def _page() -> str:
    from openstategraph.api.chat_page import chat_page_html

    return chat_page_html()


def _render_picker() -> str:
    page = _page()
    return page.split("function renderPicker(")[1].split("\nfunction ")[0]


class TestThePickerCanTellTwoOfANameApart:
    def test_it_computes_which_names_are_duplicated(self) -> None:
        body = _render_picker()

        assert "duplicated" in body
        # Case- and whitespace-insensitive, because "AI Workflow" and
        # "ai workflow " are the same name to a reader.
        assert ".trim().toLowerCase()" in body

    def test_a_duplicated_name_carries_its_slug(self) -> None:
        body = _render_picker()

        assert "${esc(w.name)} — ${esc(w.slug)}" in body

    def test_a_unique_name_is_left_alone(self) -> None:
        """A customer picker should not wear folder names it does not need —
        the slug is the exception, the way the collision suffix is."""
        body = _render_picker()
        label = body.split("const optionLabel")[1].split(";")[0]

        assert "duplicated.has(" in label
        assert "esc(w.name)" in label

    def test_the_option_value_is_still_the_slug(self) -> None:
        """The label changed; the identity on the wire did not."""
        body = _render_picker()

        assert '<option value="${esc(w.slug)}">${optionLabel(w)}</option>' in body
