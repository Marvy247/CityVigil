"""Import-time and wiring checks for the HTTP service.

Nothing else in the suite imports :mod:`cityvigil.api`, so a module-level mistake
there — a missing import, a typo in a decorator — could reach a commit undetected.
That happened once: ``os.getenv`` was used in the CORS setup without importing
``os``, and the service failed at startup while every unit test still passed. These
tests close that gap cheaply.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(scope="module")
def api():
    """Import the API module fresh. Fails loudly on any module-level error."""
    return importlib.import_module("cityvigil.api")


def test_module_imports_without_error(api):
    """Regression: a NameError at import time took the whole service down."""
    assert api.app is not None


def test_every_expected_route_is_registered(api):
    paths = {getattr(r, "path", None) for r in api.app.routes}
    expected = {
        "/health",
        "/api/cities",
        "/api/layers",
        "/api/credits",
        "/api/sources",
        "/api/tracts/summary",
        "/api/supply",
        "/api/surfaces",
        "/api/surface/{layer}/geojson",
        "/api/exposure",
        "/api/exposure/geojson",
        "/api/coverage",
        "/api/simulate/hours",
        "/api/simulate/sites",
        "/api/agent",
        "/api/audit",
    }
    missing = expected - paths
    assert not missing, f"routes missing from the app: {sorted(missing)}"


def test_cors_allows_the_dev_dashboard_and_no_wildcard(api):
    """A wildcard on a service that can hold an API key would be a credential leak."""
    assert "http://localhost:3000" in api._default_origins
    assert "*" not in api._default_origins


def test_cors_extra_origins_come_from_the_environment(monkeypatch):
    """Deployed origins are added by configuration, not by widening the default."""
    monkeypatch.setenv("CITYVIGIL_ALLOWED_ORIGINS", "https://a.example, https://b.example")
    module = importlib.reload(importlib.import_module("cityvigil.api"))
    try:
        assert "https://a.example" in module._extra_origins
        assert "https://b.example" in module._extra_origins
    finally:
        monkeypatch.delenv("CITYVIGIL_ALLOWED_ORIGINS", raising=False)
        importlib.reload(module)


def test_request_models_have_usable_defaults(api):
    """The snapshot exporter and the UI both rely on these defaulting cleanly."""
    assert api.SurfaceRequest().city == "phoenix"
    assert api.ExposureRequest().limit > 0
    assert api.CoverageRequest().walkable_km > 0
    assert api.SimulateHoursRequest().uptake == 1.0
    assert api.SimulateSitesRequest().budget >= 1
    assert api.AgentRequest().hour == 19.0


def test_layer_metadata_covers_every_ui_layer(api):
    assert set(api.LAYER_META) == {"snapshot", "peak_hour", "exceedance", "persistence"}
    for key, meta in api.LAYER_META.items():
        assert meta["analytic_type"], key
        assert meta["question"], key


def test_peak_hour_carries_the_timezone_caveat(api):
    """The layer whose timezone is unresolved must say so through the API."""
    assert "note" in api.LAYER_META["peak_hour"]
    assert "local" in api.LAYER_META["peak_hour"]["note"].lower()
