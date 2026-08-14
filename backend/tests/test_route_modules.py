"""Handlers are importable, and the way they reach the app is invisible.

`api/main.py` defined all thirty-two route handlers inside `create_app()`, as
closures over its locals — including three names unpacked from the very object
that exists to hold them together (`workflow_store = services.store`, and two
more). That is the defect ticket 07 found in `NodeRuntime.__init__` wearing a
different hat, and its cost was that no handler had a name anything could
import: testing one route meant constructing the whole application
(reviews-2026-08-14 ticket 15).

Two properties are worth holding, and neither is "the file is shorter".
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import pytest
from fastapi.routing import APIRoute

from openstategraph.api.main import create_app


def api_routes(app: Any) -> list[APIRoute]:
    """Every `APIRoute` an app serves, whatever FastAPI does with routers.

    Not `[r for r in app.routes if isinstance(r, APIRoute)]`. That works on
    FastAPI 0.121, where `include_router` copies each route onto the app, and
    returns **nothing** on 0.141, where the app holds an opaque
    `_IncludedRouter` wrapper instead. `backend/pyproject.toml` asks for
    `fastapi>=0.115` with no upper bound, so both are versions this repository
    actually runs on — found by running the CI floor leg (3.11) in a clean
    environment, which resolved the newer one (ship-it ticket 49).

    A test that silently compares two empty sets is worse than no test, and
    that is what the isinstance filter did here.
    """
    found: list[APIRoute] = []
    seen: set[int] = set()

    def walk(routes: Any) -> None:
        for route in routes or ():
            if id(route) in seen:
                continue
            seen.add(id(route))
            if isinstance(route, APIRoute):
                found.append(route)
                continue
            inner = getattr(route, "original_router", None)
            if inner is not None:
                walk(getattr(inner, "routes", None))

    walk(getattr(app, "routes", None))
    return found


def route_modules() -> list[Any]:
    """Every module under `api/routes/`, imported."""
    from openstategraph.api import routes

    found = []
    for info in pkgutil.iter_modules(routes.__path__):
        found.append(importlib.import_module(f"openstategraph.api.routes.{info.name}"))
    return found


class TestAHandlerHasAName:
    def test_every_route_module_exposes_a_router(self) -> None:
        modules = route_modules()

        assert modules, "no route modules found"
        for module in modules:
            assert hasattr(module, "router"), module.__name__

    def test_a_handler_can_be_imported_without_building_the_app(self) -> None:
        """The property the whole split exists for.

        A closure over `create_app`'s locals cannot be imported at all, so
        every test of every route paid for the entire application — every
        service, every registry, every dependency.
        """
        for module in route_modules():
            handlers = [
                route.endpoint
                for route in module.router.routes
                if isinstance(route, APIRoute)
            ]
            assert handlers, f"{module.__name__} has a router but no routes"
            for handler in handlers:
                assert inspect.getmodule(handler) is module


class TestTheDependencyStaysOutOfTheContract:
    """The near-miss this pins.

    `Services` was first declared with `WorkflowServices` imported under
    `TYPE_CHECKING`, so the annotation was an unresolved forward reference at
    registration time. FastAPI does not treat that as an error — it takes the
    parameter for a **query parameter**. `services` would have appeared in the
    published contract as a query string on every moved route, and the failure
    mode of a refactor whose whole constraint is "the contract does not
    change" is worth a test rather than a memory.
    """

    @pytest.fixture(scope="class")
    def app_routes(self) -> list[APIRoute]:
        return api_routes(create_app())

    def test_no_route_asks_a_client_for_the_services(
        self, app_routes: list[APIRoute]
    ) -> None:
        offenders = [
            (route.path, field.name)
            for route in app_routes
            for field in (
                list(route.dependant.query_params)
                + list(route.dependant.path_params)
                + list(route.dependant.header_params)
                + list(route.dependant.cookie_params)
            )
            if field.name in {"services", "http", "request"}
        ]

        assert offenders == [], (
            "an app-assembly parameter leaked into the request contract — "
            "the annotation is probably an unresolved forward reference"
        )

    def test_every_moved_handler_actually_receives_the_services(self) -> None:
        """The other half: a dependency that resolves to `None` would make
        every handler fail at run time rather than at registration."""
        from openstategraph.api.deps import get_services

        for module in route_modules():
            for route in module.router.routes:
                if not isinstance(route, APIRoute):
                    continue
                takes = "services" in inspect.signature(route.endpoint).parameters
                if not takes:
                    continue
                sub = [d.call for d in route.dependant.dependencies]
                assert get_services in sub, f"{route.path} declares services but does not depend on it"


class TestNothingSlipsBackIntoTheFactory:
    """The rule, not just this one cleanup.

    A new route is one `@app.get` away from being a closure again, and that is
    the cheapest thing to write when you are already editing `create_app`.
    """

    def test_create_app_defines_no_route_handler(self) -> None:
        import ast
        from pathlib import Path

        source = Path(
            "backend/openstategraph/api/main.py"
        ).resolve()
        if not source.exists():  # running from the backend/ directory
            source = Path(__file__).resolve().parents[1] / "openstategraph/api/main.py"

        tree = ast.parse(source.read_text())
        factory = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_app"
        )
        nested = [
            node.name
            for node in factory.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        assert nested == [], (
            "define the handler on a router under api/routes/ and reach the app "
            "through api/deps.Services — a closure here cannot be imported or "
            "tested without building the whole application"
        )

    def test_every_route_the_app_serves_comes_from_a_router(self) -> None:
        """The other direction: the routers really are the whole surface, so
        the guard above cannot be satisfied by registering routes some third
        way."""
        from openstategraph.api.routes import __name__ as routes_package

        served = {route.path for route in api_routes(create_app())}
        assert served, "no routes found — the walk above is not seeing them"
        from_routers = {
            route.path
            for module in route_modules()
            for route in module.router.routes
            if isinstance(route, APIRoute)
        }

        assert served == from_routers, f"not served by {routes_package}"
