# Prompt-injection screening is an optional extra

**Status:** adopted, opt-in. Guardrails ticket 04.
**Date:** 2026-08-15.

## The question

The owner asked for injection protection alongside PII. They are not the same
kind of thing and must not ship as one switch.

LangChain's own PII detectors are **deterministic shapes** — `email`,
`credit_card` (Luhn-validated), `ip`, `mac_address`, `url`. Every one is a
pattern. None of them looks at intent, so nothing in the Guardrail node
detects a jailbreak or an injected instruction, and the docs must not imply
that it does.

## What was adopted

`BastionGuardrailMiddleware`, from the third-party distribution
[`bastion-prompt-protection`](https://pypi.org/project/bastion-prompt-protection/)
(`bastion-soft/bastion-prompt-protection`), behind a new `[bastion]` extra.

It is **never** part of `[all]`, `[server]`, or any other extra, and a test
asserts that transitively.

## What it costs, from the artifact rather than from memory

Read off `bastion_prompt_protection-1.3.5-py3-none-any.whl`:

| Fact | Consequence |
| --- | --- |
| **Licence: AGPL-3.0-or-later** | An adopter takes this position deliberately, in their own deployment, or not at all. This alone rules out `[all]`. |
| Commercial weights are gated on the Hugging Face Hub, with offline Ed25519 licence verification | The free path and the paid path are different model downloads; neither is something to acquire on a developer's behalf. |
| Runtime dependencies: `onnxruntime`, `huggingface-hub`, `numpy`, `tokenizers` | A local ONNX model, in a product whose dependency floor is four packages and whose install proof fits in a clean venv. |
| ~694 downloads/month at the time of writing | Small. Not disqualifying for an opt-in, and not something to put in a default install. |
| Screens in `before_model`, with `check_input` and `check_tool_results` both defaulting to `True` | It catches **indirect** injection through retrieved content, which is the dangerous case. It also means it runs **inside the agent**. |

That last row is why this could never have been the Guardrail node however
visible we made it: the injection that matters arrives mid-loop, in a tool
result, inside an agent's own compiled graph. There is no wire on the canvas
between a fetched page and the model that reads it.

## Where it is switched on

`document.settings.injectionScreening`, a **workflow** setting compiled to
graph assembly — beside the checkpointer and the memory settings, and for the
same reason `retry_policy` lives there (CLAUDE.md: retry, timeout and caching
are graph-assembly parameters, not node concerns).

Deliberately not a field on the Agent card: a per-agent checkbox is exactly
the duplication the Guardrail node exists to abolish — the shipped Chinook
document has three agents, so it would be three copies of one decision and
three chances to miss one.

Deliberately not a field on the Guardrail card either: that would claim the
node does something it cannot.

## How it composes

It fills the `injection-screening` slot, **first** in
`AbstractAgentNode.SLOT_ORDER`. The position is the whole argument: `before_*`
hooks run first to last, so screening placed anywhere else would run after
another middleware had already acted on the injected text. Named slot, never
a position number — CLAUDE.md's rule, and here it is load-bearing rather than
ceremonial.

## What happens when it is asked for and absent

The run **proceeds**, and the developer channel carries one line naming the
exact command:

> This workflow asked for prompt-injection screening and ran without it — the
> bastion-prompt-protection integration is not installed (pip install
> 'openstategraph[bastion]').

The consequence leads and the fix follows, which is the
`ProviderEnvironment.readiness()` shape (workflow-gallery ticket 38) applied to a
second wall. Refusing to run because an optional extra is missing would turn a
dependency gap into an outage; failing with a `ModuleNotFoundError` traceback
would describe our machinery instead of their system.

A workflow that never asked reports nothing at all. A warning on every run of
every workflow is one nobody reads.

## What a deployer who declines should do instead

Nothing in this repository substitutes for it, and it would be dishonest to
imply otherwise. The available mitigations are architectural rather than
detective, and they are the ones this product already gives you:

- **Do not give an agent a tool it does not need.** An injected instruction
  can only ask for capabilities the agent holds.
- **Put a `human.approval` node before a consequential step.** An injection
  that has to get past a person is a different problem from one that does not.
- **Mount untrusted work as a subgraph.** A mounted workflow receives a task
  and reports a result; it never sees the parent's messages or state, so a
  poisoned page reaches a smaller blast radius.
- **Put a Guardrail before Output.** It will not detect the injection, but it
  will still stop the *exfiltration* half of the common attack — an email
  address or a URL the model was talked into repeating.

That last one is worth stating precisely, because it is the only place the two
mechanisms meet: shapes cannot detect an instruction, but they can catch what
an instruction was trying to carry out.
