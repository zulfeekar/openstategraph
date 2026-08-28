"""Every way a compiled graph quietly lost a capability, and what to say.

Seven lists used to live on `NodeRuntime` — 7 of its 23 public attributes —
and `api/registries.runtime_warnings()` reached across into all seven to turn
them into sentences, three of them through `getattr(runtime, name, [])`. That
defensive access was the tell: the contract between the two sides was never
firm enough for either to depend on it (reviews-2026-08-14 ticket 07).

The data and its only reader live together now, and a finding is a **value**
rather than a field. Adding a kind is a table entry, not another attribute on
the runtime plus another loop in `runtime_warnings` — which is the open/closed
rule applied to the one part of the compiler that grows every time a node type
learns a new way to be incomplete.

**The rule these sentences serve** is `errors.py`'s: degrade loud, never
silent. An agent that quietly loses its tools does not fail — it answers from
parametric knowledge, confidently and wrongly. Observed exactly that: a Reddit
tool node wired to an agent produced an authoritative-sounding answer about
global music revenue having queried nothing. Every sentence below exists
because some run looked like it worked and had not.
"""

from __future__ import annotations

import re
from enum import Enum


class Finding(str, Enum):
    """A way a compiled graph came out less capable than it was drawn.

    `str`-valued for the reason `Reducer` is: a member survives a JSON round
    trip with no encoder, so a finding can cross the run/stream seam as data.

    **Declaration order is report order.** It reproduces the order the seven
    loops in `runtime_warnings` happened to be written in, which is now a
    property that can be read rather than one spread across a function.
    """

    #: A tool node on the canvas with no implementation behind it.
    UNRESOLVED_TOOL = "unresolved_tool"
    #: A function node wired on the canvas with no discovered callable.
    UNRESOLVED_FUNCTION = "unresolved_function"
    #: A Team mount whose child graph cannot enforce the outcome on its card.
    #:
    #: `TeamNode`'s *Expected outcome* never reaches the compiler, so a user
    #: writes a constraint, reasonably believes it binds the run, and gets no
    #: signal that it does not. Reported rather than refused: a Team without a
    #: loop is a legal graph that answers questions. What it cannot do is keep
    #: the promise printed on its card (production-ready ticket 03).
    #:
    #: And a **report**, not a failure — `REPORT_ONLY` below carries the
    #: argument and `workflow-gallery` 61 the run it was decided on. In short:
    #: its condition is the same "no grader routes revise" that
    #: `UNWIRED_REVISE` reports one level down, the run answers with every
    #: drawn node producing its output, and the missing thing is a check on
    #: prose rather than a lost capability.
    UNENFORCED_OUTCOME = "unenforced_outcome"
    #: A grader whose `revise` port is wired to nothing (`workflow-gallery` 31).
    #:
    #: The compiler's conditional edge is given only the destinations that
    #: were drawn, and `_router_for` falls back to the first of them when the
    #: recorded decision names none — which is right for a *missing* decision
    #: and silent for a decision that exists and was understood. So a grader
    #: that judged the answer inadequate sent it to the output anyway.
    #:
    #: Reported rather than refused, and deliberately not on `plan.warnings`:
    #: a grader used as a recorder is a legal graph that answers questions,
    #: `support-triage` ships exactly that shape on purpose, and
    #: `plan.warnings` is the channel `validate` turns into PROBLEMS FOUND.
    #:
    #: For the same reason it is a **report**, not a failure — see
    #: `REPORT_ONLY` below. The run does everything it was drawn to do; this
    #: sentence is advice about the drawing, and it is the identical
    #: observation `run_health` publishes as `unrouted` (`workflow-gallery` 50).
    UNWIRED_REVISE = "unwired_revise"
    #: A node type this build has no factory for, as `(type, node id)`.
    #:
    #: The loud half of a rule that was only half kept. `errors.py` records the
    #: policy — an unknown node type is *reported*, not raised, so a document
    #: containing one still answers what it can — and `_passthrough`
    #: implemented the degrade while reporting nothing. Its docstring claimed
    #: "the gap is visible as an unchanged value", which is exactly what hides
    #: it: the skipped node forwarded its input, so the run answered the user's
    #: own question back and looked like it worked. Found through the typo
    #: `agent.react` for `agent.llm`.
    UNKNOWN_NODE_TYPE = "unknown_node_type"
    #: A subgraph node whose workflow could not be loaded.
    UNRESOLVED_SUBGRAPH = "unresolved_subgraph"
    #: A per-mount override problem — unknown child node id, wrong shape.
    OVERRIDE_PROBLEM = "override_problem"
    #: A per-mount override that DID apply — the report `OVERRIDE_PROBLEM`
    #: has no counterpart for (`launch-readiness` 40). An override reaching
    #: the wrong node of a same-named sibling mount, or reaching nothing,
    #: looked identical to one working correctly: `validate`/`run` were
    #: silent either way, and the only confirmation available was inferring
    #: scope from the model's own answer — which only works when the
    #: override happens to be observable. Recorded once per applied field, at
    #: the mount that applied it, so `data.overrides` on two sibling mounts
    #: of the same package (`same-package-twice`) produce two distinct
    #: sentences rather than one collapsed by package identity the way
    #: `CompileDiagnostics.absorb` collapses `OVERRIDE_PROBLEM` and friends.
    #: A **report**: the override still ran, so this is confirmation, not a
    #: reason to fail a build.
    OVERRIDE_APPLIED = "override_applied"
    #: A capability that failed to *load* — a tool module that would not
    #: import, an abstract class discovery could not instantiate, a plugin
    #: distribution that half-installed.
    #:
    #: Distinct from `UNRESOLVED_TOOL`, which is a node on the canvas finding
    #: no implementation; this is an implementation that never became one.
    #: They share a channel deliberately: from a developer's seat "the tool I
    #: wrote is not here" is one question, and answering half of it in a server
    #: log they never open is how the original bug survived.
    CAPABILITY_FAILED = "capability_failed"
    #: An Output node with no guardrail anywhere upstream of it, **in a
    #: document that has one somewhere else** (guardrails ticket 02).
    #:
    #: The condition is deliberately the *inconsistent* case, not the absent
    #: one. Ticket 02 weighed making the outbound guard something Output just
    #: does — impossible to forget, and invisible, and a second job for a node
    #: that has one. It chose the node, on the condition that its absence be
    #: loud; this is that condition, scoped by the rule stated at the top of
    #: this module. Warning every document that has no guardrail would fire on
    #: every shipped example and on every workflow anyone has drawn,
    #: and "a warning a user cannot act on is a warning they learn to skip".
    #:
    #: What this catches is the realistic mistake instead: somebody added a
    #: second Output later, wired it straight off the agent, and the answer
    #: reaching the user down *that* path never meets the policy the document
    #: says it has. The asymmetry ticket 02 argued from is why it is worth a
    #: sentence at all — a missing inbound guard is a missed block, a missing
    #: outbound one is a disclosure.
    UNGUARDED_EXIT = "unguarded_exit"
    #: A **stateless** mount whose child contains an approval gate, as
    #: `(mount node id, package slug)` — `organisms-first-class` 65.
    #:
    #: `625d695` shipped the mode with LangGraph's sentence attached, that a
    #: stateless subgraph cannot pause or resume. At this boundary that is
    #: false and was measured to be: a mount is a **closure**, so the child's
    #: `interrupt()` travels up and is held by the *parent's* checkpointer. It
    #: pauses, and it resumes, and it answers.
    #:
    #: What it does not do is remember. Resuming re-enters the mount node in
    #: every mode, but only this one has no child checkpoint to pick up from,
    #: so the child runs again **from its first step** — counted on the
    #: child's own pre-gate node: once before the pause, twice after the
    #: approval, at one level and at two, while both other modes run it once.
    #: A step that called a tool, sent a message or wrote to a store does it a
    #: second time, on the approval path, silently. That is why this is worth
    #: a sentence at all: a gate exists because something consequential is
    #: about to happen, and here something consequential already did.
    #:
    #: **Reported, not refused**, and on `REPORT_ONLY` below. The document
    #: runs, pauses, resumes and answers, so `validate`'s one question — is
    #: this ready to run here — is honestly yes, and refusing it would fail a
    #: working graph in somebody's CI over advice. The advice is the whole
    #: value: it arrives before the run, which is when the mode can still be
    #: changed.
    STATELESS_MOUNT_REDOES = "stateless_mount_redoes"
    #: A Guardrail row that cannot do what its card says — an unimplemented
    #: strategy, or a `detector` that is not a valid pattern (guardrails 05).
    #:
    #: Found at build time by `BaseGuardrail.problems()`. It used to be found
    #: only by running: `resolved()` is called from `screen()`, so a missing
    #: `)` surfaced as a bare `re.error` out of the middle of a run, with a
    #: person waiting. The node still refuses to pass text through when it
    #: happens — a guardrail that fails open is the one failure worse than
    #: noisy — but the developer is told at compile time, in a sentence.
    INVALID_GUARDRAIL_RULE = "invalid_guardrail_rule"
    #: An agent or worker whose **authored** rules deny holding any tools while
    #: the canvas has tools wired to it, as `(node id, the offending phrase)`.
    #:
    #: The half of production-ready 88 that survived its own fix. That ticket
    #: made the *run* right — `held_tools_context` hands the node an
    #: authoritative list that overrules the stale sentence — which is exactly
    #: why nobody will ever be prompted to look at the sentence again. The
    #: document stays wrong, silently, in a field the developer owns.
    #:
    #: Reported and never rewritten: 88 decided the prompt field is theirs, and
    #: a platform that edits a prompt is one nobody can predict. Reported on
    #: this channel rather than `plan.warnings` for `UNWIRED_REVISE`'s reason,
    #: and deliberately **not** on `validate`'s exit code: that command's one
    #: question is "is this ready to run here", and the answer is yes — the
    #: tool is bound, and it is called.
    STALE_TOOL_DENIAL = "stale_tool_denial"
    #: A mount whose child requires a run-context key the parent cannot ever
    #: name, as `(package slug, key)` — `organisms-first-class` 79.
    #:
    #: The compile-time statement of 76's rule. A key crosses a mount only when
    #: **both** documents declare it, so a child requiring a key with no
    #: default that the parent does not declare is a mount that raises before
    #: `invoke` on every run, for every input, with no `--context` value able
    #: to change it. Both documents are on disk while the graph is built, so
    #: the fact was knowable a whole run early and was said only as the run
    #: died.
    #:
    #: **A `Finding` rather than `plan.warnings`**, on `6a812bf`'s line:
    #: `plan.warnings` names a malformed document and neither document here is
    #: malformed — each is valid, and each runs on its own. What is lost is the
    #: mount, which produces nothing, which is `UNRESOLVED_SUBGRAPH`'s class one
    #: reason over. And that channel could not carry it in any case:
    #: `plan.warnings` is `ValidateWorkflowTool`'s in-memory plan, which has no
    #: root to load a sibling package from and has never seen the child.
    #:
    #: **A failure, not a report**, by `afc57f6`'s test — can the composition
    #: answer? It cannot: the run ends at the mount with no output. Keyed by
    #: slug and not by node id, so a package mounted three times says it once
    #: (`f4f61bd`'s rule, reached the other way): a parent's declaration is
    #: document-wide, so three mounts of one package share one gap for one
    #: reason. `organisms-first-class` 78 is the thing that could make that
    #: untrue — a per-mount supply differs per instance — and
    #: `unsuppliable_context_keys` takes the parameter where that lands.
    UNSUPPLIABLE_CONTEXT = "unsuppliable_context"
    #: A node's own model selection resolved to something other than what it
    #: named, as `(node id, the string it could not resolve, the model it
    #: used instead)` — `launch-readiness` 45/62, the same defect hit three
    #: times live: a colon typed by hand, an empty per-node field on a
    #: grader, and an `UnconfiguredProvider` from a missing provider extra.
    #:
    #: `CAPABILITY_FAILED` covers the first of those three now that both
    #: separators parse — an unparseable selection is a document defect,
    #: knowable with no credential, and stays a failure. This member is for
    #: the other two: `build_chat_model` refusing a syntactically valid
    #: selection because *this installation* lacks a key or a provider
    #: package. That is not a claim the document is wrong — the identical
    #: selection succeeds the moment the key or the extra is present, which
    #: is exactly `validate`'s own "on a machine with no credential" promise
    #: (`cmd_validate`'s docstring) for the *shared* default extended to a
    #: per-node one. Blocking the exit code on a missing credential would
    #: fail every shipped package naming a real provider in any environment
    #: — CI included — that does not carry that provider's paid key, which
    #: is not what this report is for.
    #:
    #: A **report**, not a failure, for that reason — see `REPORT_ONLY`
    #: below. The run still answers; it answers on a model the author did not
    #: choose, which is worth a sentence at authoring time and at run time,
    #: never worth failing a build over.
    MODEL_SELECTION_DEGRADED = "model_selection_degraded"
    #: A node holding a capability that acts outside the run, in a graph that
    #: can run that node more than once, as `(node id, capability types, the
    #: mechanism)` — `launch-readiness` 121.
    #:
    #: Two mechanisms, and the subject carries **both** when both apply
    #: because they have different fixes. `set_node_defaults` gives every node
    #: `RetryPolicy(max_attempts=3)`, and LangGraph re-runs the *whole node
    #: body* on a retry; a drawn cycle re-enters the node from a grader's
    #: `revise`. Neither carries any memory of what already happened, so a
    #: mail sent on attempt one is sent again on attempt two, and a revision
    #: after the send is a second mail. `workflows/support-triage` was both at
    #: once until `launch-readiness` 122 redrew it: three `tool.email-send` on
    #: `a-account`, inside `router1 -> a-account -> grader1 -> router1`. The
    #: shape is kept here as the worked case; no shipped package draws it now,
    #: and `test_a_send_that_can_happen_twice.py` synthesises it rather than
    #: reading one.
    #:
    #: **Narrow on purpose.** A read-only capability inside a cycle is the
    #: evaluator-optimizer pattern this product exists to draw, and a warning
    #: on it is a warning nobody reads. What separates the two is
    #: `BaseTool.side_effecting`, whose default is `True` so that an
    #: undeclared tool lands on the safe side.
    #:
    #: A **report**, not a failure — see `REPORT_ONLY`.
    REPEATED_SIDE_EFFECT = "repeated_side_effect"
    #: An approval gate with a capability that acts outside the run
    #: **upstream** of it, as `(gate node id, acting node id, capability
    #: types)` — the second half of `launch-readiness` 121.
    #:
    #: `support-triage`'s `gate1` reads *"Approve to send it"* and sat below
    #: the only send capability in the document until `launch-readiness` 122
    #: moved the capability out of it entirely. The mail is already gone when
    #: the person is asked, so what they authorise is a status change — two
    #: states with one indistinguishable output, at an operator's expense.
    #:
    #: It is LangGraph's own documented hazard read at graph scale rather than
    #: node scale: *"Place side effects after `interrupt` calls"*, *"Separate
    #: side effects into separate nodes when possible"* (Interrupts; installed
    #: `langgraph 1.2.10`). The library says it about one node's body; here
    #: the body is a whole upstream region of the drawing, which is why the
    #: compiler is the only thing that can see it.
    #:
    #: A **report**, not a failure — see `REPORT_ONLY`.
    APPROVAL_COMES_TOO_LATE = "approval_comes_too_late"
    #: A node that can hand the model a fact the run cannot re-resolve, with
    #: no gate between it and an Output, as `(output id, producing node id,
    #: capability types)` — `launch-readiness` 151.
    #:
    #: The rule it makes checkable: **a model may supply a word, never a
    #: number.** A guess about language is safe because the store re-resolves
    #: it; a guess about a quantity is unfalsifiable at the moment it is made.
    #: Measured here: three identical runs of one question gave a correct
    #: answer, a correct refusal, and an invented 81-port country set (126,
    #: 127). All three came from the same mechanism, and nothing downstream
    #: could tell them apart.
    #:
    #: **Narrow on both sides, which is the half that decides whether anybody
    #: reads the other half.** It fires only when a bound capability declares
    #: `open_world = True` — the tool that reaches past the run's own data —
    #: and it goes silent the moment a `guard.check` stands on the path. An
    #: agent bound to the store's own query tools is the ordinary case and is
    #: never reported.
    #:
    #: It reports the **absence** of a gate, never the adequacy of one. 133 is
    #: the record of why: a check that accepted `SELECT DISTINCT k, a, b` as a
    #: dedup reported success on a wrong query, which is worse than no check
    #: because it turned "unverified" into "verified". Judging a placed gate's
    #: contents from the compiler would be the same move.
    #:
    #: A **report**, not a failure — see `REPORT_ONLY`.
    UNDECLARED_FALLBACK = "undeclared_fallback"


#: What each finding says, and how many subjects it takes.
#:
#: Full sentences naming the consequence, not the condition — "the agent ran
#: without it, so its answer may not be grounded" rather than "unresolved
#: tool". A warning a user cannot act on is a warning they learn to skip.
#:
#: `CAPABILITY_FAILED` carries no prefix because discovery findings already
#: name the class, the file and the fix: a discovery finding is not a
#: sub-species of an unresolved binding, it is the other half of the same
#: question.
_SENTENCES: dict[Finding, str] = {
    Finding.UNRESOLVED_TOOL: (
        'No implementation for tool "{0}" — the agent ran without it, '
        "so its answer may not be grounded in that data source."
    ),
    Finding.UNRESOLVED_FUNCTION: (
        'No function found for "{0}" — the step passed its input through unchanged.'
    ),
    Finding.UNENFORCED_OUTCOME: (
        'Team "{0}" mounts "{1}", whose graph has no grader routing revise — so its '
        "Expected outcome is documentation and nothing in the run checks it. Add a "
        "grader to that workflow and wire revise back, or read the outcome as a note."
    ),
    Finding.UNWIRED_REVISE: (
        'Grader "{0}" has no revise edge — a verdict of revise routes to its pass '
        "branch instead, so an answer this grader rejected ships as though it had "
        "been approved. Wire revise to the node that wrote the answer, or — behind "
        "a fan-out, where no single branch agent is the one to correct — to the "
        "router that dispatched to it; the router replays its own branch decision "
        "(workflow-gallery 48). Read this grader as a recorder only if nothing "
        "upstream can take feedback."
    ),
    Finding.UNKNOWN_NODE_TYPE: (
        'Node "{1}" has type "{0}", which this build does not implement — the step '
        "passed its input through unchanged, so any answer downstream of it skipped "
        "that work."
    ),
    # "Subgraph" was a LangGraph name in a sentence a user reads, which
    # CLAUDE.md forbids — and it was not even internally true: this compiler
    # emits no LangGraph subgraph (production-ready 37). The settled words are
    # *mount* and *workflow node*, and the enum member keeps its old name
    # because it is not a surface (ticket 53).
    Finding.UNRESOLVED_SUBGRAPH: (
        'The workflow node mounting "{0}" could not load that package — '
        "the step produced nothing."
    ),
    Finding.OVERRIDE_PROBLEM: "Mount override — {0}",
    Finding.OVERRIDE_APPLIED: "Mount override applied — {0}",
    Finding.CAPABILITY_FAILED: "{0}",
    Finding.UNGUARDED_EXIT: (
        'Output "{0}" has no guardrail upstream of it, but this workflow has one on '
        "another path — so an answer that leaves this way is never checked against the "
        "policy the rest of the document keeps. Wire a Guardrail before it, or delete "
        "the one that suggests it should be there."
    ),
    Finding.STALE_TOOL_DENIAL: (
        'Agent "{0}" has tools wired to it, but its own rules still say "{1}" — the '
        "run overrules that with the generated list of what the node holds, so the "
        "answer is right and the sentence is stale. Update the line, or expect every "
        "reader of this document to believe it."
    ),
    Finding.STATELESS_MOUNT_REDOES: (
        'The workflow node "{0}" keeps no record of "{1}", and that workflow contains an '
        "approval step. It does pause and it can be answered — but because nothing was "
        "kept, answering it runs that workflow again from its first step, so every step "
        "before the approval happens a second time. Change what the child remembers, or "
        "move the approval out of that workflow."
    ),
    Finding.UNSUPPLIABLE_CONTEXT: (
        'The workflow node mounting "{0}" can never run: that workflow requires the run '
        'context key "{1}", and this document does not declare it — so no run of this '
        "document can supply a value, and the mount fails before it starts. Declare that "
        "key on this workflow, or give it a default in that one."
    ),
    Finding.INVALID_GUARDRAIL_RULE: (
        'Guardrail "{0}" has a row for "{1}" that {2} — that row protects nothing, '
        "and the node refuses everything rather than letting text past a policy it "
        "cannot apply. Fix the row or remove it."
    ),
    Finding.MODEL_SELECTION_DEGRADED: (
        'Node "{0}" selected model "{1}", which this installation could not '
        'resolve — it ran on "{2}" instead.'
    ),
    Finding.REPEATED_SIDE_EFFECT: (
        'Node "{0}" holds a capability that acts outside this run ({1}), and this graph '
        "can run that node more than once — {2}. Nothing records what it already did, so "
        "the action happens again in full. Set that node's Max retries to 1, keep it out "
        "of the loop, or make the action safe to repeat. If the capability only reads, "
        "declare side_effecting = False on its tool class and this stops being reported."
    ),
    Finding.APPROVAL_COMES_TOO_LATE: (
        'Approval step "{0}" sits downstream of "{1}", which holds a capability that acts '
        "outside this run ({2}) — so by the time a person is asked, the action has already "
        "happened, and approving it changes only what the run records. Move the approval "
        "above that step, or reword its message as a notice rather than a decision."
    ),
    Finding.UNDECLARED_FALLBACK: (
        'Output "{0}" can be reached from "{1}", which holds a capability that answers '
        "from outside this run's own data ({2}), and no check stands between them. A "
        "quantity that arrives that way looks exactly like one your data returned, and "
        "nothing downstream can tell them apart. Put a guard.check between that step and "
        "this Output, or unbind that capability from the step that writes the answer."
    ),
}


#: Findings that are a *report* about the document rather than a claim that a
#: capability was lost. They ride `warnings()` with everything else and are
#: kept off `failure_warnings()`, so no surface can turn one into an exit code.
#: Membership is a decision about meaning: everything else here describes work
#: the run did not do.
#:
#: `UNWIRED_REVISE` joined it in `workflow-gallery` 50, which is the
#: classification pass ticket 89 left with one member. The argument is not that
#: an unwired grader is harmless — it is that **the runtime already publishes
#: the identical observation as a report**. `run_health`'s `unrouted` says a
#: verdict of revise reached no edge; this finding says the edge was never
#: drawn. Ticket 49 put `unrouted` on the report side deliberately, so leaving
#: this one on the failure side made one observation a failure when the
#: compiler noticed it and a report when the run did — and on any run that
#: answered with nothing, the compile half alone exited 1 for a graph
#: `support-triage` ships on purpose.
#:
#: `STATELESS_MOUNT_REDOES` joined it in `organisms-first-class` 65 on the
#: narrowest reading of the same rule: the run does everything it was drawn to
#: do — it pauses, it resumes, it answers — and the sentence is about what
#: answering *costs*. A document that runs is not a document `validate` should
#: exit 1 on.
#:
#: `UNENFORCED_OUTCOME` joined it in `workflow-gallery` 61, which is the
#: ticket 50 filed against itself: 50 kept this one and `UNGUARDED_EXIT` on the
#: failure side on its *safe direction of error* rather than because either
#: argument was won, and `9729338` then turned that classification into an exit
#: code. 61 decided them apart, by building a document for each and running it.
#:
#: This one is `UNWIRED_REVISE` one level up, and not by analogy: the condition
#: is `_closes_a_loop_impl(child_document)` — *does any grader in the child
#: route revise* — which is the same observation the child-level finding
#: reports about itself. Leaving them classified differently made one fact a
#: failure when the parent noticed it and a report when the child did, which is
#: the asymmetry 50 was filed to remove. The run settles it: a parent mounting
#: a graderless child answers, and every node it draws produces its output —
#: nothing was skipped and no capability was lost. What is missing is a machine
#: check on a sentence a person wrote on a card. And it fires on a
#: *deliberate* act: an Expected outcome written as a note over a straight
#: pipeline is a reasonable thing to author, and it exited 1.
#:
#: **`UNGUARDED_EXIT` stays a failure, and 61 recorded why with a run rather
#: than with a direction of error.** One model, one answer, `guarded-lookup`
#: plus a second Output off the agent: the guarded door emits
#: `Contact them at [REDACTED_EMAIL] or [REDACTED_URL]` and the unguarded one
#: emits the address and the internal URL intact. The run did something the
#: document was drawn *not* to do — that is not an observation about how a
#: graph is drawn, it is a disclosure, and `guardrails` 02's asymmetry (a
#: missing inbound guard is a missed block, a missing outbound one is a
#: disclosure) is what it turns on. It is also reachable only from an
#: inconsistency the author had to draw twice — a policy, and then a path
#: around it — which is the opposite of the deliberate-authoring case above.
#: `REPEATED_SIDE_EFFECT` and `APPROVAL_COMES_TOO_LATE` joined it together in
#: `launch-readiness` 121, on a reason neither of the others needed: **their
#: condition is a conservative assumption, not an observation.**
#: `BaseTool.side_effecting` defaults to `True` so an undeclared tool lands on
#: the safe side, which means an adopter whose read-only tool predates the flag
#: gets both sentences about a graph that is entirely correct. A guess may be
#: loud; it may not exit 1. That is the whole bargain of conservative-by-default
#: — it earns the right to be noisy by never being fatal — and it is the same
#: line `8bda508` drew when it split `RunResult`.
#:
#: `APPROVAL_COMES_TOO_LATE` is the closer call of the two, because
#: `UNGUARDED_EXIT` next door *is* a failure and the shapes rhyme: both are
#: about a control the document draws and the run gets around. 61 settled that
#: one with a run in which the unguarded door disclosed an address — an
#: observed fact about a document whose author drew the policy **twice**, once
#: as a rule and once as a path around it. Here nobody drew anything twice, and
#: the fact is inferred from a default. Different evidence, different side.
#:
#: `UNDECLARED_FALLBACK` joined it in `launch-readiness` 151 on the first of
#: 121's two reasons and not the second: nothing about the graph it names is
#: *wrong*. Binding a web tool to the node that writes the answer is a
#: reasonable thing to draw, and the sentence is about what that arrangement
#: makes *possible* rather than about something the run did. A document that
#: runs, answers, and loses no capability is not one `validate` should exit 1
#: on — and the fix it asks for is a node the author may deliberately not want.
#:
REPORT_ONLY: frozenset[Finding] = frozenset(
    {
        Finding.UNENFORCED_OUTCOME,
        Finding.UNWIRED_REVISE,
        Finding.STALE_TOOL_DENIAL,
        Finding.STATELESS_MOUNT_REDOES,
        Finding.OVERRIDE_APPLIED,
        Finding.MODEL_SELECTION_DEGRADED,
        Finding.REPEATED_SIDE_EFFECT,
        Finding.APPROVAL_COMES_TOO_LATE,
        Finding.UNDECLARED_FALLBACK,
    }
)


#: How a finding absorbed from a mount is said. The child's own sentence,
#: unedited, behind the path of packages it came from — the child's words are
#: already full sentences naming the consequence, and rewriting them per depth
#: would be a second phrasing to keep in step with the first.
_MOUNTED = 'Inside mounted workflow "{path}": {sentence}'


class CompileDiagnostics:
    """What the compiler noticed and could not resolve.

    One reason to change: the ways a graph can come out incomplete. Recording
    is deduplicated here rather than at each call site — five of the seven
    buckets open-coded `if x not in bucket` and one of them did not.
    """

    def __init__(self) -> None:
        self._findings: dict[Finding, list[tuple[str, ...]]] = {}
        self._mounted: list[tuple[str, Finding, tuple[str, ...]]] = []

    @staticmethod
    def sentence_for(finding: Finding) -> str:
        """The template for a kind. Every member has one, and a test says so."""
        return _SENTENCES[finding]

    def record(self, finding: Finding, *subjects: str) -> None:
        """Note a finding, once. Recording the same subjects twice is a no-op."""
        expected = _SENTENCES[finding].count("{")
        if len(subjects) != expected:
            # Raised rather than formatted loosely: a template with an
            # unfilled slot ships "{1}" to a user, which is worse than the
            # missing information it stands for.
            raise ValueError(
                f"{finding.value} takes {expected} subject(s), got {len(subjects)}: {subjects!r}"
            )
        recorded = self._findings.setdefault(finding, [])
        if subjects not in recorded:
            recorded.append(subjects)

    def subjects(self, finding: Finding) -> list[tuple[str, ...]]:
        """What was recorded for one kind, in the order it was recorded."""
        return list(self._findings.get(finding, ()))

    def any(self, finding: Finding) -> bool:
        """Whether anything of this kind was recorded."""
        return bool(self._findings.get(finding))

    def failure_warnings(self) -> list[str]:
        """The findings that may reach an exit code — everything but a report.

        `loader.ask()` put the whole of `warnings()` on `RunResult.failures`,
        a rule written for a mount that would not load: that is a broken run,
        it leaves no marker in `outputs`, and a `1` is the honest answer
        (`production-ready` 53). `STALE_TOOL_DENIAL` is the first finding that
        is not a claim about capability at all — the tool is bound, the run
        calls it, and the report says so in its own sentence. Found by running
        it: the CLI printed *"the answer is right and the sentence is stale"*
        prefixed `error:`, because the prefix is derived from this same
        membership (`workflow-gallery` 44).

        The split, not the removal: a report goes on `warnings()` like every
        other finding, and `8bda508`'s rule — a report cannot move an exit
        code — is what decides which list it is *also* on.
        """
        return [
            *(
                _SENTENCES[finding].format(*subjects)
                for finding in Finding
                if finding not in REPORT_ONLY
                for subjects in self._findings.get(finding, ())
            ),
            *(
                _MOUNTED.format(path=path, sentence=_SENTENCES[finding].format(*subjects))
                for path, finding, subjects in self._mounted
                if finding not in REPORT_ONLY
            ),
        ]

    def warnings(self) -> list[str]:
        """Every finding, spelled out, grouped in `Finding` declaration order.

        This document's own findings first and unprefixed, then everything
        absorbed from a mount. The split is the point: a reader scanning the
        top of the list is reading about the document they have open.
        """
        return [
            *(
                _SENTENCES[finding].format(*subjects)
                for finding in Finding
                for subjects in self._findings.get(finding, ())
            ),
            *(
                _MOUNTED.format(path=path, sentence=_SENTENCES[finding].format(*subjects))
                for path, finding, subjects in self._mounted
            ),
        ]

    def absorb(self, child: "CompileDiagnostics", *, through: str) -> None:
        """Fold a mounted child's findings into this document's, prefixed.

        Upward, for `GraphNames.absorb`'s reason and one of its own: the child
        compiles inside the parent's build and is never run by itself, so the
        parent's report is the only place a sentence recorded down there can
        be read. Until `workflow-gallery` 75 nothing folded them and every one
        was dropped — `CAPABILITY_FAILED`, `STALE_TOOL_DENIAL`,
        `UNWIRED_REVISE` and the rest, silent in exactly the document a
        developer is least able to debug by reading.

        **`through` is the mounted package's slug, not the mount's node id**,
        and that choice is the whole of the ticket's "a package mounted three
        times does not say the same thing three times". `GraphNames` keys by
        node-id path because it answers *which card lit up*, and three mounts
        of one package are three different cards. This answers *what is wrong
        with the drawing*, and three mounts of one package are one package: a
        finding recorded by its compile is a property of the package, so
        keying by node id would print the same sentence once per mount and
        keying by slug collapses them by construction. Two mounts whose
        `overrides` genuinely produce *different* findings still both speak —
        they differ in the finding, not in the key.

        Depth costs nothing: a grandchild's already-prefixed rows are
        re-prefixed here, so a finding three levels down arrives as
        `outer/inner`.

        The failure/report split survives the crossing. A row keeps the
        `Finding` it was recorded as, so `REPORT_ONLY` membership is read
        again at render time and `8bda508`'s rule — no report may move an exit
        code — holds for an absorbed finding exactly as for an owned one.
        """
        rows = [
            (through, finding, subjects)
            for finding in Finding
            for subjects in child._findings.get(finding, ())
        ]
        rows += [
            (f"{through}/{path}", finding, subjects)
            for path, finding, subjects in child._mounted
        ]
        for row in rows:
            if row not in self._mounted:
                self._mounted.append(row)


#: The phrasings that count as *"this node holds no tools at all"*, and nothing
#: wider.
#:
#: `CLAUDE.md`'s rule reads both ways here. **Tolerant**: the observed prose is
#: matched however it is spelt — `hold`/`have`, contracted or not, wherever in
#: the sentence the subject sits. **Strict**: only a denial of *tools*, bare,
#: about *this* node, in *one* sentence. Everything the second half excludes is
#: ordinary correct prose on a node that holds something — "you have no
#: internet access", "you have no web-search tools", "you have no tools for
#: booking travel", "the user has no tools installed". A warning that fires on
#: any of those is a warning a developer learns to skip, which is worse than
#: the silence this finding replaces.
#:
#: So the shape is fixed and narrow: the subject `you`, a negation, and the
#: bare word `tools` — no qualifier in front of it, no purpose clause after it,
#: and no sentence boundary crossed between the subject and the claim.
_TOOL_DENIALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\byou\b[^.!?\n]{0,40}?\bno\s+tools\b(?!\s+(?:for|to)\b)", re.IGNORECASE),
    re.compile(
        r"\byou\b[^.!?\n]{0,40}?\b(?:do\s+not|don[\u2019']t|cannot|can[\u2019']t|will\s+not|"
        r"won[\u2019']t)\s+(?:have|hold)\s+any\s+tools\b(?!\s+(?:for|to)\b)",
        re.IGNORECASE,
    ),
)


def denies_holding_tools(text: str) -> str:
    """The phrase in `text` claiming this node holds no tools, or `""`.

    Returns the offending phrase rather than a bool so the finding can quote
    it: a warning naming the sentence is one a developer can act on without
    re-reading the whole field, and the quote is the node's own words rather
    than our paraphrase of them.
    """
    for pattern in _TOOL_DENIALS:
        found = pattern.search(text or "")
        if found:
            return found.group(0).strip()
    return ""
