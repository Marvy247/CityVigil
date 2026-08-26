"""Client behaviour: submit-and-poll, retries, caching, guard integration."""

from __future__ import annotations

import pytest

from cityvigil.errors import (
    APIError,
    CacheMiss,
    TaskFailed,
    TaskTimeout,
    ValidationError,
)
from conftest import FakeResponse, FakeSession, scripted_api


# ------------------------------------------------------------- happy path


def test_heatmap_submits_polls_and_returns_result(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    result = client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, analytic_type="tcm"
    )
    assert result == tcm_result

    methods = [m for m, _, _ in client._session.calls]
    assert methods[0] == "POST"
    assert "GET" in methods


def test_tolerates_404_window_after_submit(make_client, phoenix_aoi, tcm_result):
    """The status endpoint 404s briefly after submission; that is not a failure."""
    client = make_client(scripted_api(tcm_result, not_ready_times=2))
    result = client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0
    )
    assert result == tcm_result


def test_polls_through_processing_states(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result, processing_times=3))
    result = client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0
    )
    assert result == tcm_result


# ------------------------------------------------------------------ failures


def test_task_failure_raises(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result, fail=True))
    with pytest.raises(TaskFailed, match="boom"):
        client.create_heatmap(
            phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0
        )


def test_timeout_raises_with_last_status(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result, processing_times=10_000))
    with pytest.raises(TaskTimeout) as exc:
        client.create_heatmap(
            phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0, timeout=0.05
        )
    assert exc.value.last_status == "processing"


def test_bad_submit_status_raises_api_error(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result, submit_status=400), max_retries=1)
    with pytest.raises(APIError, match="400"):
        client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3)


def test_retries_transient_5xx_then_succeeds(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result, submit_failures=2), max_retries=3)
    result = client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0
    )
    assert result == tcm_result
    assert len([m for m, _, _ in client._session.calls if m == "POST"]) == 3


def test_error_envelope_is_surfaced(make_client, phoenix_aoi):
    def handler(method, url, kwargs):
        return FakeResponse(200, {"error": True, "message": "quota exceeded"})

    client = make_client(handler)
    with pytest.raises(APIError, match="quota exceeded"):
        client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3)


# -------------------------------------------------------------------- guards


def test_guard_rejection_happens_before_any_http_call(make_client, dubai_aoi, tcm_result):
    """Non-US AOI must cost zero requests and zero credits."""
    client = make_client(scripted_api(tcm_result))
    with pytest.raises(ValidationError, match="United States only"):
        client.create_heatmap(dubai_aoi, start_date="2024-07-15", filter_type=3)
    assert client._session.calls == []


def test_guard_rejection_is_audited(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    with pytest.raises(ValidationError):
        client.create_heatmap(
            phoenix_aoi, start_date="2024-07-15", filter_type=3, analytic_type="exceedance"
        )
    rejections = client.audit.of_kind("guard_rejection")
    assert len(rejections) == 1
    assert rejections[0].detail["field"] == "threshold"


def test_fahrenheit_threshold_reaches_api_as_celsius(make_client, phoenix_aoi, exceedance_result):
    """A 100 F threshold must be sent as 37.78 C, not 100."""
    client = make_client(scripted_api(exceedance_result))
    client.create_heatmap(
        phoenix_aoi,
        start_date="2024-07-15",
        end_date="2024-07-21",
        filter_type=4,
        analytic_type="exceedance",
        threshold=100.0,
        threshold_unit="F",
        direction="above",
        poll_interval=0.0,
    )
    post = next(kw for m, _, kw in client._session.calls if m == "POST")
    assert post["json"]["threshold"] == pytest.approx(37.7778, abs=1e-3)


def test_invalid_analytic_type_rejected(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    with pytest.raises(ValidationError, match="analytic_type"):
        client.create_heatmap(
            phoenix_aoi, start_date="2024-07-15", filter_type=3, analytic_type="nonsense"
        )


# --------------------------------------------------------------------- cache


def test_second_identical_call_is_served_from_cache(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    kwargs = dict(start_date="2024-07-15", filter_type=3, poll_interval=0.0)

    client.create_heatmap(phoenix_aoi, **kwargs)
    calls_after_first = len(client._session.calls)
    result = client.create_heatmap(phoenix_aoi, **kwargs)

    assert result == tcm_result
    assert len(client._session.calls) == calls_after_first, "cache hit must not call the API"
    assert client.cache.hits == 1


def test_changing_the_question_bypasses_the_cache(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, granularity=100, poll_interval=0.0
    )
    posts_before = len([m for m, _, _ in client._session.calls if m == "POST"])
    client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, granularity=60, poll_interval=0.0
    )
    posts_after = len([m for m, _, _ in client._session.calls if m == "POST"])
    assert posts_after == posts_before + 1


def test_labelled_aoi_reuses_the_cache(make_client, phoenix_aoi, tcm_result):
    """Regression: a `name` property on the AOI once cost a duplicate 4,220 credits."""
    client = make_client(scripted_api(tcm_result))
    kwargs = dict(start_date="2024-07-15", filter_type=3, poll_interval=0.0)

    client.create_heatmap(phoenix_aoi, **kwargs)
    posts_before = len([m for m, _, _ in client._session.calls if m == "POST"])

    labelled = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Central Phoenix"},
                "geometry": phoenix_aoi["features"][0]["geometry"],
            }
        ],
    }
    client.create_heatmap(labelled, **kwargs)

    posts_after = len([m for m, _, _ in client._session.calls if m == "POST"])
    assert posts_after == posts_before, "labelled AOI must hit the cache, not re-spend"
    assert client.cache.hits == 1


def test_payload_sent_is_canonicalised(make_client, phoenix_aoi, tcm_result):
    """The AOI on the wire carries no cosmetic properties."""
    client = make_client(scripted_api(tcm_result))
    labelled = {
        "type": "Feature",
        "properties": {"name": "x"},
        "geometry": phoenix_aoi["features"][0]["geometry"],
    }
    client.create_heatmap(labelled, start_date="2024-07-15", filter_type=3, poll_interval=0.0)
    post = next(kw for m, _, kw in client._session.calls if m == "POST")
    aoi = post["json"]["polygon_aoi"]
    assert aoi["type"] == "FeatureCollection"
    assert aoi["features"][0]["properties"] == {}


def test_replay_mode_needs_no_api_key(settings, tmp_path, phoenix_aoi, tcm_result):
    """Judges must be able to run everything with no key at all."""
    from cityvigil.audit import AuditLog
    from cityvigil.cache import ResponseCache
    from cityvigil.config import Settings
    from cityvigil.fg_client import FortyGuardClient

    cache_dir = tmp_path / "replay-cache"
    seeded = Settings(
        api_key="k", base_url=settings.base_url, cache_dir=cache_dir, cache_mode="live"
    )
    warm = FortyGuardClient(
        seeded,
        audit=AuditLog(),
        cache=ResponseCache(cache_dir, "live"),
        session=FakeSession(scripted_api(tcm_result)),
    )
    warm.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0)

    keyless = Settings(
        api_key=None, base_url=settings.base_url, cache_dir=cache_dir, cache_mode="replay"
    )
    replay = FortyGuardClient(
        keyless,
        audit=AuditLog(),
        cache=ResponseCache(cache_dir, "replay"),
        session=FakeSession(scripted_api(tcm_result)),
    )
    assert replay.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3
    ) == tcm_result
    assert replay._session.calls == []


def test_replay_mode_miss_is_explicit(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result), mode="replay")
    with pytest.raises(CacheMiss, match="no cached response"):
        client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3)


# --------------------------------------------------------------------- audit


def test_every_call_is_audited_with_provenance(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    client.create_heatmap(
        phoenix_aoi, start_date="2024-07-15", filter_type=3, granularity=80, poll_interval=0.0
    )
    calls = client.audit.of_kind("api_call")
    assert len(calls) == 1
    detail = calls[0].detail
    assert detail["endpoint"] == "/v1/heatmap"
    assert detail["analytic_type"] == "tcm"
    assert detail["cached"] is False
    assert detail["activity_id"] == "act-123"
    assert detail["granularity_m"] == 80
    assert detail["aoi_region"] == "conus"
    assert detail["payload_digest"]


def test_run_stats_tally_endpoints_and_layers(make_client, phoenix_aoi, tcm_result):
    client = make_client(scripted_api(tcm_result))
    client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0)
    stats = client.run_stats()
    assert stats["endpoints_used"] == {"/v1/heatmap": 1}
    assert stats["layers_used"] == {"tcm": 1}


def test_audit_can_be_written_to_disk(make_client, phoenix_aoi, tcm_result, tmp_path):
    client = make_client(scripted_api(tcm_result))
    client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0)
    path = client.write_audit(tmp_path / "audit.json")
    assert path.is_file()
    import json

    written = json.loads(path.read_text())
    assert written["endpoints_used"] == {"/v1/heatmap": 1}


def test_injected_empty_audit_log_is_used(settings, phoenix_aoi, tcm_result, tmp_path):
    """Regression: AuditLog implements __len__, so an empty one is falsy.

    `self.audit = audit or AuditLog()` silently replaced the caller's log with a
    fresh one, leaving the API's /api/audit endpoint reading an orphan that never
    received any records.
    """
    from cityvigil.audit import AuditLog
    from cityvigil.cache import ResponseCache
    from cityvigil.config import Settings
    from cityvigil.fg_client import FortyGuardClient

    shared = AuditLog()
    assert len(shared) == 0 and not shared, "precondition: an empty log is falsy"

    cfg = Settings(
        api_key="k", base_url=settings.base_url, cache_dir=tmp_path / "c", cache_mode="live"
    )
    client = FortyGuardClient(
        cfg,
        audit=shared,
        cache=ResponseCache(tmp_path / "c", "live"),
        session=FakeSession(scripted_api(tcm_result)),
    )
    assert client.audit is shared

    client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0)
    assert len(shared) > 0, "records must land in the injected log"
    assert shared.endpoints_used() == {"/v1/heatmap": 1}


def test_injected_empty_cache_is_used(settings, phoenix_aoi, tcm_result, tmp_path):
    """Same truthiness trap guarded for the cache."""
    from cityvigil.audit import AuditLog
    from cityvigil.cache import ResponseCache
    from cityvigil.config import Settings
    from cityvigil.fg_client import FortyGuardClient

    shared_cache = ResponseCache(tmp_path / "explicit", "live")
    cfg = Settings(
        api_key="k", base_url=settings.base_url, cache_dir=tmp_path / "other", cache_mode="live"
    )
    client = FortyGuardClient(
        cfg,
        audit=AuditLog(),
        cache=shared_cache,
        session=FakeSession(scripted_api(tcm_result)),
    )
    assert client.cache is shared_cache
    client.create_heatmap(phoenix_aoi, start_date="2024-07-15", filter_type=3, poll_interval=0.0)
    assert shared_cache.writes == 1
