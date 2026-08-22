"""The situational text a node's prompt is told about its place in the graph.

*Context* in `CLAUDE.md`'s prompt-composition sense: the generated middle
section a `SystemPrompt` places above the developer's rules and below the
locked preamble — the branch list a classifier can route to, the tools this
node already holds, the ones that could be added, what a rejection actually
said. It is generated, never editable, and it is the part that has to be true
about *this* compile.

These are pure functions of a document and a plan: they resolve no model, bind
no tool and touch no `NodeRuntime` state, which is why they live beside it
rather than inside it. `node_runtime.py` re-exports every name here, so the
seam is invisible to importers.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.workflow_compiler import CompiledPlan, ROUTER_TYPE
from openstategraph.developer_channel import FENCE_CLOSE, FENCE_OPEN


def _text(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _branch_entries(raw: Any) -> list[Any]:
    """The router's branch table, in either of its two saved forms.

    v1 documents store a newline-separated string of names; v2 (ticket 20)
    stores ``[{id, name}]`` so edges survive renames. Anything unusable
    collapses to a single ``"default"`` branch rather than raising — a router
    is the entry point, and refusing to compile is a total outage where a
    misroute is recoverable. `Branch.of` handles per-entry normalisation.
    """
    if isinstance(raw, str):
        names = [line.strip() for line in raw.split("\n") if line.strip()]
        return names or ["default"]
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, (str, dict))]
        return entries or ["default"]
    return ["default"]




def nested_record(node_id: str, child_outputs: Any) -> dict[str, Any]:
    """A mounted child's per-node outputs, keyed the way the parent sees them.

    `every-workflow-green` 16. The two run doors disagreed about the same run:
    the streaming one rebuilds this map from the frame stream, and the blocking
    one had nothing to rebuild it from, because a mount returned only the
    child's answer. So `silent_node_warnings` and `node_failure_warnings` ran
    over the inside of a mount on one door and over nothing on the other, and
    `/api/runs` is the door an adopter embeds.

    The prefix is `"<mount node id>/<child node id>"` — the same string
    `streaming.py` mints from the frame path. Getting that wrong would replace
    one disagreement with a subtler one.

    **The empty string is kept, deliberately.** It is exactly what
    `silent_node_warnings` looks for; dropping falsy values would delete the
    defect this exists to report.

    Recording this does not breach subagent isolation, which is a rule about
    what the child *receives* — `_subgraph` states it as "receives a task and
    reports a result". What the parent writes down about that is the parent's
    business.
    """
    if not isinstance(child_outputs, dict):
        return {}
    return {f"{node_id}/{key}": value for key, value in child_outputs.items()}


def advisor_context(node_id: str, catalog: str) -> str:
    """The editor-only "you may propose a fix" context block.

    *Context*, not rules and not a contract change: it is generated
    situational detail (this agent's own id, the tools this runtime could
    bind), so `SystemPrompt` places it above the developer's rules and the
    locked OUTPUT CONTRACT still renders last. That ordering is what lets the
    fence coexist with the contract instead of competing with it.

    `attachTo` is pre-filled with the agent's own node id rather than left to
    the model, because a hallucinated id is the one failure the editor cannot
    recover from: it would either wire the tool to the wrong agent or reject a
    genuinely correct suggestion.

    **The sentence before the block is required, and says so** (ticket 22).
    *"Say so briefly, then emit exactly one fenced block"* read as a single
    instruction with an optional first half: models sometimes emitted the block
    alone, and since the fence is split out of the answer for every audience,
    the reply a client rendered was the empty string. Asking for the shape of a
    reply is what a prompt is for, so the requirement belongs here —
    `developer_channel.NO_PROSE` is the guarantee, and this is what keeps it
    from ever being needed.

    **And the sentence is constrained, because nothing else constrains it**
    (`the-agent-asks-for-what-it-cannot-get` 04). The block is validated
    against a catalogue of node types that exist; the sentence is prose, so a
    model asked to explain what it cannot do offered to build it, and there is
    nothing on the other side of a developer's "yes" — no tool here writes a
    file. The prohibition is stated here rather than matched afterwards: a
    matcher for an offer-to-build in ordinary prose is exactly the shape this
    repository has watched rot, and its false-positive set is every sentence
    containing "I can".
    """
    if not catalog:
        return ""
    return (
        "You are running inside the workflow editor. If you cannot properly "
        "answer because this workflow lacks a capability, first tell the user "
        "in plain words what you cannot do and why — always that sentence, "
        "never the block alone — and then emit exactly one fenced block:\n"
        f"{FENCE_OPEN}\n"
        '{"nodeType": "<one from the catalogue below>", '
        f'"attachTo": "{node_id}", '
        '"port": "tools", "label": "<short human label>", '
        '"reason": "<one sentence>"}\n'
        f"{FENCE_CLOSE}\n"
        "Only suggest when genuinely blocked — never when you can already "
        "answer, and never more than one block.\n"
        # Declining has to be sayable, or the model picks the nearest entry.
        # Observed: asked to post to Slack, it proposed `tool.email-send` and
        # wrote "No Slack-send capability is available" in its own reason
        # (`every-workflow-green` 29). A catalogue with no way out is a leading
        # question, and a developer who accepts the answer wires an email tool
        # to an agent that was asked to post to Slack.
        # Both halves are load-bearing and were measured, not guessed. Without
        # the first, a Slack request drew `tool.email-send` — the nearest entry
        # — with "no Slack-send capability is available" in its own reason.
        # With the first alone, the model declined 3 runs in 5 on a gap
        # `tool.web-search` covers exactly. So declining is narrowed to "no
        # entry could help *at all*", and preferring an entry is stated as the
        # default rather than left to inference (`every-workflow-green` 29).
        # Required, not optional. Told that "none" was available, the model
        # simply wrote the sentence and skipped the block — so a gap nothing in
        # the library covers produced no signal at all, and the developer was
        # left at a dead end with no door (`every-workflow-green` 34). Unlike
        # ticket 33's case, nothing was called, so nothing was recorded: the
        # model is the only witness and it has to testify.
        "Whenever you are blocked for want of a capability you must always "
        "emit the block — never the sentence alone.\n"
        "Choose an entry from the catalogue whenever one would help, even "
        "partly — that is the usual case. Only if no entry could help at "
        'all, use "none" as the nodeType and say in your sentence what kind of '
        "capability is missing. Never propose an entry that cannot do the job "
        "because it is the closest one: a wrong tool costs a node, an edge and "
        "a re-run to discover.\n"
        # The third clause, and it closes a loop rather than tightening a rule
        # (`the-agent-asks-for-what-it-cannot-get` 01). A bound tool returning
        # an error is not a missing capability — errors are data precisely so
        # you can read them and retry — but nothing said so, so an agent whose
        # Email Send answered "No recipient configured" reported that the
        # workflow "doesn't have an email-sending capability" and emitted the
        # same fence again. Three times, in the transcript that found this.
        "A tool that ran and returned an error is NOT a missing capability: "
        "you have it, and something about it needs fixing. Say what the error "
        "was and what would fix it — never suggest adding a tool you were "
        "already given.\n"
        # The opposite case, and the clause above used to swallow it
        # (`every-workflow-green` 30). Asked for a live price, the agent called
        # `web_search` — a name it invented — and the runtime answered "web_search
        # is not a valid tool, try one of [...]". That reads as "a tool failed",
        # so the sentence above fired and no card was offered, on the one surface
        # the card exists for. The premise of that sentence — *you have it* — is
        # false here, and reaching for a name you do not have is the clearest
        # signal there is that something is missing.
        "But an error saying a name is not a valid tool IS a missing "
        "capability: you reached for something you do not have. Suggest one "
        "then — but only if you still cannot answer.\n"
        # The strongest sentence here, and it is countering an observed
        # failure rather than tightening a rule. Twice, on two different
        # questions, the trace was: search failed, an invented name failed,
        # search **succeeded** — and the answer was still "I don't have the
        # ability to look that up" (`every-workflow-green` 30). The success was
        # the *last* event, so this is not a later failure erasing an earlier
        # one; the agent did not treat a returned result as knowledge at all.
        # Everything else in this block is about what is missing, which primes
        # exactly that reading, so the counterweight has to be explicit.
        "Anything a tool returned in this turn is something you now know: use "
        "it and answer. Never say you cannot look something up after a tool "
        "has already returned results — an earlier failed call, or a name that "
        "did not exist, does not undo a result you were given.\n"
        # The sentence channel, which nothing validated
        # (`the-agent-asks-for-what-it-cannot-get` 04, sharpened by the owner
        # from their own transcript). The fence above is constrained to node
        # types that exist; the plain-words sentence this block *requires* was
        # constrained by nothing, and a model told to explain what it cannot do
        # offers to fix it — that is what a helpful assistant does. A developer
        # answers "yes" and there is nothing on the other side of yes: no tool
        # here writes a file, and an agent has no capability to create a
        # capability. `CLAUDE.md`'s law — do not promise which is not possible
        # — was being broken by an instruction we wrote. `branch_context`'s
        # "never offer a capability no branch above provides" is the precedent:
        # prose the parser cannot police is constrained where it is invited.
        "You cannot create a capability, write code, or change this workflow: "
        "the block above is a suggestion, and a developer applies it. So "
        "never offer to build, write, add or wire anything yourself, and "
        "never ask whether you should — there is no next turn in which you "
        "could do it, so an offer taken up is a dead end. Say what is missing "
        "and stop.\n"
        "Tools that could be added to you:\n"
        f"{catalog}"
    )


def held_tools_context(tools: list[Any]) -> str:
    """What this node **already holds** — the counterweight to `advisor_context`.

    `advisor_context` tells an agent what could be *added* to it, and nothing
    told it what it has. That asymmetry was invisible while every agent's
    authored prose happened to be current, and it stopped being invisible the
    moment the capability door started wiring tools onto agents after the fact
    (production-ready 88): `chinook-assistant`'s front desk opens *"You hold no
    tools and no database access"*, a user accepted an Email Send onto it, and
    the agent answered *"this workflow doesn't include an email-sending
    capability"* — two supersteps, no tool call. The binding was correct the
    whole time; `plan.tool_bindings` and `openstategraph validate` both agreed.
    The model believed the sentence over the tool schema, which is the only
    reasonable thing to do when one of them is an explicit instruction.

    **Context, not rules**, exactly like `branch_context`: it is generated from
    what the compiler bound, never authored, so `SystemPrompt` places it above
    the developer's rules and the locked output contract still renders last.

    Which forces the precedence sentence to be explicit. Context renders
    *before* rules and the stale claim lives *in* the rules, so "later
    instructions win ties" runs the wrong way here — a list saying "you have
    `send_email`" followed by prose saying "you hold no tools" is a
    contradiction the model resolves by recency, and recency favours the lie.
    The developer's text is not edited: it is theirs, and a platform that
    rewrites a prompt field is a platform nobody can predict. It is overruled,
    on the one point the compiler knows better than the author.
    """
    named = [t for t in tools if getattr(t, "name", "")]
    if not named:
        return ""
    lines = "\n".join(
        f"- `{t.name}`" + (f" — {str(getattr(t, 'description', '') or '').strip()}" if getattr(t, "description", "") else "")
        for t in named
    )
    return (
        "Tools you hold right now — the exact set you can call:\n"
        f"{lines}\n"
        "This list is authoritative. It is generated from what was bound to "
        "you at the moment you were built, so where anything in your rules says or "
        "implies you hold no tools — or no tool of some kind — that text is "
        "out of date and this list wins. A tool may well have been added to "
        "you after those rules were written.\n"
        "So: never tell the user a capability is missing when one of these "
        "provides it. Call it instead. If one of them fails, say what the "
        "error was — a tool that ran and failed is not a tool you lack."
    )


def branch_context(node_id: str, plan: CompiledPlan, nodes: dict[str, Any]) -> str:
    """What the classifier feeding this agent can actually route to (ticket 11).

    The **chainlogic** rule, made mechanical: a conversational branch that
    tells the user "just ask me for X" is writing the *next* question, and the
    router has to be able to place that question on a branch that can answer
    it. Found live on `page-analytics`: the conversation agent — whose prompt
    was hand-written and could see nothing but itself — offered "charts",
    "dashboards" and "copy/paste reports" that no branch produces, and phrased
    a data question ("Show trends: monthly sales, media-type mix, top genres")
    in wording the router then classified as `full_report`, the one branch
    that ends in a human approval gate and an email rather than an answer. The
    user got no answer at all.

    Its own prompt could never have prevented that, because the branch table
    is not knowledge the prompt author holds — it is a fact about the *graph*,
    and it changes whenever anyone renames a branch or draws an edge. So it is
    **generated context**, resolved from the compiled plan at build time and
    handed to `SystemPrompt` exactly like `advisor_context` and the skills
    text: above the developer's rules, below nothing the developer edits, with
    the locked output contract still rendering last.

    The router's `rules` text rides verbatim rather than being parsed into
    per-branch sentences. Splitting one free-text field into a table would be
    duplicating *knowledge* — the classifier reads that same string, and two
    renderings of it are two things that can disagree. Verbatim cannot.

    Returns "" for any agent no classifier routes to, which is most of them.
    """
    for router_id, destinations in plan.conditional.items():
        if (nodes.get(router_id) or {}).get("type") != ROUTER_TYPE:
            continue
        if node_id not in destinations.values():
            continue
        data = (nodes.get(router_id) or {}).get("data") or {}
        by_id = {}
        for entry in _branch_entries(data.get("branches")):
            if isinstance(entry, dict):
                by_id[str(entry.get("id") or entry.get("name") or "")] = str(
                    entry.get("name") or entry.get("id") or ""
                )
            else:
                by_id[str(entry)] = str(entry)
        names = [by_id.get(key, key) for key in destinations]
        mine = sorted(
            {by_id.get(key, key) for key, dst in destinations.items() if dst == node_id}
        )
        if not names:
            continue
        lines = [
            "This workflow routes every incoming question to exactly ONE of "
            "these branches, by classifying the question's wording:",
            "  " + ", ".join(names),
        ]
        if mine:
            lines.append(f"You are the '{', '.join(mine)}' branch.")
        rules = _text(data, "rules")
        if rules:
            lines.append("How the classifier decides:\n" + rules)
        lines.append(
            "So: never offer a capability no branch above provides, and when "
            "you suggest what to ask next, phrase each suggestion the way the "
            "branch that can answer it is described above — a suggestion the "
            "classifier sends to the wrong branch is a suggestion the user "
            "cannot get answered."
        )
        # ...and the other half of that instruction, which was missing (ticket
        # 23). The branch names are routing vocabulary, and an agent handed a
        # list it is told to phrase things by will read the list aloud: live
        # refusals offered to help with "off-topic questions" and to "let you
        # know the types of requests I can't handle" — the branch table recited
        # to the person asking. That is the very failure this block exists to
        # prevent, in the opposite direction, so the correction belongs in the
        # block that hands the names over rather than in each workflow's
        # prompt, where it would be one sentence copied into every document
        # that can disagree with the next.
        lines.append(
            "These branch names are this workflow's internal routing "
            "vocabulary: never name a branch to the user, and never read the "
            "list back as a menu. Describe what you can help with in the "
            "user's own words, as questions they could ask. When you cannot "
            "help, say what is missing — the fact, the data or the capability "
            "this workflow does not have — never merely that the request is "
            "one you do not handle."
        )
        return "\n".join(lines)
    return ""



def rejection_feedback(note: str) -> str:
    """What travels down the `rejected` edge — never an empty string.

    A reviewer may reject without typing anything, and that must stay allowed:
    blocking a rejection behind a mandatory text field is how a bad draft gets
    approved instead. But the empty string is not a neutral default. Handed to
    the agent that writes the held record, it is an invitation — on
    `support-triage` it produced *"the draft was refused because the reviewer
    stated that identity verification ... is required"*, a position the
    reviewer never took, on an account-deletion ticket
    (`every-workflow-green` 11).

    So silence is reported as silence. The sentence deliberately says only that
    no reason was given: it names no cause and puts no words in the reviewer's
    mouth, because a downstream model repeating it verbatim must still be
    telling the truth.
    """
    return note.strip() or "The reviewer rejected this draft and gave no reason."


def revision_request(rejected: str, feedback: str) -> str:
    """What an agent is told when its answer came back over a `revise` edge.

    **The rejected answer travels with the complaint, or the lap is a repeat**
    (`production-ready` 73). `_agent` writes no `messages`, so the conversation
    state a revise lap starts from holds the user's question and nothing else;
    appending only the reviewer's sentence asks a model to correct a text it
    has never been shown. Printed off a live `chinook-assistant` run, the whole
    payload of attempt three was two human turns:

        human | 'top artists by revenue'
        human | 'Your previous answer was rejected: The answer is empty.'

    From that standing start the model re-runs the same investigation and
    stops the same way, so a three-attempt budget buys three identical first
    attempts and the grader's objection never moves.

    The rejected text is not a new channel: it is `outputs[<the grader>]`,
    already delivered over the edge that caused this lap.

    **Silence stays silence.** When the previous attempt genuinely produced
    nothing there is nothing to show, and the sentence is exactly what it was
    — inventing a placeholder here would hand the model a fiction to revise.
    """
    asked = f"Your previous answer was rejected: {feedback}"
    if not rejected.strip():
        return asked
    return (
        f"{asked}\n\n"
        "This is the answer that was rejected, in full. Revise it — do not "
        "start again from nothing:\n\n"
        f"{rejected}"
    )
