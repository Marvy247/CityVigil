"""Cache behaviour — the basis of offline, credit-free replay."""

from __future__ import annotations

import json

import pytest

from cityvigil.cache import ResponseCache, canonical_digest
from cityvigil.errors import CacheMiss, ConfigError


def test_digest_is_order_independent():
    """A payload rebuilt in a different field order must hit the same entry."""
    a = canonical_digest("/v1/heatmap", {"granularity": 100, "analytic_type": "tcm"})
    b = canonical_digest("/v1/heatmap", {"analytic_type": "tcm", "granularity": 100})
    assert a == b


def test_digest_changes_with_the_question():
    base = {"analytic_type": "tcm", "granularity": 100}
    changed = {"analytic_type": "exceedance", "granularity": 100}
    assert canonical_digest("/v1/heatmap", base) != canonical_digest("/v1/heatmap", changed)


def test_digest_changes_with_endpoint():
    payload = {"a": 1}
    assert canonical_digest("/v1/heatmap", payload) != canonical_digest("/v1/env_params", payload)


def test_put_then_get_roundtrip(tmp_path):
    cache = ResponseCache(tmp_path, "live")
    payload = {"analytic_type": "tcm"}
    assert cache.get("/v1/heatmap", payload) is None
    cache.put("/v1/heatmap", payload, {"map_data": {"features": []}})
    assert cache.get("/v1/heatmap", payload) == {"map_data": {"features": []}}
    assert cache.hits == 1 and cache.writes == 1


def test_entry_stores_the_payload_for_review(tmp_path):
    """An opaque hash file is useless in review; the question must be legible."""
    import gzip

    cache = ResponseCache(tmp_path, "live")
    payload = {"analytic_type": "exceedance", "threshold": 35.0}
    path = cache.put("/v1/heatmap", payload, {"ok": True})
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        entry = json.load(fh)
    assert entry["payload"] == payload
    assert entry["endpoint"] == "/v1/heatmap"
    assert "cached_at" in entry


def test_entries_are_gzipped(tmp_path):
    """A committed cache of city-scale responses is only clonable compressed."""
    cache = ResponseCache(tmp_path, "live")
    path = cache.put("/v1/heatmap", {"a": 1}, {"features": [{"v": 1}] * 500})
    assert path.suffix == ".gz"
    assert path.read_bytes()[:2] == b"\x1f\x8b"  # gzip magic


def test_compression_actually_shrinks_payloads(tmp_path):
    """Repeated coordinate-like JSON should compress by a large factor."""
    cache = ResponseCache(tmp_path, "live")
    response = {
        "features": [
            {"geometry": {"coordinates": [[-112.130320, 33.399705]] * 5}, "value": 81.167}
            for _ in range(400)
        ]
    }
    path = cache.put("/v1/heatmap", {"a": 1}, response)
    raw = len(json.dumps(response).encode())
    assert path.stat().st_size < raw / 5, "expected better than 5x compression"


def test_plain_json_entries_are_still_readable(tmp_path):
    """Backwards compatibility with caches written before compression."""
    cache = ResponseCache(tmp_path, "live")
    legacy = cache._legacy_path_for("/v1/heatmap", {"a": 1})
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"response": {"from": "legacy"}}), encoding="utf-8")
    assert cache.get("/v1/heatmap", {"a": 1}) == {"from": "legacy"}


def test_entries_are_namespaced_by_endpoint(tmp_path):
    cache = ResponseCache(tmp_path, "live")
    p = cache.path_for("/v1/heatmap", {"a": 1})
    assert p.parent.name == "v1_heatmap"


def test_replay_mode_raises_on_miss(tmp_path):
    cache = ResponseCache(tmp_path, "replay")
    with pytest.raises(CacheMiss, match="replay mode"):
        cache.get("/v1/heatmap", {"analytic_type": "tcm"})


def test_replay_mode_serves_committed_entries(tmp_path):
    ResponseCache(tmp_path, "live").put("/v1/heatmap", {"a": 1}, {"result": "cached"})
    assert ResponseCache(tmp_path, "replay").get("/v1/heatmap", {"a": 1}) == {"result": "cached"}


def test_refresh_mode_ignores_existing_entries(tmp_path):
    ResponseCache(tmp_path, "live").put("/v1/heatmap", {"a": 1}, {"result": "stale"})
    assert ResponseCache(tmp_path, "refresh").get("/v1/heatmap", {"a": 1}) is None


def test_invalid_mode_rejected(tmp_path):
    with pytest.raises(ConfigError, match="cache mode"):
        ResponseCache(tmp_path, "sometimes")  # type: ignore[arg-type]


def test_corrupt_entry_reported_clearly(tmp_path):
    cache = ResponseCache(tmp_path, "live")
    path = cache.path_for("/v1/heatmap", {"a": 1})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not gzip at all")
    with pytest.raises(ConfigError, match="corrupt cache entry"):
        cache.get("/v1/heatmap", {"a": 1})


def test_no_temp_files_left_behind(tmp_path):
    """Writes are atomic, so a crash cannot leave a half-written entry."""
    cache = ResponseCache(tmp_path, "live")
    cache.put("/v1/heatmap", {"a": 1}, {"ok": True})
    assert list(tmp_path.rglob("*.tmp")) == []


def test_stats_report_counters(tmp_path):
    cache = ResponseCache(tmp_path, "live")
    cache.get("/v1/heatmap", {"a": 1})
    cache.put("/v1/heatmap", {"a": 1}, {"ok": True})
    cache.get("/v1/heatmap", {"a": 1})
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1 and stats["writes"] == 1
    assert stats["mode"] == "live"
