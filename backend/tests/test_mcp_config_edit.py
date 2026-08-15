"""Editing `mcp_servers:` in place, without eating the file around it.

mcp-connect ticket 03. `54497b3` shipped the registry read-only, so the panel
needed a writer. The two things worth testing here are not "does it write" —
they are the two ways a writer of a *committed, commented* file goes wrong:

1. it rewrites the whole document and silently deletes every comment, which
   for this file is deleting the reason the format was chosen;
2. it writes something the loader would refuse, so the next read fails and the
   project's config is broken by the tool that was supposed to configure it.

Nothing here reaches a network. The catalogue functions are pure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.config_edit import (
    remove_mcp_server,
    upsert_mcp_server,
    writable_config_path,
)
from openstategraph.config_file import (
    CONFIG_ENV_VAR,
    ConfigError,
    McpAuthConfig,
    McpServerConfig,
    config_mcp_servers,
    load_config,
)
from openstategraph.prebuilt_mcp import mcp_server_catalogue

COMMENTED = """\
# OpenStateGraph — this project's committed configuration.
#
# NO SECRETS. EVER. This file is committed.

version: 1

# The model used when nothing more specific asked for one.
default_model: ollama:gpt-oss:120b-cloud

# Where <slug>/workflow.json packages live.
workflows_dir: workflows
"""


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "openstategraph.yaml"
    path.write_text(COMMENTED, encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))
    return path


def entry(
    name: str = "Internal docs", url: str = "https://mcp.example.test/mcp", **kwargs: object
) -> McpServerConfig:
    return McpServerConfig(name=name, url=url, **kwargs)  # type: ignore[arg-type]


class TestTheFileSurvives:
    def test_every_comment_is_still_there_after_a_write(self, config: Path) -> None:
        upsert_mcp_server(entry())
        after = config.read_text(encoding="utf-8")

        for line in COMMENTED.splitlines():
            assert line in after, line

    def test_the_entry_reads_back_through_the_normal_loader(self, config: Path) -> None:
        upsert_mcp_server(entry(transport="sse"))

        servers = config_mcp_servers(load_config(config))
        assert [(s.name, s.url, s.transport, s.origin) for s in servers] == [
            ("Internal docs", "https://mcp.example.test/mcp", "sse", "project")
        ]

    def test_the_block_s_own_header_is_written_once_not_once_per_save(self, config: Path) -> None:
        """Found in the live walk, on the second Save press of the session."""
        upsert_mcp_server(entry())
        upsert_mcp_server(entry("Another", url="https://other.example.test/mcp"))

        after = config.read_text(encoding="utf-8")
        assert after.count("# MCP servers this project can bind") == 1

    def test_a_second_save_of_the_same_name_replaces_rather_than_duplicates(
        self, config: Path
    ) -> None:
        upsert_mcp_server(entry())
        upsert_mcp_server(entry(url="https://moved.example.test/mcp"))

        servers = config_mcp_servers(load_config(config))
        assert [s.url for s in servers] == ["https://moved.example.test/mcp"]

    def test_the_variable_name_is_stored_and_no_value_could_be(self, config: Path) -> None:
        upsert_mcp_server(
            entry(auth=McpAuthConfig(kind="header", header_name="X-API-KEY", token_env="MY_TOKEN"))
        )

        server = config_mcp_servers(load_config(config))[0]
        assert (server.auth.kind, server.auth.header_name, server.auth.token_env) == (
            "header",
            "X-API-KEY",
            "MY_TOKEN",
        )

    def test_the_file_is_created_when_the_project_has_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "openstategraph.yaml"
        monkeypatch.setenv(CONFIG_ENV_VAR, str(target))

        upsert_mcp_server(entry())

        assert target.is_file()
        assert load_config(target).version == 1


class TestTheLoaderIsTheOnlyJudge:
    def test_a_pasted_credential_is_refused_and_the_file_is_untouched(self, config: Path) -> None:
        before = config.read_text(encoding="utf-8")

        with pytest.raises(ConfigError):
            upsert_mcp_server(entry(auth=McpAuthConfig(kind="bearer", token_env="sk-live-abc123")))

        assert config.read_text(encoding="utf-8") == before

    def test_a_url_that_is_actually_a_key_is_refused_by_the_same_walk(self, config: Path) -> None:
        with pytest.raises(ConfigError):
            upsert_mcp_server(McpServerConfig(name="Oops", url="sk-ant-api03-not-a-url"))

        assert "Oops" not in config.read_text(encoding="utf-8")

    def test_a_pyproject_only_project_is_told_where_to_put_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.openstategraph]\nversion = 1\n", encoding="utf-8")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(pyproject))

        with pytest.raises(ConfigError) as raised:
            writable_config_path()

        assert "pyproject.toml" in str(raised.value)


class TestDeleting:
    def test_a_project_entry_leaves_no_line_behind(self, config: Path) -> None:
        upsert_mcp_server(entry())
        remove_mcp_server("Internal docs")

        assert "Internal docs" not in config.read_text(encoding="utf-8")
        assert config_mcp_servers(load_config(config)) == []

    def test_a_built_in_default_is_tombstoned_rather_than_pretended_gone(
        self, config: Path
    ) -> None:
        remove_mcp_server("LangChain docs")

        configured = config_mcp_servers(load_config(config))
        catalogue = mcp_server_catalogue(configured)
        assert "LangChain docs" not in catalogue
        # The other default is untouched: removing one is not opting out.
        assert "LangChain API reference" in catalogue
        assert "enabled: false" in config.read_text(encoding="utf-8")

    def test_re_adding_a_tombstoned_default_brings_it_back(self, config: Path) -> None:
        remove_mcp_server("LangChain docs")
        upsert_mcp_server(
            McpServerConfig(name="LangChain docs", url="https://docs.langchain.com/mcp")
        )

        catalogue = mcp_server_catalogue(config_mcp_servers(load_config(config)))
        assert "LangChain docs" in catalogue

    def test_deleting_the_last_entry_removes_the_block_and_keeps_the_comments(
        self, config: Path
    ) -> None:
        upsert_mcp_server(entry())
        remove_mcp_server("Internal docs")
        after = config.read_text(encoding="utf-8")

        assert "mcp_servers" not in after
        for line in COMMENTED.splitlines():
            assert line in after, line

    def test_a_name_nobody_declared_is_an_error_rather_than_a_silent_success(
        self, config: Path
    ) -> None:
        with pytest.raises(ConfigError):
            remove_mcp_server("Never registered")
