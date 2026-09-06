"""Two vocabularies whose second consumer was outside every pin.

Framework-packaging ticket 11. The habit the 2026-08-16 architecture review
named: every pin in this repository was written against the file that was in
front of its author, and where a contract has a *second* consumer, the second
one is the one an adopter touches.

**1. The provider credential key.** `runtimeCredentialKey` on each browser-side
provider is the name the editor sends a pasted key under; `ProviderSpec.env_vars`
is the name the server accepts it under. `api/model_resolution.apply_credentials`
**silently `continue`s** on a name it does not accept, so a one-character
divergence reproduces the exact bug `src/core/runtime/providerCredentials.ts`
says it was written to fix: a key pasted in the editor, a run reporting "no
model configured", and nothing logged anywhere. Each side tested its own half;
nothing compared them.

**2. The plugin field `kind`.** A closed set that was written down three times
with three memberships — `number` was documented in `abc/tool.py` and in
`docs/building-an-atom.md`, and `src/app/pluginNodes.ts` has no branch for it,
so a plugin author following the documented set got a text box in silence.

Read out of the TypeScript source rather than out of a build artifact, as
`test_mcp_field_contract.py` and `test_guardrail_field_contract.py` are: the
source is what a developer edits, and a pin against `dist/` goes quiet exactly
when somebody edits the source and does not rebuild. Reading repository files
also keeps this green on CI's backend leg, which has no Node and no
`node_modules`.
"""

from __future__ import annotations

import re
from pathlib import Path

from openstategraph.abc.tool import PLUGIN_FIELD_KINDS
from openstategraph.api.model_resolution import accepted_credential_keys

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = ROOT / "src" / "core" / "providers"
RENDERER = ROOT / "src" / "app" / "pluginNodes.ts"

#: The browser providers that name a credential. `MockProvider` needs none,
#: which is what makes it the default with no keys configured.
PROVIDER_FILES = ("AnthropicProvider.ts", "OpenAIProvider.ts", "OllamaProvider.ts")


def _runtime_credential_keys() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in PROVIDER_FILES:
        source = (PROVIDERS / name).read_text()
        match = re.search(r"runtimeCredentialKey = '([A-Z0-9_]+)'", source)
        assert match, f"{name} no longer declares a runtimeCredentialKey"
        found[name] = match.group(1)
    return found


class TestTheKeyTheEditorSendsIsAKeyTheServerAccepts:
    def test_the_extractor_found_all_three(self) -> None:
        """The control. An extractor that matched nothing would make the
        assertion below a statement about the empty set."""
        assert len(_runtime_credential_keys()) == 3

    def test_every_key_the_editor_sends_is_accepted(self) -> None:
        sent = set(_runtime_credential_keys().values())

        assert sent <= accepted_credential_keys(), (
            "A provider's runtimeCredentialKey is not in accepted_credential_keys(), "
            "so apply_credentials will drop it without a word: the key is pasted in "
            "the editor and the run still reports no model configured."
        )

    def test_subset_and_not_equality_is_on_purpose(self) -> None:
        """The server may accept a name no browser provider sends — a provider
        installed as a plugin has no TypeScript here at all. The other
        direction is the one that fails silently, and it is the one pinned."""
        assert accepted_credential_keys() >= set(_runtime_credential_keys().values())

    def test_no_address_is_ever_sent_as_a_credential(self) -> None:
        """`OLLAMA_HOST` is in `env_vars` and must never be forwardable — a
        client-supplied address written into a process-global `os.environ` is a
        redirection dressed as a fallback (reviews-2026-08-14 ticket 01)."""
        assert "OLLAMA_HOST" not in _runtime_credential_keys().values()


class TestTheClosedSetOfPluginFieldKinds:
    @staticmethod
    def _rendered_kinds() -> list[str]:
        source = RENDERER.read_text()
        block = re.search(r"export const PLUGIN_FIELD_KINDS = \[(.*?)\]", source, re.S)
        assert block, "pluginNodes.ts no longer declares PLUGIN_FIELD_KINDS"
        return re.findall(r"'([a-z-]+)'", block.group(1))

    def test_the_extractor_can_actually_fail(self) -> None:
        assert self._rendered_kinds()

    def test_the_renderer_and_the_ladder_declare_the_same_set(self) -> None:
        assert self._rendered_kinds() == list(PLUGIN_FIELD_KINDS), (
            "abc/tool.py's PLUGIN_FIELD_KINDS and pluginNodes.ts's have diverged. A "
            "kind only Python documents is a control nobody gets; a kind only the "
            "editor renders is one no plugin author knows to ask for."
        )

    def test_number_is_no_longer_promised(self) -> None:
        """The specific divergence the ticket found. `fields.ts` has no
        `number` kind at all, so promising one was promising a control the
        editor cannot build."""
        assert "number" not in PLUGIN_FIELD_KINDS

    def test_the_documentation_promises_the_same_set(self) -> None:
        """`docs/building-an-atom.md`'s worked `ToolField` carries the set in a
        trailing comment — the third of the three memberships. (The *other*
        list in that page, "Available kinds", is `fields.ts`'s nine and is a
        different question: what an in-repo node may declare.)"""
        atom = (ROOT / "docs" / "building-an-atom.md").read_text()
        listed = re.search(r'kind="text",\s*#\s*([a-z |]+)', atom)

        assert listed, "the worked ToolField example no longer names the set"
        assert [word.strip() for word in listed.group(1).split("|")] == list(
            PLUGIN_FIELD_KINDS
        )


class TestAnUnrenderableKindIsSaidOutLoud:
    @staticmethod
    def _warnings(kind: str) -> list[str]:
        from openstategraph.api.plugin_capabilities import _declared_fields

        class _Tool:
            node_fields = ({"key": "depth", "kind": kind},)

        _fields, warnings = _declared_fields(_Tool(), "tool.acme", "acme-osg")
        return warnings

    def test_a_kind_the_editor_cannot_render_earns_a_warning(self) -> None:
        found = " ".join(self._warnings("number"))

        assert "number" in found
        assert "text box" in found

    def test_the_field_is_still_shown(self) -> None:
        """Degrade, never disappear — a card missing a control is worse than a
        control of the wrong shape."""
        from openstategraph.api.plugin_capabilities import _declared_fields

        class _Tool:
            node_fields = ({"key": "depth", "kind": "number"},)

        fields, _warnings = _declared_fields(_Tool(), "tool.acme", "acme-osg")

        assert [entry["key"] for entry in fields] == ["depth"]

    def test_a_supported_kind_says_nothing(self) -> None:
        assert self._warnings("textarea") == []
