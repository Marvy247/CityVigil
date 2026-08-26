"""Shared fixtures.

The fake transport mimics behaviour observed against the live API, including the
404 window immediately after submission, so the retry and polling logic is
exercised without a network or credits.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from cityvigil.audit import AuditLog
from cityvigil.cache import ResponseCache
from cityvigil.config import Settings
from cityvigil.fg_client import FortyGuardClient


class FakeResponse:
    """Minimal stand-in for :class:`requests.Response`."""

    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeSession:
    """Scriptable session. ``handler(method, url, kwargs)`` returns a FakeResponse."""

    def __init__(self, handler: Callable[[str, str, dict], FakeResponse]) -> None:
        self.headers: dict[str, str] = {}
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)


def scripted_api(
    result: dict,
    *,
    not_ready_times: int = 0,
    fail: bool = False,
    processing_times: int = 0,
    submit_status: int = 200,
    submit_failures: int = 0,
) -> Callable[[str, str, dict], FakeResponse]:
    """Build a handler that emulates submit-then-poll.

    ``not_ready_times`` 404s on the status endpoint before responding, mimicking
    eventual consistency. ``submit_failures`` returns 503 on POST that many times
    to exercise retry/backoff.
    """
    state = {"not_ready": not_ready_times, "processing": processing_times, "posts": 0}

    def handler(method: str, url: str, kwargs: dict) -> FakeResponse:
        if method == "POST" and "/v1/status/" not in url:
            state["posts"] += 1
            if state["posts"] <= submit_failures:
                return FakeResponse(503, text="upstream busy")
            if submit_status != 200:
                return FakeResponse(submit_status, text="bad request")
            return FakeResponse(200, {"error": False, "data": {"activity_id": "act-123"}})

        if method == "GET" and "/v1/status/" in url:
            if state["not_ready"] > 0:
                state["not_ready"] -= 1
                return FakeResponse(404, text="not found")
            if fail:
                return FakeResponse(
                    200, {"error": False, "data": {"status": "Failed", "message": "boom"}}
                )
            if state["processing"] > 0:
                state["processing"] -= 1
                return FakeResponse(200, {"error": False, "data": {"status": "Processing"}})
            return FakeResponse(
                200, {"error": False, "data": {"status": "Completed", "result": result}}
            )

        return FakeResponse(404, text=f"unexpected {method} {url}")

    return handler


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def phoenix_aoi() -> dict:
    """~1.1 km² AOI over downtown Phoenix — the same footprint used live."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-112.0800, 33.4430],
                            [-112.0680, 33.4430],
                            [-112.0680, 33.4530],
                            [-112.0800, 33.4530],
                            [-112.0800, 33.4430],
                        ]
                    ],
                },
            }
        ],
    }


@pytest.fixture
def dubai_aoi() -> dict:
    """Outside US coverage — must be rejected before any credits are spent."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [55.2700, 25.1900],
                [55.2900, 25.1900],
                [55.2900, 25.2100],
                [55.2700, 25.2100],
                [55.2700, 25.1900],
            ]
        ],
    }


def _square(i: int) -> dict:
    """A tiny square polygon, offset so tiles do not overlap."""
    lon = -112.080 + i * 0.001
    lat = 33.443 + i * 0.001
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + 0.001, lat],
                [lon + 0.001, lat + 0.001],
                [lon, lat + 0.001],
                [lon, lat],
            ]
        ],
    }


@pytest.fixture
def tcm_result() -> dict:
    """A tcm payload using the real Celsius magnitudes returned for Phoenix."""
    tiles = [
        (0, 35.9436, 29.16, 40.49),
        (1, 36.1772, 29.44, 40.51),
        (2, 35.8874, 28.97, 40.12),
    ]
    return {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": str(tid),
                    "type": "Feature",
                    "properties": {
                        "tile_id": tid,
                        "average_temperature": avg,
                        "min_temperature": lo,
                        "max_temperature": hi,
                    },
                    "geometry": _square(tid),
                }
                for tid, avg, lo, hi in tiles
            ],
        },
        "stats_data": {
            "temperature_stats": {
                "minimum": 35.8874,
                "maximum": 36.1772,
                "mean": 36.0028,
                "standard_deviation": 0.0767,
            }
        },
    }


@pytest.fixture
def exceedance_result() -> dict:
    """An exceedance payload: per-tile hour counts, units 'hour'."""
    values = [(0, 40.5626), (1, 25.5136), (2, 33.9012)]
    return {
        "map_data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": str(tid),
                    "type": "Feature",
                    "properties": {"tile_id": tid, "value": val},
                    "geometry": _square(tid),
                }
                for tid, val in values
            ],
        },
        "stats_data": {
            "activity_id": "act-123",
            "analytic_type": "exceedance",
            "units": "hour",
            "n_cells": 3,
            "min": 25.5136,
            "max": 40.5626,
            "mean": 33.3258,
        },
    }


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        api_key="test-key",
        base_url="https://api.example.test",
        cache_dir=tmp_path / "cache",
        cache_mode="live",
        plan="hackathon",
        timeout=5.0,
    )


@pytest.fixture
def make_client(settings):
    """Factory returning a client wired to a fake transport."""

    def _make(handler, *, mode: str = "live", max_retries: int = 3) -> FortyGuardClient:
        cfg = Settings(
            api_key=settings.api_key,
            base_url=settings.base_url,
            cache_dir=settings.cache_dir,
            cache_mode=mode,  # type: ignore[arg-type]
            plan=settings.plan,
            timeout=settings.timeout,
        )
        return FortyGuardClient(
            cfg,
            audit=AuditLog(),
            cache=ResponseCache(cfg.cache_dir, mode),  # type: ignore[arg-type]
            session=FakeSession(handler),
            max_retries=max_retries,
        )

    return _make
