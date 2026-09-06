"""`site/behind-the-scenes.html` shows the compiler, not a memory of it.

Production-ready ticket 29. The page walks `evaluator-optimizer` through five
artifacts, and its whole value is that four of them are *taken* from the real
compiler rather than transcribed. A walk-through of what a compiler does, typed
out by hand, is a walk-through of what someone remembers it doing — and this
repository's recurring defect is documentation that says things which used to
be so.

So the generated regions are compared against the compiler here, on every test
run, with no node and no network:

1. **The document** is the committed `workflow.json`, byte for byte.
2. **The plan** is what `ValidateWorkflowTool` prints — the seam
   `openstategraph validate` goes through.
3. **The Mermaid source** is what `draw_mermaid()` draws. The *rendered* SVG
   needs node and is checked by `scripts/build_behind_the_scenes.py --check`;
   its source, which is what the page's prose makes claims about, is checked
   here.
4. **Every prompt layer** is what `SystemPrompt.describe()` returns. This page
   is that method's first caller anywhere in the repository.
5. **Artifact five is hand-written**, deliberately — it is an instruction, not
   an output. So every name it uses is pinned against the real API instead,
   which is the check a generated block would have given for free.

Two further claims the page makes in prose, pinned because prose is where the
stale sentences live: that `--xray` expands nothing today, and that the page
makes no external request at all.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SITE = REPO / "site"
PAGE = SITE / "behind-the-scenes.html"


def _script() -> ModuleType:
    """The generator, imported by path — `scripts/` is not an importable package.

    Imported rather than reimplemented: comparing the page against a *second*
    rendering of the same idea would pass while both were wrong, which is the
    failure mode this whole file exists to prevent.
    """
    path = REPO / "scripts" / "build_behind_the_scenes.py"
    spec = importlib.util.spec_from_file_location("build_behind_the_scenes", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _script()


@pytest.fixture(scope="module")
def regions() -> dict[str, str]:
    """What the committed page currently shows, region by region."""
    text = PAGE.read_text()
    found = {
        name: body
        for name, body in re.findall(
            r"<!--bts:([a-z0-9-]+)-->(.*?)<!--/bts:\1-->", text, flags=re.DOTALL
        )
    }
    assert found, "the page has no generated regions at all"
    return found


class TestTheGeneratedBlocksAreGenerated:
    def test_the_document_is_the_committed_file(
        self, script: ModuleType, regions: dict[str, str]
    ) -> None:
        assert regions["document"] == script.json_html(script.document())

    def test_the_plan_is_what_validate_prints(
        self, script: ModuleType, regions: dict[str, str]
    ) -> None:
        assert regions["plan"] == script.esc(script.plan_text())

    def test_the_mermaid_source_is_what_the_compiler_draws(
        self, script: ModuleType, regions: dict[str, str]
    ) -> None:
        assert regions["mermaid-src"] == script.esc(script.mermaid_text())

    def test_the_rendered_diagram_is_an_svg_and_fetches_nothing(
        self, regions: dict[str, str]
    ) -> None:
        """The SVG itself is re-rendered by `--check`; what matters here is that
        it is inline rather than a link to one."""
        assert regions["mermaid"].startswith("<svg")
        assert "<image" not in regions["mermaid"]

    @pytest.mark.parametrize("node_id", ["draft1", "grader1"])
    def test_every_prompt_layer_is_what_describe_returns(
        self, script: ModuleType, regions: dict[str, str], node_id: str
    ) -> None:
        entry = script.prompt_sections()[node_id]

        assert regions[f"layers-{node_id}"] == script.layers_html(entry)
        assert regions[f"rendered-{node_id}"] == script.esc(entry["render"])
        assert regions[f"describe-{node_id}"] == script.json_html(entry["describe"])
        assert regions[f"builder-{node_id}"] == script.esc(entry["built_by"])

    def test_the_page_shows_every_layer_the_prompt_has(self, script: ModuleType) -> None:
        """A layer quietly dropped from the page's table would be a prompt
        section a reader is told nothing about — the omission is invisible
        precisely because the rest of the page is generated and looks complete."""
        described = script.prompt_sections()["grader1"]["describe"]
        shown = {key for key, _kind, _blurb in script.LAYERS}
        # `render()` composes these; the other keys of `describe()` are the
        # derived view (`effective_rules`) and the editability contract.
        composed = set(described) - {"effective_rules", "editable", "replace_defaults"}

        assert shown == composed


class TestTheClaimsTheProseMakes:
    def test_xray_still_expands_nothing(self) -> None:
        """§3 states this as a fact about the project. An agent is built lazily
        inside its closure and a mount is a closure over the child's
        `invoke()`, so neither is a node LangGraph can x-ray. The day that
        changes, this fails and the paragraph gets rewritten rather than
        quietly becoming false."""
        from openstategraph import load_workflow

        workflow = load_workflow(
            REPO / "backend" / "openstategraph" / "examples" / "evaluator-optimizer"
        )
        graph = workflow.graph

        assert graph.get_graph(xray=True).draw_mermaid() == graph.get_graph(
            xray=False
        ).draw_mermaid()

    def test_the_plan_comes_from_validate_and_the_page_says_so(self) -> None:
        """The research correction: the plan is `validate`, not `graph`.
        `graph` prints Mermaid, which is the artifact after it."""
        text = PAGE.read_text()

        assert "openstategraph validate" in text
        assert "It is <code>validate</code>, not <code>graph</code>" in text


class TestArtifactFiveIsHandWrittenButNotInvented:
    """The Python block is prose — an instruction, not an output. Every name in
    it is checked against the real API, which is what generating it would have
    given for free."""

    @pytest.mark.parametrize(
        "attribute", ["graph", "warnings", "ask", "as_tool", "mermaid", "slug"]
    )
    def test_the_workflow_members_it_names_exist(self, attribute: str) -> None:
        from openstategraph.loader import CompiledWorkflow

        assert hasattr(CompiledWorkflow, attribute) or attribute in getattr(
            CompiledWorkflow, "__annotations__", {}
        )

    @pytest.mark.parametrize("attribute", ["decisions", "outputs", "attempts", "warnings"])
    def test_the_result_members_it_names_exist(self, attribute: str) -> None:
        from openstategraph.loader import RunResult

        assert attribute in getattr(RunResult, "__annotations__", {}) or hasattr(
            RunResult, attribute
        )

    def test_the_snippet_uses_only_those_names(self) -> None:
        """Guards the other direction: a plausible-looking `.attempt` or
        `.decision` that the page invents and nothing rejects."""
        snippet = PAGE.read_text().split('<div class="pane-bar"><span>run_it.py')[1]
        snippet = snippet.split("</pre>")[0]
        used = set(re.findall(r"\b(?:workflow|answer)\.([a-z_]+)", snippet))

        assert used <= {"warnings", "ask", "decisions", "attempts", "graph"}


class TestThePagesFetchNothing:
    """Every page under `site/` is self-contained: inline CSS, inline SVG, no
    font, no script, no CDN. It is the property that lets them be opened from a
    file:// URL, served by a wheel, and read on a plane — and one `<link
    rel=stylesheet>` would end it silently."""

    #: Elements that make the browser go and get something.
    FETCHING = re.compile(
        r"<(script|link|img|iframe|source|video|audio|embed|object|use)\b[^>]*>",
        flags=re.IGNORECASE,
    )
    URLISH = re.compile(r'\b(?:src|href|data|srcset)\s*=\s*"([^"]*)"', flags=re.IGNORECASE)

    @pytest.mark.parametrize("page", sorted(p.name for p in SITE.glob("*.html")))
    def test_no_subresource_leaves_the_page(self, page: str) -> None:
        text = (SITE / page).read_text()

        for tag in self.FETCHING.findall(text) and self.FETCHING.finditer(text):
            for url in self.URLISH.findall(tag.group(0)):
                assert not url.startswith(("http://", "https://", "//")), (
                    f"{page} fetches {url!r} from off-page"
                )

    @pytest.mark.parametrize("page", sorted(p.name for p in SITE.glob("*.html")))
    def test_no_stylesheet_or_font_is_imported(self, page: str) -> None:
        text = (SITE / page).read_text()

        assert "@import" not in text
        assert "@font-face" not in text
        assert not re.search(r"url\(\s*['\"]?https?:", text)


class TestItIsReachable:
    @pytest.mark.parametrize("page", ["index.html", "gallery.html"])
    def test_the_other_pages_link_to_it(self, page: str) -> None:
        """Ticket 28's lesson, applied before it can repeat: a page nothing
        links to is a page nobody finds."""
        assert "behind-the-scenes.html" in (SITE / page).read_text()

    def test_it_links_back(self) -> None:
        text = PAGE.read_text()

        assert 'href="gallery.html"' in text
        assert 'href="index.html"' in text
