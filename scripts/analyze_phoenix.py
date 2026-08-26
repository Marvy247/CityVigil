"""Who should Phoenix protect first? Real data, end to end.

    python3 scripts/analyze_phoenix.py

Joins FortyGuard exceedance hours to CDC/ATSDR social vulnerability, Census tract
geometry and LEHD workplace counts, then ranks census tracts by
vulnerability-weighted person-hours of dangerous heat.

Runs from the committed cache by default, so it needs no API key and spends no
credits. Set ``CITYVIGIL_CACHE_MODE=live`` to query new windows.
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
from cityvigil.sources import citations  # noqa: E402
from cityvigil.tracts import load_tracts  # noqa: E402
from cityvigil.vulnerability import VulnerabilityModel, Weights  # noqa: E402

RULE = "=" * 78


def main() -> int:
    settings = Settings.from_env()
    client = FortyGuardClient(settings)
    layers = ExposureLayers(client)

    print(RULE)
    print(f"CityVigil — {PHOENIX.name}")
    print(RULE)
    print(f"episode   : {PHOENIX.episode_start} to {PHOENIX.episode_end}")
    print(f"threshold : {PHOENIX.danger_threshold_f:.0f} F")
    print(f"cache mode: {settings.cache_mode}")
    print()

    print("Loading real tract data…")
    tracts = load_tracts(download=True)
    print(json.dumps(tracts.summary(), indent=2))
    print()

    window = dict(
        threshold=PHOENIX.danger_threshold_f,
        threshold_unit="F",
        start_date=PHOENIX.episode_start,
        end_date=PHOENIX.episode_end,
    )
    print("Querying FortyGuard layers…")
    exceedance = layers.how_long_dangerous(PHOENIX.aoi, **window)
    persistence = layers.any_relief(PHOENIX.aoi, **window)
    snapshot = layers.how_hot(PHOENIX.aoi, start_date=PHOENIX.episode_start)

    print("\nJoining tiles to tracts…")
    assignment = assign_tiles(exceedance, tracts)
    model = VulnerabilityModel(tracts, Weights())
    report = build_exposure_report(
        exceedance, tracts, model, persistence=persistence, snapshot=snapshot,
        assignment=assignment,
    )

    totals = report.totals()
    print()
    print(RULE)
    print("EXPOSURE TOTALS")
    print(RULE)
    print(f"tracts intersecting the study area : {totals['n_tracts']}")
    print(f"residents                          : {totals['population']:,}")
    print(f"  of whom aged 65+                 : {totals['population_65_plus']:,}")
    print(f"jobs in outdoor-exposed sectors    : {totals['outdoor_jobs']:,}")
    print(f"tiles matched / unmatched          : {totals['tiles_matched']:,} / {totals['tiles_unmatched']}")
    print()
    print(f"person-hours above {totals['threshold_c']:.1f} C          : {totals['person_hours']:,.0f}")
    print(f"  borne by residents aged 65+      : {totals['elderly_person_hours']:,.0f}")
    print(f"vulnerability-weighted person-hours: {totals['weighted_person_hours']:,.0f}")
    print(
        f"worker exposure-hours (upper bound): "
        f"{totals['worker_exposure_hours_upper_bound']:,.0f}"
    )

    print()
    print(RULE)
    print("PROTECTION PRIORITY — TOP 10 TRACTS")
    print(RULE)
    header = (
        f"{'#':<3}{'tract':<9}{'pop':>7}{'65+':>6}{'hrs':>6}{'unbrk':>7}"
        f"{'vuln':>6}{'person-h':>11}{'weighted':>11}{'Δrank':>7}"
    )
    print(header)
    print("-" * len(header))
    shifts = {r["geoid"]: r for r in report.rank_shift(limit=10)}
    for position, entry in enumerate(report.ranked(10), start=1):
        row = entry.to_dict()
        shift = shifts.get(row["geoid"], {}).get("moved_up", 0)
        arrow = f"{shift:+d}" if shift else "0"
        print(
            f"{position:<3}{row['geoid'][-6:]:<9}{row['population']:>7,}{row['age65']:>6,}"
            f"{row['mean_exceedance_h']:>6.0f}{(row['mean_persistence_h'] or 0):>7.1f}"
            f"{row['vulnerability']['score']:>6.2f}{row['person_hours']:>11,.0f}"
            f"{row['weighted_person_hours']:>11,.0f}{arrow:>7}"
        )

    print()
    print(RULE)
    print("WHAT THE VULNERABILITY WEIGHTING CHANGES")
    print(RULE)
    raw_top = [e.tract.geoid[-6:] for e in report.ranked_by_person_hours(5)]
    weighted_top = [e.tract.geoid[-6:] for e in report.ranked(5)]
    print(f"by raw person-hours      : {', '.join(raw_top)}")
    print(f"by weighted person-hours : {', '.join(weighted_top)}")
    biggest = max(report.rank_shift(limit=25), key=lambda r: r["moved_up"])
    print(
        f"\nlargest promotion: tract {biggest['geoid'][-6:]} rose "
        f"{biggest['moved_up']} places (#{biggest['rank_person_hours']} by exposure "
        f"alone, #{biggest['rank_weighted']} once who lives there is counted)"
    )

    print()
    print(RULE)
    print("HOW THE TOP TRACT'S SCORE WAS BUILT")
    print(RULE)
    top = report.ranked(1)[0]
    print(f"tract {top.tract.geoid} — {top.tract.name}")
    print(f"  {top.vulnerability.explain()}")
    for name, source in model.describe()["component_sources"].items():
        print(f"  {name:<16} {source}")

    print()
    print(RULE)
    print("MODEL CAVEAT")
    print(RULE)
    print(f"  {model.describe()['caveat']}")
    print(f"  normalisation: {model.describe()['normalisation']}")

    print()
    print(RULE)
    print("DATA SOURCES")
    print(RULE)
    for line in citations():
        print(f"  - {line}")

    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    (out / "phoenix_exposure_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    client.write_audit(out / "phoenix_analysis_audit.json")
    print(f"\nWrote outputs/phoenix_exposure_report.json and the audit trail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
