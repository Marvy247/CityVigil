"""Where would today's cooling network leave people unprotected?

    CITYVIGIL_CACHE_MODE=replay python3 scripts/coverage_gap.py

Combines three real datasets:

* FortyGuard exceedance hours over central Phoenix, 15-21 July 2024
* CDC/ATSDR social vulnerability and Census population by tract
* The Maricopa Heat Relief Network's current cooling sites, with opening hours

Framing, stated up front: the Heat Relief Network service publishes only the
CURRENT season. It cannot describe what was open in July 2024. This asks the
counterfactual — given the network operating today, where would gaps fall during a
heat event like the one that actually happened?
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cityvigil import FortyGuardClient, Settings  # noqa: E402
from cityvigil.cities import PHOENIX  # noqa: E402
from cityvigil.exposure import assign_tiles, build_exposure_report  # noqa: E402
from cityvigil.layers import ExposureLayers  # noqa: E402
from cityvigil.supply import (  # noqa: E402
    coverage_for_tracts,
    load_sites,
    open_site_count_by_hour,
    supply_summary,
)
from cityvigil.tracts import load_tracts  # noqa: E402
from cityvigil.vulnerability import VulnerabilityModel  # noqa: E402

RULE = "=" * 78
#: Hours to evaluate: mid-afternoon, the temperature peak, and the evening when
#: it is still dangerous but provision has thinned out.
HOURS = (14.0, 16.0, 17.0, 19.0, 20.0)
WEEKDAY = "Wednesday"


def main() -> int:
    settings = Settings.from_env()
    client = FortyGuardClient(settings)
    layers = ExposureLayers(client)

    print(RULE)
    print(f"CityVigil — cooling coverage gap, {PHOENIX.name}")
    print(RULE)
    print(f"heat episode : {PHOENIX.episode_start} to {PHOENIX.episode_end}")
    print(f"threshold    : {PHOENIX.danger_threshold_f:.0f} F")
    print(f"cache mode   : {settings.cache_mode}")
    print()

    tracts = load_tracts(download=True)
    sites = load_sites(download=True)
    summary = supply_summary(sites)

    print(RULE)
    print("SUPPLY — MARICOPA HEAT RELIEF NETWORK (CURRENT SEASON)")
    print(RULE)
    print(f"sites total            : {summary['n_sites']}")
    for kind, count in summary["by_type"].items():
        print(f"  {kind:<20} {count}")
    print(f"indoor cooling sites   : {summary['n_cooling_sites']}")
    print(f"  ADA accessible       : {summary['ada_accessible']}")
    print(f"  median closing hour  : {summary['median_weekday_closing_hour']}:00")
    print(f"season                 : {summary['season']['start']} to {summary['season']['end']}")
    print(f"\n  CAVEAT: {summary['vintage_caveat']}")

    # --- the hours story -------------------------------------------------
    counts = open_site_count_by_hour(sites, weekday=WEEKDAY)
    peak_open = max(counts.values())
    peak_hour = max(counts, key=lambda h: counts[h])

    print()
    print(RULE)
    print(f"WHEN IS COOLING ACTUALLY AVAILABLE? ({WEEKDAY})")
    print(RULE)
    for hour in range(9, 23):
        bar = "#" * int(counts[hour] / max(peak_open, 1) * 40)
        pct = counts[hour] / max(peak_open, 1) * 100
        print(f"  {hour:02d}:00  {counts[hour]:>3} sites {pct:>5.0f}%  {bar}")
    print(f"\n  capacity peaks at {peak_hour}:00 with {peak_open} sites open")
    for hour in (17, 19, 20):
        drop = (1 - counts[hour] / max(peak_open, 1)) * 100
        print(f"  by {hour}:00 only {counts[hour]} remain — a {drop:.0f}% fall from peak")

    # --- demand ----------------------------------------------------------
    window = dict(
        threshold=PHOENIX.danger_threshold_f,
        threshold_unit="F",
        start_date=PHOENIX.episode_start,
        end_date=PHOENIX.episode_end,
    )
    exceedance = layers.how_long_dangerous(PHOENIX.aoi, **window)
    persistence = layers.any_relief(PHOENIX.aoi, **window)
    model = VulnerabilityModel(tracts)
    report = build_exposure_report(
        exceedance,
        tracts,
        model,
        persistence=persistence,
        assignment=assign_tiles(exceedance, tracts),
    )
    totals = report.totals()

    # Days in the analysed window, to express exceedance as hours per day.
    days = 7
    hours_per_day = totals["person_hours"] / max(totals["population"], 1) / days

    print()
    print(RULE)
    print("DEMAND — WHEN IS IT DANGEROUS?")
    print(RULE)
    print(f"study area residents     : {totals['population']:,}")
    print(f"mean hours above threshold: {hours_per_day:.1f} per day, per person")
    print(
        f"\n  So the dangerous window runs roughly {hours_per_day:.0f} hours a day, "
        f"while cooling capacity\n  falls {(1 - counts[19] / max(peak_open, 1)) * 100:.0f}% "
        f"between {peak_hour}:00 and 19:00. Provision thins out while it is\n"
        f"  still dangerous outside."
    )

    # --- the gap ---------------------------------------------------------
    print()
    print(RULE)
    print("UNMET NEED — RESIDENTS WITHOUT A WALKABLE OPEN COOLING SITE")
    print(RULE)
    print(f"{'hour':<7}{'sites open':>11}{'tracts uncovered':>18}{'residents':>12}{'person-hours':>15}")
    print("-" * 63)

    studied = [e.tract for e in report.tracts]
    gap_rows = []
    for hour in HOURS:
        coverage = coverage_for_tracts(studied, sites, weekday=WEEKDAY, hour=hour)
        uncovered = [e for e in report.tracts if not coverage[e.tract.geoid].walkable_cover]
        residents = sum(e.tract.population for e in uncovered)
        person_hours = sum(e.person_hours for e in uncovered)
        gap_rows.append(
            {
                "hour": hour,
                "sites_open": counts[int(hour)],
                "tracts_uncovered": len(uncovered),
                "residents_uncovered": residents,
                "unmet_person_hours": round(person_hours, 1),
            }
        )
        print(
            f"{int(hour):02d}:00 {counts[int(hour)]:>11}{len(uncovered):>18}"
            f"{residents:>12,}{person_hours:>15,.0f}"
        )

    print(
        "\n  'Uncovered' means no indoor cooling site open within "
        "800 m straight-line of the\n  tract centre. Street distance is longer, so "
        "these figures understate the gap."
    )

    # --- isolate the hours effect from the walkability effect ------------
    # The absolute "uncovered" level is dominated by the strict 800 m standard.
    # What the closing times cost specifically is the set of tracts that HAVE a
    # walkable site during the afternoon and lose it by the evening.
    at_peak = coverage_for_tracts(studied, sites, weekday=WEEKDAY, hour=float(peak_hour))
    at_evening = coverage_for_tracts(studied, sites, weekday=WEEKDAY, hour=19.0)
    lost = [
        e
        for e in report.tracts
        if at_peak[e.tract.geoid].walkable_cover
        and not at_evening[e.tract.geoid].walkable_cover
    ]

    print()
    print(RULE)
    print("SEPARATING THE TWO CAUSES")
    print(RULE)
    covered_at_peak = sum(1 for e in report.tracts if at_peak[e.tract.geoid].walkable_cover)
    print(
        f"Two different things drive the numbers above, and they should not be\n"
        f"conflated:\n\n"
        f"  distance : only {covered_at_peak} of {len(report.tracts)} tracts have a walkable "
        f"cooling site even at\n             {peak_hour}:00, when the network is at full "
        f"capacity. That is a siting gap,\n             not an hours gap.\n\n"
        f"  hours    : {len(lost)} tracts have walkable cooling in the afternoon and lose it "
        f"by 19:00,\n             affecting "
        f"{sum(e.tract.population for e in lost):,} residents and "
        f"{sum(e.person_hours for e in lost):,.0f} person-hours.\n"
        f"             That gap closes by changing opening times, not by building "
        f"anything."
    )
    if lost:
        print("\n  tracts that lose walkable cooling purely to closing times:")
        for entry in sorted(lost, key=lambda e: -e.weighted_person_hours)[:6]:
            cover = at_evening[entry.tract.geoid]
            nearest = (
                f"{cover.nearest_open_km:.1f} km"
                if cover.nearest_open_km is not None
                else "none open"
            )
            print(
                f"    {entry.tract.geoid[-6:]}  pop {entry.tract.population:>6,}  "
                f"65+ {entry.tract.age65:>5,}  vuln {entry.vulnerability.score:.2f}  "
                f"nearest open at 19:00: {nearest}"
            )

    # --- worst-served tracts at the evening hour -------------------------
    evening = coverage_for_tracts(studied, sites, weekday=WEEKDAY, hour=19.0)
    worst = [e for e in report.ranked() if not evening[e.tract.geoid].walkable_cover][:8]

    print()
    print(RULE)
    print("HIGHEST-PRIORITY TRACTS WITH NO OPEN SITE AT 19:00")
    print(RULE)
    print(f"{'tract':<9}{'pop':>7}{'65+':>6}{'vuln':>6}{'person-h':>11}{'nearest open':>14}")
    print("-" * 53)
    for entry in worst:
        cover = evening[entry.tract.geoid]
        nearest = (
            f"{cover.nearest_open_km:.1f} km" if cover.nearest_open_km is not None else "none open"
        )
        print(
            f"{entry.tract.geoid[-6:]:<9}{entry.tract.population:>7,}"
            f"{entry.tract.age65:>6,}{entry.vulnerability.score:>6.2f}"
            f"{entry.person_hours:>11,.0f}{nearest:>14}"
        )

    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    (out / "phoenix_coverage_gap.json").write_text(
        json.dumps(
            {
                "framing": (
                    "Current-season Heat Relief Network evaluated against the "
                    "July 2024 heat episode. Not a record of what was open in 2024."
                ),
                "supply": summary,
                "open_by_hour": counts,
                "demand_totals": totals,
                "gap_by_hour": gap_rows,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote outputs/phoenix_coverage_gap.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
