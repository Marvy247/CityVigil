"""Does CityVigil's ranking predict where people actually died of heat?

    python3 scripts/validate.py            # live, ~28 heatmap calls first run
    CITYVIGIL_CACHE_MODE=replay python3 scripts/validate.py   # offline afterwards

Tests the tract ranking against Maricopa County's recorded heat-associated deaths
by ZIP code for 2022, using July 2022 exposure. The headline question is not
whether the model scores well in absolute terms — it is whether the vulnerability
weighting beats heat exposure alone, which is the free baseline.

The result is reported whichever way it falls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cityvigil import FortyGuardClient, Settings  # noqa: E402
from cityvigil.exposure import build_exposure_report  # noqa: E402
from cityvigil.geometry import bbox_union  # noqa: E402
from cityvigil.guards import bbox_area_km2, tile_bbox  # noqa: E402
from cityvigil.layers import ExposureLayers, HeatSurface, Tile  # noqa: E402
from cityvigil.tracts import load_tracts  # noqa: E402
from cityvigil.validation import (  # noqa: E402
    aggregate_to_zips,
    load_zip_outcomes,
    outcome_summary,
    validate,
    zip_index,
)
from cityvigil.vulnerability import VulnerabilityModel  # noqa: E402

RULE = "=" * 78

# July 2022: the peak heat month, and within the API's measured 31-day range limit.
# Deaths accrue across the whole May-September season, so this is exposure during
# the worst month rather than the whole season — a stated simplification.
WINDOW_START, WINDOW_END = "2022-07-01", "2022-07-31"
THRESHOLD_F = 100.0


def main() -> int:
    settings = Settings.from_env()
    client = FortyGuardClient(settings)
    layers = ExposureLayers(client)

    print(RULE)
    print("CityVigil — validation against recorded heat deaths")
    print(RULE)
    print(f"exposure window : {WINDOW_START} to {WINDOW_END} (peak heat month)")
    print(f"threshold       : {THRESHOLD_F:.0f} F")
    print(f"outcome         : Maricopa County heat-associated deaths by ZIP, 2022")
    print(f"cache mode      : {settings.cache_mode}")
    print()

    outcomes = load_zip_outcomes(download=True)
    summary = outcome_summary(outcomes)
    print(RULE)
    print("OUTCOME DATA")
    print(RULE)
    print(f"ZIP codes                    : {summary['n_zips']}")
    print(f"  published counts           : {summary['n_published']}")
    print(f"  suppressed (below threshold): {summary['n_suppressed']}")
    print(f"  labelled high-mortality    : {summary['n_high_mortality']}")
    print(f"published deaths total       : {summary['published_deaths_total']}")
    print(f"published range              : {summary['min_published']} to {summary['max_published']}")
    print(f"\n  {summary['censoring_note']}")

    # --- study region: the extent of ZIPs with published counts --------------
    published = [o for o in outcomes.values() if not o.suppressed]
    region = bbox_union(o.geometry.bbox for o in published)
    tiles = tile_bbox(region)

    # `--tiles N` runs a subset, for checking the pipeline before committing to the
    # full region. A subset covers less ground, so its numbers are not comparable.
    limit = None
    if "--tiles" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--tiles") + 1])
        tiles = tiles[:limit]

    print()
    print(RULE)
    print("STUDY REGION")
    print(RULE)
    print(f"bbox           : {[round(v, 3) for v in region]}")
    print(f"area           : {bbox_area_km2(region):,.0f} km²")
    print(f"AOI tiles      : {len(tiles)} (heatmaps cost a flat 4,220 credits each)")
    print(f"credits if live: {len(tiles) * 4220:,}")
    if limit is not None:
        print(f"  SUBSET RUN: limited to {limit} tiles — results are not representative")

    before = client.credits_remaining()
    if before is not None:
        print(f"credits now    : {before:,}")

    # --- fetch exposure across the region -----------------------------------
    print(f"\nFetching July 2022 exceedance for {len(tiles)} tiles…")
    all_tiles: list[Tile] = []
    offset = 0
    for n, aoi in enumerate(tiles, start=1):
        surface = layers.how_long_dangerous(
            aoi,
            threshold=THRESHOLD_F,
            threshold_unit="F",
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            granularity=100,
        )
        # Tile ids restart per AOI, so re-key them to keep the combined set unique.
        for tile in surface.tiles:
            all_tiles.append(
                Tile(
                    tile_id=offset + tile.tile_id,
                    geometry=tile.geometry,
                    value=tile.value,
                )
            )
        offset += len(surface.tiles) + 1
        print(f"  [{n}/{len(tiles)}] {len(surface.tiles):>6,} tiles  "
              f"mean {sum(t.value for t in surface.tiles) / len(surface.tiles):>6.1f} h")

    combined = HeatSurface(
        analytic_type="exceedance",
        units="hour",
        tiles=all_tiles,
        threshold_c=(THRESHOLD_F - 32.0) * 5.0 / 9.0,
        window={"start_date": WINDOW_START, "end_date": WINDOW_END, "filter_type": 4},
        rationale="Cumulative dangerous hours during the peak heat month of 2022.",
    )
    print(f"\ncombined surface: {len(combined):,} tiles")

    # --- join to tracts, then to ZIPs ---------------------------------------
    tracts = load_tracts(download=True)
    model = VulnerabilityModel(tracts)
    print("Joining tiles to tracts…")
    report = build_exposure_report(combined, tracts, model)
    totals = report.totals()
    print(
        f"  {totals['n_tracts']} tracts, {totals['population']:,} residents, "
        f"{totals['tiles_unmatched']:,} tiles outside the county"
    )

    print("Aggregating tracts to ZIP codes…")
    zip_scores = aggregate_to_zips(report.tracts, outcomes, index=zip_index(outcomes))
    print(f"  {len(zip_scores)} ZIPs with at least one tract")

    result = validate(zip_scores, top_k=10)

    print()
    print(RULE)
    print("DISCRIMINATION — DOES THE RANKING FIND THE HIGH-MORTALITY ZIPS?")
    print(RULE)
    print(f"ZIPs scored          : {result.n_zips}")
    print(f"high-mortality ZIPs  : {result.n_high_mortality}")
    print()
    print(f"{'ranking by':<26}{'AUC':>8}{'precision@10':>15}")
    print("-" * 49)
    labels = {
        "weighted_person_hours": "vulnerability-weighted",
        "person_hours": "person-hours (heat×pop)",
        "mean_exceedance_h": "heat exposure alone",
        "population": "population alone",
    }
    for key, label in labels.items():
        m = result.metrics[key]
        a = m["auc"]
        p = m["precision_at_10"]
        print(
            f"{label:<26}{(f'{a:.3f}' if a is not None else 'n/a'):>8}"
            f"{(f'{p:.2f}' if p is not None else 'n/a'):>15}"
        )

    print()
    print(RULE)
    print("VERDICT")
    print(RULE)
    print(f"  {result.verdict}")
    print("\n  0.5 AUC is a coin flip. The comparison that matters is the weighted")
    print("  model against heat exposure alone, because heat alone is free.")

    print()
    print(RULE)
    print("LIMITATIONS OF THIS TEST")
    print(RULE)
    for line in result.to_dict()["limitations"]:
        print(f"  - {line}")

    print()
    print(RULE)
    print("TOP 10 ZIPS BY THE WEIGHTED MODEL")
    print(RULE)
    print(f"{'zip':<8}{'pop':>9}{'meanH':>8}{'weighted p-h':>15}{'deaths':>9}{'label':>7}")
    print("-" * 56)
    for s in sorted(zip_scores, key=lambda z: -z.weighted_person_hours)[:10]:
        deaths = "<6" if s.deaths is None else str(s.deaths)
        print(
            f"{s.zip_code:<8}{s.population:>9,}{s.mean_exceedance_h:>8.1f}"
            f"{s.weighted_person_hours:>15,.0f}{deaths:>9}"
            f"{('HIGH' if s.high_mortality else '-'):>7}"
        )

    after = client.credits_remaining()
    if before is not None and after is not None:
        print(f"\ncredits spent this run: {before - after:,} (remaining {after:,})")

    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    client.write_audit(out / "validation_audit.json")
    print("Wrote outputs/validation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
