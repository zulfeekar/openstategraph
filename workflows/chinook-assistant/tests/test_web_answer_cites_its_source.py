"""The web branch may not publish a figure it does not attribute.

`every-workflow-green/44`. `agent-web` holds `tool.web-search` and
`tool.web-fetch`, both declaring `open_world = True`, and its `result` ran
straight into `out1`. The compiler said so on `load_workflow` alone, and the
sentence it said is the specification for this function:

> A quantity that arrives that way looks exactly like one your data returned,
> and nothing downstream can tell them apart.

So the check is not *"is this figure true"* — nothing here can know that. It is
*"can a reader tell where this figure came from"*, and on this branch there is
exactly one honest answer to that: the URL of the page it was read from.
`agent-web`'s own prompt already ends *"Cite the URL you used"*; until now
nothing made that a condition of publishing.

**Why a package function and not a built-in.** The three checks core supplies
all need the run's *evidence* rather than its text. This one needs only the
text, which is the ordinary `fn(text) -> str` seam — and it is a statement
about this package's web branch, not about every graph.
"""

from __future__ import annotations

from functions.cited_figures import web_answer_cites_its_source


class TestAnswersThatPass:
    def test_a_figure_beside_the_url_it_was_read_from(self) -> None:
        answer = (
            "Thriller has sold about 70 million copies worldwide.\n"
            "Source: https://en.wikipedia.org/wiki/Thriller_(album)"
        )
        assert web_answer_cites_its_source(answer) == ""

    def test_an_answer_with_no_figure_at_all(self) -> None:
        # Nothing to attribute, so nothing to refuse. A refusal is the case
        # that matters: the branch must still be able to say it found nothing.
        answer = "The pages I read disagree, so I would rather not put a number on it."
        assert web_answer_cites_its_source(answer) == ""

    def test_a_percentage_is_not_a_candidate(self) -> None:
        # `quantities_in` is core's candidate rule, imported rather than
        # re-implemented — a share is arithmetic over figures, not a claim.
        assert web_answer_cites_its_source("Roughly 40% of them were reissues.") == ""

    def test_a_plain_http_url_counts(self) -> None:
        assert web_answer_cites_its_source("It was 1994. http://example.org/a") == ""


class TestAnswersThatAreSentBack:
    def test_a_figure_with_no_source_anywhere(self) -> None:
        reason = web_answer_cites_its_source(
            "Thriller has sold about 70 million copies."
        )
        assert reason
        assert "70" in reason

    def test_the_reason_names_every_unattributed_figure_once(self) -> None:
        reason = web_answer_cites_its_source(
            "It ran 12 weeks in 1984, and 12 again after."
        )
        assert "12" in reason and "1984" in reason
        assert reason.count("12") == 1

    def test_naming_a_publication_is_not_citing_a_page(self) -> None:
        # The failure `agent-chat`'s prompt calls "the single worst thing you
        # can do here", one branch along: a source named from memory reads
        # exactly like a source read.
        reason = web_answer_cites_its_source("Billboard reported 70 million copies.")
        assert reason

    def test_it_is_a_sentence_for_the_model_to_act_on(self) -> None:
        # The return travels `revise` -> `agent-web.feedback`, so it is
        # developer- and model-facing text, and it must say what to do next.
        reason = web_answer_cites_its_source("About 70 million copies.")
        assert "web_fetch" in reason or "fetch" in reason
