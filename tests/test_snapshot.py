"""The static snapshot must cover every path the dashboard requests.

The deployed demo has no backend: it serves committed captures from
``dashboard/public/snapshot/``. If the client requests a path with no corresponding
file, that panel shows an error on the live site — which is exactly what happened
with ``/api/audit``, and was only noticed by using the deployment.

This test derives the required set from the client itself, so adding a new endpoint
to the UI without exporting it fails here rather than in production.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLIENT = REPO / "dashboard" / "lib" / "cityvigil.ts"
SNAPSHOT = REPO / "dashboard" / "public" / "snapshot"

#: Values substituted into templated paths such as /api/surface/${layer}/geojson.
LAYERS = ("snapshot", "peak_hour", "exceedance", "persistence")


def _snapshot_name(path: str) -> str:
    """Mirror the mapping the client uses to turn a path into a filename."""
    return path.lstrip("/").replace("/", "_").replace("-", "_")


def _requested_paths() -> set[str]:
    """Every API path the TypeScript client calls, templates expanded."""
    source = CLIENT.read_text(encoding="utf-8")
    raw = set(re.findall(r"request<[^>]*>\(\s*[`']([^`']+)[`']", source))
    raw |= set(re.findall(r"request<[^>]*>\(\s*`([^`]+)`", source))

    expanded: set[str] = set()
    for path in raw:
        if "${layer}" in path:
            expanded |= {path.replace("${layer}", layer) for layer in LAYERS}
        elif "${" in path:
            pytest.fail(f"unhandled template in client path: {path}")
        else:
            expanded.add(path)
    return expanded


def test_client_source_is_present():
    assert CLIENT.is_file(), f"cannot find the API client at {CLIENT}"


def test_snapshot_directory_is_committed():
    """Without this the deployed demo has no data at all."""
    assert SNAPSHOT.is_dir(), "the snapshot directory must be committed"
    assert list(SNAPSHOT.glob("*.json")), "the snapshot directory is empty"


def test_every_requested_path_has_a_snapshot_file():
    """Regression: /api/audit was requested by the UI but never exported."""
    available = {p.stem for p in SNAPSHOT.glob("*.json")}
    missing = sorted(
        path for path in _requested_paths() if _snapshot_name(path) not in available
    )
    assert not missing, (
        f"the dashboard requests these paths with no snapshot file: {missing}. "
        f"Add them to EXPORTS in scripts/export_snapshot.py and re-run it."
    )


def test_snapshot_files_are_valid_json():
    for path in sorted(SNAPSHOT.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pytest.fail(f"{path.name} is not valid JSON: {exc}")


def test_manifest_lists_the_files_present():
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    on_disk = {p.name for p in SNAPSHOT.glob("*.json")}
    assert set(manifest["files"]) <= on_disk, "manifest lists files that do not exist"


def test_agent_snapshot_carries_a_usable_trace():
    """The agent panel is the primary-track deliverable; its capture must be whole."""
    payload = json.loads((SNAPSHOT / "api_agent.json").read_text(encoding="utf-8"))
    assert payload["steps"] > 0
    assert payload["recommendation"]
    assert any(s["kind"] == "decide" for s in payload["trace"])
    assert all(
        s["rationale"].strip() for s in payload["trace"] if s["kind"] == "decide"
    ), "every recorded decision must still carry its reason"


def test_audit_snapshot_records_layer_choices():
    """Captured last on purpose, so it holds the real calls rather than an empty log."""
    payload = json.loads((SNAPSHOT / "api_audit.json").read_text(encoding="utf-8"))
    assert payload["records"], "the audit capture is empty"
    assert payload["layers_used"], "no layer choices were recorded"


def test_registry_keeps_both_study_windows():
    """The 2024 window is retained on purpose: persistence is saturated in 2026.

    Dropping it would remove the only window where the total-hours versus
    unbroken-hours distinction can actually be demonstrated.
    """
    from cityvigil.cities import CITIES, PHOENIX, PHOENIX_2024

    assert PHOENIX.episode_start.startswith("2026"), "primary episode should be current-season"
    assert PHOENIX_2024.episode_start.startswith("2024")
    assert set(CITIES) == {"phoenix", "phoenix-2024"}
    # Same footprint, so the two windows are directly comparable.
    assert PHOENIX.aoi == PHOENIX_2024.aoi


def test_episode_notes_disclose_their_own_limits():
    """Each window must state what it does and does not support."""
    from cityvigil.cities import PHOENIX, PHOENIX_2024

    assert "saturated" in PHOENIX.episode_note
    assert "counterfactual" in PHOENIX_2024.episode_note
