"""A figure this package publishes from the web must name the page it came from.

`every-workflow-green/44`. The compiler reports an Output a model-supplied
quantity can reach with no gate on the path, and it names the hazard precisely:

> A quantity that arrives that way looks exactly like one your data returned,
> and nothing downstream can tell them apart.

`agent-web` is the branch that hazard is about. It holds `tool.web-search` and
`tool.web-fetch` and nothing else, so it has no data of its own: every figure it
states was either read off a page or produced from memory, and those two are the
pair a reader cannot separate. This function is what stands between them and
`out1`, wired to a `guard.check` whose `revise` returns to `agent-web`.

## What it asserts, and what it deliberately does not

*Every quantity in the answer must sit beside the URL the answer read it from.*

It cannot ask whether the figure is **true**, and it must not pretend to: a
check that accepted a wrong figure would turn "unverified" into "verified",
which `compile/grounding.py` records as worse than no check at all. It asks the
one question a reader needs and the text can answer — *which was this, the
database or the open web* — and sends the answer back for another lap when the
text does not say.

**A URL, not a source name.** `Billboard reported 70 million` is exactly the
shape `agent-chat`'s prompt calls "the single worst thing you can do here": a
source named from memory reads identically to a source read. An `http(s)://`
address is checkable by whoever reads the answer, which a publication's name is
not.

**Two deliberate holes, so nobody rediscovers them as bugs.** A hallucinated URL
passes — the text is all this seam sees, and whether the page was fetched is a
question about the run's evidence, which `fn(text) -> str` has no access to by
design. And one URL anywhere in the answer attributes every figure in it; per-
figure attribution would need to know which sentence each number belongs to, and
a gate that guesses that would refuse honest answers, which is how a gate
acquires a workaround.

The candidate rule — what counts as a quantity rather than a name, a list marker
or a share — is imported from `openstategraph.grounded_numbers` rather than
written again here. It is core's rule, it is already argued there, and a second
copy of it would drift.
"""

from __future__ import annotations

import re

from openstategraph.grounded_numbers import quantities_in

#: An address a reader can open. Scheme-anchored on purpose: a bare `nytimes.com`
#: is a source *name* spelled with a dot, and this whole function is about the
#: difference between naming a source and citing a page.
_URL = re.compile(r"https?://\S+")


def web_answer_cites_its_source(text: str) -> str:
    """`""` to publish, a sentence to send back — `guard.check`'s contract.

    The non-empty return is both the `revise` reason recorded on the node and
    the feedback text that reaches `agent-web`, so it is written for a model to
    act on rather than for a customer to read.
    """
    answer = text or ""
    unattributed: list[str] = []
    seen: set[str] = set()
    for literal, _value, _end in quantities_in(answer):
        if literal in seen:
            continue
        seen.add(literal)
        unattributed.append(literal)
    if not unattributed or _URL.search(answer):
        return ""
    return (
        "These figures are stated with no page behind them: "
        + ", ".join(unattributed)
        + ". You hold no data of your own, so a reader cannot tell them from figures "
        "this workflow's database returned. Use web_fetch on the page you took them "
        "from and quote its URL in the answer, or say plainly that you could not "
        "verify them and drop them."
    )
