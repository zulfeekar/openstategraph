"""Open API explorer tools — keyless public HTTP APIs, errors as data.

Four API families, one worker archetype each (ticket 42):

- **Open-Meteo** — geocoding + weather forecast (https://open-meteo.com)
- **World Bank** — country facts + indicator series (https://api.worldbank.org)
- **Wikipedia REST** — page summaries (https://en.wikipedia.org/api/rest_v1)
- **USGS** — recent earthquakes (https://earthquake.usgs.gov/fdsnws/event/1)

REST Countries was the ticket's original country-facts API, but it is no
longer keyless — verified live 2026-08-07: every legacy version path answers
with a deprecation envelope and the current `api.restcountries.com` returns
`401 authKeyMissing`. The World Bank API replaces it: keyless, stable, and
its indicator series are genuinely *tabular*, which the workflow's
structured-output requirement wants anyway.

Design rules, all inherited from the repo's standing decisions:

- **Errors are data.** A timeout, a 404, an empty result set — every one
  comes back as `ToolResult.failure(...)` with the URL or query named, so the
  model can read what went wrong and retry differently. Nothing here raises
  past `BaseTool.run`.
- **The fetcher is injectable.** Every tool takes `fetch=` in its
  constructor; tests inject a stub that serves recorded fixture payloads, so
  the suite runs offline. The default fetcher is stdlib `urllib` — no new
  dependency — with a modest timeout and a descriptive User-Agent
  (Wikipedia's API etiquette asks for one).
- **Rate-limit friendliness** is documented in this workflow's `AGENTS.md`;
  the code's contribution is one request per tool call, bounded result
  counts, and no retry storm (retrying is the graph's `RetryPolicy`, with
  backoff, never a tool-level loop).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult

#: One request per tool call, and it should give up before the graph's own
#: per-node timeout would.
FETCH_TIMEOUT_SECONDS = 20

#: Wikipedia's API etiquette asks every client for a descriptive User-Agent
#: with a contact; the other APIs simply ignore it.
USER_AGENT = "openstategraph-open-api-explorer/0.1 (local dev tool; https://github.com/openstategraph)"

#: url -> decoded response body. Raises `FetchError` on any transport or
#: HTTP-status failure; tools convert that to `ToolResult.failure`.
Fetcher = Callable[[str], str]


class FetchError(Exception):
    """A transport-level failure with a message a model can act on."""


def _ssl_context():
    """certifi's CA bundle when available (ticket 59).

    python.org macOS installs ship no system CA path, so a bare `urlopen`
    fails every HTTPS call with CERTIFICATE_VERIFY_FAILED unless the user
    hand-exports SSL_CERT_FILE. certifi rides in with the backend deps;
    falling back to the default context keeps this import-safe without it.
    """
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def default_fetch(url: str) -> str:
    """Stdlib fetch: one GET, bounded timeout, readable failures."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(
            request, timeout=FETCH_TIMEOUT_SECONDS, context=_ssl_context()
        ) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Network error reaching {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError(f"Timed out after {FETCH_TIMEOUT_SECONDS}s: {url}") from exc


def _rows_to_markdown(columns: list[str], rows: list[tuple]) -> str:
    """The same markdown-table formatter shape the tabular workflow uses."""
    if not rows:
        return "_No rows._"
    head = f"| {' | '.join(columns)} |"
    rule = f"| {' | '.join('---' for _ in columns)} |"
    body = [f"| {' | '.join('' if c is None else str(c) for c in row)} |" for row in rows]
    return "\n".join([head, rule, *body])


class _HttpJsonTool(BaseTool):
    """Shared plumbing for every tool here: fetch one URL, parse JSON.

    Within-family shared behaviour, so it lives on a family base
    (CLAUDE.md's boundary rule): the fetcher slot, the failure translation
    and the JSON parse are declared once. Subclasses implement `_query`,
    returning either a `ToolResult` built from parsed data or a failure.
    """

    def __init__(self, *, fetch: Fetcher | None = None) -> None:
        self._fetch = fetch or default_fetch

    def _get_json(self, url: str) -> Any:
        """Fetch + parse. Raises `FetchError`, which `_execute` translates."""
        body = self._fetch(url)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(f"Response from {url} was not JSON: {exc}") from exc

    def _execute(self, args: BaseModel) -> ToolResult:
        try:
            return self._query(args)
        except FetchError as exc:
            return ToolResult.failure(str(exc))

    def _query(self, args: BaseModel) -> ToolResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Open-Meteo
# --------------------------------------------------------------------------- #


class GeocodeArgs(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, description="Place name to look up, e.g. 'Paris'")
    count: int = Field(default=3, ge=1, le=10, description="How many matches to return")


class GeocodeTool(_HttpJsonTool):
    """Resolve a place name to coordinates via Open-Meteo's geocoding API."""

    name = "open_meteo_geocode"
    node_type = "tool.openmeteo-geocode"
    description = (
        "Look up a city or place name and return its latitude, longitude, country "
        "and timezone. Call this before the forecast tool, which needs coordinates."
    )
    Args = GeocodeArgs

    def _query(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, GeocodeArgs)
        url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + urllib.parse.urlencode(
                {"name": args.name, "count": args.count, "language": "en", "format": "json"}
            )
        )
        payload = self._get_json(url)
        results = payload.get("results") or []
        if not results:
            return ToolResult.failure(
                f"No place matched {args.name!r}. Try a simpler or differently-spelled name."
            )
        rows = [
            (
                place.get("name"),
                place.get("country"),
                place.get("latitude"),
                place.get("longitude"),
                place.get("timezone"),
                place.get("population", ""),
            )
            for place in results
        ]
        return ToolResult(
            content=_rows_to_markdown(
                ["Name", "Country", "Latitude", "Longitude", "Timezone", "Population"], rows
            )
        )


class ForecastArgs(BaseModel):
    model_config = {"extra": "forbid"}
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    days: int = Field(default=3, ge=1, le=7, description="Forecast days (1-7)")


class ForecastTool(_HttpJsonTool):
    """Current conditions + daily forecast from Open-Meteo."""

    name = "open_meteo_forecast"
    node_type = "tool.openmeteo-forecast"
    description = (
        "Get current weather and a daily forecast (temperature min/max, "
        "precipitation, wind) for coordinates. Use the geocode tool first to "
        "turn a place name into latitude/longitude."
    )
    Args = ForecastArgs

    def _query(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ForecastArgs)
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
            {
                "latitude": args.latitude,
                "longitude": args.longitude,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
                "current": "temperature_2m,wind_speed_10m,weather_code",
                "timezone": "auto",
                "forecast_days": args.days,
            }
        )
        payload = self._get_json(url)
        daily = payload.get("daily") or {}
        dates = daily.get("time") or []
        if not dates:
            return ToolResult.failure(
                f"Open-Meteo returned no forecast for ({args.latitude}, {args.longitude})."
            )
        current = payload.get("current") or {}
        units = payload.get("daily_units") or {}
        header = (
            f"Current: {current.get('temperature_2m', '?')}°C, "
            f"wind {current.get('wind_speed_10m', '?')} km/h "
            f"(timezone {payload.get('timezone', '?')})"
        )
        rows = list(
            zip(
                dates,
                daily.get("temperature_2m_max") or [],
                daily.get("temperature_2m_min") or [],
                daily.get("precipitation_sum") or [],
                daily.get("wind_speed_10m_max") or [],
            )
        )
        table = _rows_to_markdown(
            [
                "Date",
                f"Max ({units.get('temperature_2m_max', '°C')})",
                f"Min ({units.get('temperature_2m_min', '°C')})",
                f"Precip ({units.get('precipitation_sum', 'mm')})",
                f"Wind max ({units.get('wind_speed_10m_max', 'km/h')})",
            ],
            rows,
        )
        return ToolResult(content=f"{header}\n\n{table}")


# --------------------------------------------------------------------------- #
# World Bank
# --------------------------------------------------------------------------- #


class CountryArgs(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(
        min_length=2,
        max_length=3,
        description="ISO country code, 2 or 3 letters, e.g. 'FR' or 'FRA'",
    )


class WorldBankCountryTool(_HttpJsonTool):
    """Country facts (capital, region, income level) from the World Bank."""

    name = "world_bank_country"
    node_type = "tool.worldbank-country"
    description = (
        "Get facts about a country by its ISO code (e.g. 'FR'): capital city, "
        "region, and income level, from the World Bank open data API."
    )
    Args = CountryArgs

    def _query(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CountryArgs)
        code = urllib.parse.quote(args.code.strip().upper())
        url = f"https://api.worldbank.org/v2/country/{code}?format=json"
        payload = self._get_json(url)
        # World Bank envelope: [meta, rows]; an unknown code returns a
        # one-element envelope carrying a message instead of rows.
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
        if not rows:
            return ToolResult.failure(
                f"World Bank has no country for code {args.code!r}. Use an ISO "
                "3166 code such as 'FR', 'DEU' or 'JPN'."
            )
        country = rows[0]
        table = _rows_to_markdown(
            ["Field", "Value"],
            [
                ("Name", country.get("name")),
                ("Capital", country.get("capitalCity")),
                ("Region", (country.get("region") or {}).get("value")),
                ("Income level", (country.get("incomeLevel") or {}).get("value")),
                ("ISO3", country.get("id")),
                ("Longitude", country.get("longitude")),
                ("Latitude", country.get("latitude")),
            ],
        )
        return ToolResult(content=table)


class IndicatorArgs(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(min_length=2, max_length=3, description="ISO country code, e.g. 'FR'")
    indicator: str = Field(
        default="SP.POP.TOTL",
        description=(
            "World Bank indicator id. Common ones: SP.POP.TOTL (population), "
            "NY.GDP.MKTP.CD (GDP US$), SP.DYN.LE00.IN (life expectancy)"
        ),
    )
    years: int = Field(default=5, ge=1, le=20, description="How many recent years")


class WorldBankIndicatorTool(_HttpJsonTool):
    """An indicator series (population, GDP, ...) as a year-by-year table."""

    name = "world_bank_indicator"
    node_type = "tool.worldbank-indicator"
    description = (
        "Get a World Bank indicator series for a country as a year-by-year "
        "table — population (SP.POP.TOTL), GDP (NY.GDP.MKTP.CD), life "
        "expectancy (SP.DYN.LE00.IN) and thousands more."
    )
    Args = IndicatorArgs

    def _query(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, IndicatorArgs)
        code = urllib.parse.quote(args.code.strip().upper())
        indicator = urllib.parse.quote(args.indicator.strip())
        end = datetime.now(timezone.utc).year
        start = end - args.years
        url = (
            f"https://api.worldbank.org/v2/country/{code}/indicator/{indicator}?"
            + urllib.parse.urlencode({"format": "json", "date": f"{start}:{end}", "per_page": 25})
        )
        payload = self._get_json(url)
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
        if not rows:
            return ToolResult.failure(
                f"World Bank returned no data for country {args.code!r} and "
                f"indicator {args.indicator!r}. Check both codes."
            )
        name = (rows[0].get("indicator") or {}).get("value") or args.indicator
        country = (rows[0].get("country") or {}).get("value") or args.code
        table = _rows_to_markdown(
            ["Year", name],
            [(entry.get("date"), entry.get("value")) for entry in rows if entry.get("value") is not None],
        )
        return ToolResult(content=f"{name} — {country}\n\n{table}")


# --------------------------------------------------------------------------- #
# Wikipedia REST
# --------------------------------------------------------------------------- #


class WikipediaArgs(BaseModel):
    model_config = {"extra": "forbid"}
    title: str = Field(min_length=1, description="Article title, e.g. 'Eiffel Tower'")


class WikipediaSummaryTool(_HttpJsonTool):
    """One article's lead summary from Wikipedia's REST API."""

    name = "wikipedia_summary"
    node_type = "tool.wikipedia-summary"
    description = (
        "Get the lead summary of an English Wikipedia article by title. Good for "
        "background facts and definitions; not a search — the title must be close "
        "to the real article name."
    )
    Args = WikipediaArgs

    def _query(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, WikipediaArgs)
        title = urllib.parse.quote(args.title.strip().replace(" ", "_"), safe="")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        try:
            payload = self._get_json(url)
        except FetchError as exc:
            if "HTTP 404" in str(exc):
                return ToolResult.failure(
                    f"No Wikipedia article titled {args.title!r}. Try the exact "
                    "article name, e.g. 'Eiffel Tower'."
                )
            raise
        extract = payload.get("extract") or ""
        if not extract:
            return ToolResult.failure(f"Wikipedia returned an empty summary for {args.title!r}.")
        heading = payload.get("title") or args.title
        description = payload.get("description") or ""
        lines = [f"**{heading}**" + (f" — {description}" if description else ""), "", extract]
        return ToolResult(content="\n".join(lines))


# --------------------------------------------------------------------------- #
# USGS earthquakes
# --------------------------------------------------------------------------- #


class EarthquakeArgs(BaseModel):
    model_config = {"extra": "forbid"}
    min_magnitude: float = Field(default=4.5, ge=0, le=10)
    days: int = Field(default=7, ge=1, le=30, description="How many days back to search")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum quakes to return")


class EarthquakeQueryTool(_HttpJsonTool):
    """Recent significant earthquakes from the USGS FDSN event service."""

    name = "usgs_earthquakes"
    node_type = "tool.usgs-earthquakes"
    description = (
        "List recent earthquakes worldwide above a minimum magnitude, from the "
        "USGS. Returns time, magnitude, place and depth, strongest first."
    )
    Args = EarthquakeArgs

    def __init__(self, *, fetch: Fetcher | None = None, result_cap: int = 50) -> None:
        super().__init__(fetch=fetch)
        self.result_cap = result_cap

    def configure(self, data: dict[str, Any]) -> "EarthquakeQueryTool":
        """The bound node's "Max results" field becomes this instance's ceiling.

        A fresh instance, never a mutation — the same contract
        `QueryDataTool.configure` documents for its row cap.
        """
        configured = data.get("maxResults")
        if isinstance(configured, (int, float)) and configured > 0:
            return type(self)(fetch=self._fetch, result_cap=int(configured))
        if isinstance(configured, str) and configured.strip().isdigit():
            return type(self)(fetch=self._fetch, result_cap=int(configured.strip()))
        return self

    def _query(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, EarthquakeArgs)
        start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
        url = "https://earthquake.usgs.gov/fdsnws/event/1/query?" + urllib.parse.urlencode(
            {
                "format": "geojson",
                "starttime": start,
                "minmagnitude": args.min_magnitude,
                "limit": min(args.limit, self.result_cap),
                "orderby": "magnitude",
            }
        )
        payload = self._get_json(url)
        features = payload.get("features") or []
        if not features:
            return ToolResult.failure(
                f"No earthquakes of magnitude ≥ {args.min_magnitude} in the last "
                f"{args.days} day(s). Lower the magnitude or widen the window."
            )
        rows = []
        for feature in features:
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or [None, None, None]
            when = props.get("time")
            stamp = (
                datetime.fromtimestamp(when / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                if isinstance(when, (int, float))
                else "?"
            )
            rows.append((stamp, props.get("mag"), props.get("place"), coords[2]))
        return ToolResult(
            content=_rows_to_markdown(["Time (UTC)", "Magnitude", "Place", "Depth (km)"], rows)
        )


#: The workflow's tool catalogue — what capability discovery imports.
TOOLS = [
    GeocodeTool(),
    ForecastTool(),
    WorldBankCountryTool(),
    WorldBankIndicatorTool(),
    WikipediaSummaryTool(),
    EarthquakeQueryTool(),
]

__all__ = [
    "TOOLS",
    "EarthquakeQueryTool",
    "FetchError",
    "Fetcher",
    "ForecastTool",
    "GeocodeTool",
    "WikipediaSummaryTool",
    "WorldBankCountryTool",
    "WorldBankIndicatorTool",
    "default_fetch",
]
