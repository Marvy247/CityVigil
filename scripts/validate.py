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
import time
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
    study_region,
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
WINDOW_START, WINDOW_END = "2023-07-01", "2023-07-31"
THRESHOLD_F = 100.0

#: 2023 is used because its counts are uncensored, unlike the 2022 release.
OUTCOME_YEAR = 2023

#: Share of recorded deaths the study region must cover. 0.6 gives 24 AOI tiles
#: over the urban core; 0.8 would give 72 and add mostly empty land.
REGION_COVERAGE = 0.6


def main() -> int:
    settings = Settings.from_env()
    client = FortyGuardClient(settings)
    layers = ExposureLayers(client)

    print(RULE)
    print("CityVigil — validation against recorded heat deaths")
    print(RULE)
    print(f"exposure window : {WINDOW_START} to {WINDOW_END} (peak heat month)")
    print(f"threshold       : {THRESHOLD_F:.0f} F")
    print(f"outcome         : Maricopa County heat deaths by ZIP, {OUTCOME_YEAR} (uncensored)")
    print(f"cache mode      : {settings.cache_mode}")
    print()

    outcomes = load_zip_outcomes(download=True, year=OUTCOME_YEAR)
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
    # Region is chosen to cover most of the recorded mortality without paying for
    # empty desert. With an uncensored release, every ZIP in the county carries a
    # value, so the bbox of "all published" is the whole 36,433 km2 county: 330
    # tiles and 1.39M credits. See validation.study_region.
    region, defining = study_region(outcomes, coverage=REGION_COVERAGE)
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
    print(f"region covers  : {REGION_COVERAGE:.0%} of recorded deaths, from {len(defining)} ZIPs")
    if limit is not None:
        print(f"  SUBSET RUN: limited to {limit} tiles — results are not representative")

    before = client.credits_remaining()
    if before is not None:
        print(f"credits now    : {before:,}")

    # --- fetch exposure across the region -----------------------------------
    print(f"\nFetching July {OUTCOME_YEAR} exceedance for {len(tiles)} tiles…")
    all_tiles: list[Tile] = []
    offset = 0
    skipped: list[int] = []

    for n, aoi in enumerate(tiles, start=1):
        # A transient 500 killed an earlier 24-tile run on its first tile: the
        # client's three fast retries all landed inside the same server hiccup.
        # Retry here with much longer gaps, and skip a tile that stays broken rather
        # than discarding the whole run. Failed tasks cost no credits.
        surface = None
        for attempt, pause in enumerate((0, 45, 120), start=1):
            if pause:
                print(f"      retrying tile {n} in {pause}s (attempt {attempt})")
                time.sleep(pause)
            try:
                surface = layers.how_long_dangerous(
                    aoi,
                    threshold=THRESHOLD_F,
                    threshold_unit="F",
                    start_date=WINDOW_START,
                    end_date=WINDOW_END,
                    granularity=100,
                )
                break
            except Exception as exc:  # noqa: BLE001 - transient upstream failure
                print(f"      tile {n} attempt {attempt} failed: {type(exc).__name__}")

        if surface is None:
            skipped.append(n)
            print(f"  [{n}/{len(tiles)}] SKIPPED after 3 attempts")
            continue

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
        print(
            f"  [{n}/{len(tiles)}] {len(surface.tiles):>6,} tiles  "
            f"mean {sum(t.value for t in surface.tiles) / len(surface.tiles):>6.1f} h"
        )

    if skipped:
        print(f"\n  WARNING: {len(skipped)} of {len(tiles)} tiles unavailable: {skipped}")
        print("  Those areas are absent from the analysis and the ZIP coverage below.")
    if not all_tiles:
        print("\nNo tiles retrieved; cannot validate.")
        return 1

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
    print(f"{'ranking by':<26}{'AUC':>8}{'95% CI':>18}{'rho vs counts':>15}{'P@10':>7}")
    print("-" * 74)
    labels = {
        "weighted_person_hours": "vulnerability-weighted",
        "person_hours": "person-hours (heat×pop)",
        "mean_exceedance_h": "heat exposure alone",
        "population": "population alone",
    }
    for key, label in labels.items():
        m = result.metrics[key]
        a, p = m["auc"], m["precision_at_10"]
        lo, hi = m.get("auc_ci_low"), m.get("auc_ci_high")
        rho = m.get("spearman_vs_counts")
        ci = f"{lo:.3f}-{hi:.3f}" if lo is not None and hi is not None else "n/a"
        print(
            f"{label:<26}{(f'{a:.3f}' if a is not None else 'n/a'):>8}{ci:>18}"
            f"{(f'{rho:+.3f}' if rho is not None else 'n/a'):>15}"
            f"{(f'{p:.2f}' if p is not None else 'n/a'):>7}"
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
