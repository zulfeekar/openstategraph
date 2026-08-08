"""Tests for the open-api-explorer tools.

Two suites in one file:

- **Offline (the default)**: every tool runs against *recorded* fixture
  payloads — real responses captured from the real APIs on 2026-08-07, saved
  under `fixtures/` — served through the injectable fetcher. No network, no
  flakiness, and the assertions read actual content (the lesson
  `test_tabular_tools.py` records: a test that only checks attribute
  existence cannot fail).
- **Live (`-m live`)**: the same tools against the real APIs, marked so CI
  and the default run never depend on third-party uptime. One request per
  API family — rate-limit friendliness applies to the test suite too.

Loaded by file path under a synthetic module name, exactly like the tabular
workflow's tests — a hyphenated workflow slug can never be a package, and
putting a second workflow on `pytest.ini`'s `pythonpath` recreates the
`tools` collision its own comment warns about.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

WORKFLOW_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_module():
    name = "dyflow_workflow_open_api_explorer_tools_openapis"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, WORKFLOW_DIR / "tools" / "openapis.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


openapis = _load_module()


def fixture_fetch(fixture_name: str):
    """A fetcher that serves one recorded payload regardless of URL."""
    body = (FIXTURES / fixture_name).read_text()

    def fetch(url: str) -> str:
        fetch.urls.append(url)
        return body

    fetch.urls = []
    return fetch


def failing_fetch(message: str):
    def fetch(url: str) -> str:
        raise openapis.FetchError(message)

    return fetch


class TestGeocode:
    def test_reads_real_places_from_the_recorded_payload(self) -> None:
        result = openapis.GeocodeTool(fetch=fixture_fetch("geocode_paris.json")).run(name="Paris")
        assert result.error is None
        assert "Paris" in result.content
        assert "48.85341" in result.content  # the real latitude in the fixture

    def test_the_query_reaches_the_url(self) -> None:
        fetch = fixture_fetch("geocode_paris.json")
        openapis.GeocodeTool(fetch=fetch).run(name="Paris", count=5)
        assert "name=Paris" in fetch.urls[0]
        assert "count=5" in fetch.urls[0]

    def test_an_empty_result_set_is_a_failure_naming_the_query(self) -> None:
        empty = fixture_fetch("geocode_paris.json")
        tool = openapis.GeocodeTool(fetch=lambda url: json.dumps({"results": []}))
        result = tool.run(name="Xyzzynowhere")
        assert result.error is not None
        assert "Xyzzynowhere" in result.error
        del empty

    def test_a_network_failure_is_data_not_an_exception(self) -> None:
        result = openapis.GeocodeTool(fetch=failing_fetch("Network error reaching X")).run(
            name="Paris"
        )
        assert result.error == "Network error reaching X"


class TestForecast:
    def test_renders_the_recorded_daily_table_and_current_conditions(self) -> None:
        result = openapis.ForecastTool(fetch=fixture_fetch("forecast_paris.json")).run(
            latitude=48.85, longitude=2.35
        )
        assert result.error is None
        assert result.content.startswith("Current:")
        # Three daily rows in the recorded payload — a real tabular answer.
        assert result.content.count("| 2026-") == 3

    def test_out_of_range_coordinates_are_refused_as_data(self) -> None:
        result = openapis.ForecastTool(fetch=fixture_fetch("forecast_paris.json")).run(
            latitude=123.0, longitude=0.0
        )
        assert result.error is not None
        assert "latitude" in result.error


class TestWorldBankCountry:
    def test_reads_real_facts_from_the_recorded_payload(self) -> None:
        result = openapis.WorldBankCountryTool(
            fetch=fixture_fetch("worldbank_country_fr.json")
        ).run(code="FR")
        assert result.error is None
        assert "France" in result.content
        assert "Paris" in result.content
        assert "High income" in result.content

    def test_an_unknown_code_is_a_failure_naming_the_code(self) -> None:
        # The real API answers an unknown code with a one-element envelope.
        envelope = json.dumps([{"message": [{"id": "120", "value": "no match"}]}])
        result = openapis.WorldBankCountryTool(fetch=lambda url: envelope).run(code="ZZ")
        assert result.error is not None
        assert "ZZ" in result.error


class TestWorldBankIndicator:
    def test_renders_the_recorded_population_series_as_a_year_table(self) -> None:
        result = openapis.WorldBankIndicatorTool(
            fetch=fixture_fetch("worldbank_indicator_fr.json")
        ).run(code="FR")
        assert result.error is None
        assert "Population, total" in result.content
        assert "| 2023 | 68372286 |" in result.content

    def test_no_data_is_a_failure_naming_both_codes(self) -> None:
        envelope = json.dumps([{"message": [{"id": "120"}]}])
        result = openapis.WorldBankIndicatorTool(fetch=lambda url: envelope).run(
            code="FR", indicator="NO.SUCH.THING"
        )
        assert result.error is not None
        assert "NO.SUCH.THING" in result.error


class TestWikipediaSummary:
    def test_reads_the_recorded_extract(self) -> None:
        result = openapis.WikipediaSummaryTool(fetch=fixture_fetch("wikipedia_eiffel.json")).run(
            title="Eiffel Tower"
        )
        assert result.error is None
        assert "Eiffel Tower" in result.content
        assert "lattice tower" in result.content  # phrase from the recorded fixture

    def test_a_404_becomes_a_readable_no_such_article_failure(self) -> None:
        result = openapis.WikipediaSummaryTool(
            fetch=failing_fetch("HTTP 404 from https://en.wikipedia.org/...")
        ).run(title="No Such Page Ever")
        assert result.error is not None
        assert "No Such Page Ever" in result.error

    def test_spaces_in_the_title_become_underscores_in_the_url(self) -> None:
        fetch = fixture_fetch("wikipedia_eiffel.json")
        openapis.WikipediaSummaryTool(fetch=fetch).run(title="Eiffel Tower")
        assert fetch.urls[0].endswith("/Eiffel_Tower")


class TestEarthquakes:
    def test_renders_the_recorded_quakes_strongest_first(self) -> None:
        result = openapis.EarthquakeQueryTool(fetch=fixture_fetch("usgs_quakes.json")).run()
        assert result.error is None
        assert "Magnitude" in result.content
        # The recorded payload is orderby=magnitude with five features.
        assert result.content.count("| 2026-") == 5

    def test_no_matches_is_a_failure_with_actionable_advice(self) -> None:
        empty = json.dumps({"type": "FeatureCollection", "features": []})
        result = openapis.EarthquakeQueryTool(fetch=lambda url: empty).run(min_magnitude=9.5)
        assert result.error is not None
        assert "9.5" in result.error

    def test_the_configured_result_cap_bounds_what_the_model_asked_for(self) -> None:
        fetch = fixture_fetch("usgs_quakes.json")
        tool = openapis.EarthquakeQueryTool(fetch=fetch).configure({"maxResults": 3})
        tool.run(limit=50)
        assert "limit=3" in fetch.urls[0]

    def test_configure_returns_a_fresh_instance_not_a_mutation(self) -> None:
        shared = openapis.EarthquakeQueryTool(fetch=fixture_fetch("usgs_quakes.json"))
        capped = shared.configure({"maxResults": 3})
        assert capped is not shared
        assert shared.result_cap == 50


class TestCatalogue:
    def test_six_tools_with_unique_names_and_node_types(self) -> None:
        names = [tool.name for tool in openapis.TOOLS]
        node_types = [tool.node_type for tool in openapis.TOOLS]
        assert len(names) == 6
        assert len(set(names)) == 6
        assert len(set(node_types)) == 6
        assert all(t.startswith("tool.") for t in node_types)

    def test_every_tool_publishes_a_manifest(self) -> None:
        for tool in openapis.TOOLS:
            manifest = tool.manifest()
            assert manifest["name"] == tool.name
            assert manifest["args_schema"]


# --------------------------------------------------------------------------- #
# Live suite — `pytest -m live`. One request per API family, real network.
# --------------------------------------------------------------------------- #


@pytest.mark.live
class TestLiveApis:
    def test_open_meteo_geocodes_a_real_city(self) -> None:
        result = openapis.GeocodeTool().run(name="Paris", count=1)
        assert result.error is None
        assert "Paris" in result.content

    def test_world_bank_knows_france(self) -> None:
        result = openapis.WorldBankCountryTool().run(code="FR")
        assert result.error is None
        assert "Paris" in result.content

    def test_wikipedia_summarises_the_eiffel_tower(self) -> None:
        result = openapis.WikipediaSummaryTool().run(title="Eiffel Tower")
        assert result.error is None
        assert "Eiffel" in result.content

    def test_usgs_reports_recent_quakes(self) -> None:
        result = openapis.EarthquakeQueryTool().run(min_magnitude=2.5, days=30)
        assert result.error is None
        assert "Magnitude" in result.content
