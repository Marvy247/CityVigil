"""Live verification against the real FortyGuard API.

Runs all four analysis layers over a small Phoenix AOI and prints what each one
returned, the audit trail, and the credits consumed. This is the script that
proves the foundation works against production rather than against fixtures.

    python3 scripts/verify_live.py

Re-running is nearly free: responses are cached, so a second run serves from disk
and spends nothing. Use ``CITYVIGIL_CACHE_MODE=refresh`` to force live calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cityvigil import FortyGuardClient, Settings  # noqa: E402
from cityvigil.layers import ExposureLayers  # noqa: E402

# ~1.1 km² over downtown Phoenix, comfortably inside the Basic-tier area cap.
_UNUSED_SMALL_AOI = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "Phoenix downtown test AOI"},
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

# Study window comes from the city registry, so there is one source of truth for
# the episode rather than a copy that can drift out of date.
from cityvigil.cities import PHOENIX  # noqa: E402

STUDY_DAY = PHOENIX.episode_start
WINDOW_START, WINDOW_END = PHOENIX.episode_start, PHOENIX.episode_end

# 100 F. Passed in Fahrenheit deliberately, to exercise the conversion that the
# API requires (it takes Celsius) rather than hard-coding a Celsius constant.
DANGER_THRESHOLD_F = PHOENIX.danger_threshold_f


def main() -> int:
    settings = Settings.from_env()
    client = FortyGuardClient(settings)
    layers = ExposureLayers(client)

    before = client.credits_remaining()
    print(f"credits before : {before:,}" if before is not None else "credits before : unknown")
    print(f"cache mode     : {settings.cache_mode}  ({settings.cache_dir})")
    print()

    surfaces = {}

    print("[1/4] how hot is it?            -> tcm")
    surfaces["snapshot"] = layers.how_hot(
        PHOENIX.aoi, start_date=STUDY_DAY, filter_type=3, granularity=100
    )

    print("[2/4] when does it peak?        -> time_of_measure")
    surfaces["peak_hour"] = layers.when_peak(
        PHOENIX.aoi, start_date=STUDY_DAY, filter_type=3, granularity=100
    )

    print("[3/4] how long is it dangerous? -> exceedance")
    surfaces["exceedance"] = layers.how_long_dangerous(
        PHOENIX.aoi,
        threshold=DANGER_THRESHOLD_F,
        threshold_unit="F",
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        granularity=100,
    )

    print("[4/4] is there any relief?      -> persistence")
    surfaces["persistence"] = layers.any_relief(
        PHOENIX.aoi,
        threshold=DANGER_THRESHOLD_F,
        threshold_unit="F",
        start_date=WINDOW_START,
        end_date=WINDOW_END,
        granularity=100,
    )

    print("\n" + "=" * 72)
    print("SURFACES")
    print("=" * 72)
    for name, surface in surfaces.items():
        s = surface.summary()
        span = (
            f"min {s['min']:.2f}  mean {s['mean']:.2f}  max {s['max']:.2f}"
            if s["min"] is not None
            else "no values"
        )
        print(f"\n{name:<12} {s['analytic_type']:<16} units={s['units']:<9} tiles={s['n_tiles']}")
        print(f"{'':<12} {span}  [{s['units']}]")
        if s["threshold_c"] is not None:
            print(
                f"{'':<12} threshold {s['threshold_c']:.2f} C "
                f"(= {DANGER_THRESHOLD_F:.0f} F as supplied)"
            )

    # The comparison that justifies keeping both hour-based layers.
    exc, per = surfaces["exceedance"], surfaces["persistence"]
    print("\n" + "=" * 72)
    print("WHY BOTH HOUR LAYERS MATTER")
    print("=" * 72)
    print(
        f"total dangerous hours   : max {max(exc.values):.1f} h over the window\n"
        f"longest unbroken stretch: max {max(per.values):.1f} h\n"
        "Ranking on the total alone would treat a tile that cools overnight the\n"
        "same as one that never does. Persistence separates them."
    )

    print("\n" + "=" * 72)
    print("AUDIT TRAIL")
    print("=" * 72)
    print(client.audit.render_text())

    print("\n" + "=" * 72)
    print("RUN STATS")
    print("=" * 72)
    print(json.dumps(client.run_stats(), indent=2))

    after = client.credits_remaining()
    if before is not None and after is not None:
        print(f"\ncredits after  : {after:,}   (spent {before - after:,})")

    out = Path("outputs")
    client.write_audit(out / "verify_live_audit.json")
    for name, surface in surfaces.items():
        target = out / f"phoenix_{name}.geojson"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(surface.to_geojson()), encoding="utf-8")
    print(f"wrote audit + {len(surfaces)} GeoJSON exports to {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
