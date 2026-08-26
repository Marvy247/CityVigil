"""Export every API response as static JSON, so the dashboard works with no backend.

    CITYVIGIL_CACHE_MODE=replay python3 scripts/export_snapshot.py

Why this exists
---------------
A hackathon demo link has to work on a stranger's machine with nothing running.
The dashboard normally talks to a local FastAPI service that holds a FortyGuard
key, and that service cannot be exposed publicly — an open instance would let
anyone spend the key's credits.

So the whole API surface is captured to static files under
``dashboard/public/snapshot/``. The client falls back to them when the live API is
unreachable, which means the deployed site is fully functional, contains no
credentials, and costs nothing to host. The trade is that snapshot responses are
fixed at the default parameters; the UI says so rather than pretending otherwise.

The API functions are called directly rather than over HTTP, so this needs no
running server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cityvigil import api  # noqa: E402

OUT = Path("dashboard/public/snapshot")

#: Filename the client looks for, and how to produce it. Keys mirror the API paths
#: with slashes replaced, so the fallback can map a request path to a file.
EXPORTS: list[tuple[str, callable]] = [
    ("health", api.health),
    ("api_cities", api.list_cities),
    ("api_layers", api.list_layers),
    ("api_sources", api.data_sources),
    ("api_tracts_summary", api.tracts_summary),
    ("api_supply", api.supply),
    (
        "api_surfaces",
        lambda: api.surfaces(
            api.SurfaceRequest(
                city="phoenix",
                layers=["snapshot", "peak_hour", "exceedance", "persistence"],
            )
        ),
    ),
    ("api_exposure", lambda: api.exposure(api.ExposureRequest(city="phoenix", limit=25))),
    (
        "api_exposure_geojson",
        lambda: api.exposure_geojson(api.ExposureRequest(city="phoenix")),
    ),
    ("api_coverage", lambda: api.coverage(api.CoverageRequest(city="phoenix", limit=15))),
    ("api_agent", lambda: api.run_agent(api.AgentRequest(city="phoenix", hour=19.0))),
    (
        "api_simulate_hours",
        lambda: api.simulate_hours(api.SimulateHoursRequest(city="phoenix")),
    ),
    (
        "api_simulate_sites",
        lambda: api.simulate_sites(api.SimulateSitesRequest(city="phoenix", budget=5)),
    ),
    # Exported last, deliberately: the audit trail accumulates as the calls above
    # run, so capturing it at the end records the real layer choices and their
    # rationales rather than an empty log.
    ("api_audit", api.audit),
]

#: Tile geometry per layer — the heavy ones, exported separately.
LAYERS = ("snapshot", "peak_hour", "exceedance", "persistence")


def write(name: str, payload: object) -> int:
    target = OUT / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), default=str)
    target.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def main() -> int:
    print(f"Exporting static snapshot to {OUT}/\n")
    total = 0
    failed: list[str] = []

    for name, produce in EXPORTS:
        try:
            size = write(name, produce())
            total += size
            print(f"  {name:<26} {size / 1024:>9,.0f} KB")
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed.append(name)
            print(f"  {name:<26} FAILED: {type(exc).__name__}: {str(exc)[:70]}")

    for layer in LAYERS:
        name = f"api_surface_{layer}_geojson"
        try:
            payload = api.surface_geojson(layer, api.SurfaceRequest(city="phoenix"))
            size = write(name, payload)
            total += size
            print(f"  {name:<26} {size / 1024:>9,.0f} KB")
        except Exception as exc:  # noqa: BLE001
            failed.append(name)
            print(f"  {name:<26} FAILED: {type(exc).__name__}: {str(exc)[:70]}")

    # Credits are a live account query and need a key, so there is nothing to
    # capture. Emit an explicit "unknown" rather than omitting the file, so the
    # client gets a well-formed answer instead of a fetch error.
    total += write(
        "api_credits",
        {
            "remaining": None,
            "credits_per_heatmap": 4220,
            "heatmaps_affordable": None,
            "note": "Credit balance is a live account query; not available in a static snapshot.",
        },
    )
    print(f"  {'api_credits':<26} {'(placeholder)':>12}")

    manifest = {
        "generated_from": "committed response cache (replay mode)",
        "note": (
            "Static capture of the CityVigil API at default parameters. The dashboard "
            "uses these when no live API is reachable, so the deployed site works "
            "without a backend and without credentials. Interactive parameter changes "
            "require running the API locally."
        ),
        "files": sorted(p.name for p in OUT.glob("*.json")),
        "bytes": total,
    }
    write("manifest", manifest)

    print(f"\n  total {total / 1e6:.1f} MB across {len(manifest['files'])} files")
    if failed:
        print(f"  FAILED: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
