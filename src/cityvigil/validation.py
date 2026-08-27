"""Validation against an independent outcome: recorded heat deaths.

Why this exists
---------------
Everything else in CityVigil is a model. It ranks tracts by a weighted
combination of heat exposure and published vulnerability indicators, and the
weights are a stated prior rather than a fitted result. That makes the ranking
*defensible*, not *demonstrated*. This module is the attempt to demonstrate it,
by testing the ranking against something it was never given: where people
actually died of heat.

The outcome data and its censoring
---------------------------------
Maricopa County publishes heat-associated deaths by ZIP code. Counts below the
disclosure threshold are suppressed with ``-999``: 118 of 142 ZIPs are censored,
and the smallest published count is 6. So the data cannot support a death-rate
regression. What it does support cleanly is a **binary test**: did this ZIP record
at least 6 heat-associated deaths? Censoring becomes a well-defined label rather
than missing data, and every ZIP can be used.

The test
--------
Rank ZIPs by CityVigil's score and ask how well that ordering separates the
high-mortality ZIPs from the rest, measured as AUC — the probability that a
randomly chosen high-mortality ZIP scores above a randomly chosen other one. 0.5
is a coin flip.

The comparison that actually matters is not "is AUC high" but **"does the
vulnerability weighting beat heat exposure alone?"** Heat exposure is the free
baseline: if the weighted model cannot beat it, the vulnerability layer is
decoration. Both are reported, always, including when the answer is unflattering.

Known limitations of this validation
-----------------------------------
* **Deaths are recorded by place of injury, not residence.** A large share of
  Maricopa heat deaths occur outdoors, so a ZIP's count reflects where people were
  exposed, which is not the same as where the vulnerable population lives. This
  systematically favours ZIPs with public space and disadvantages residential ones.
* **Modest numbers.** 33 high-mortality ZIPs of 92 scored. Bootstrap confidence
  intervals are reported for every candidate so a few points of AUC are not
  mistaken for a real difference.
* **ZIP boundaries are not tract boundaries.** Tract scores are aggregated to ZIPs
  by containment of the tract centre, which is approximate.
* **One year, one county.** Nothing here establishes that the ranking transfers.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import CityVigilError
from .geometry import GridIndex, MultiPolygon, from_geojson_geometry
from .sources import (
    DEFAULT_DATA_DIR,
    HEAT_DEATHS_BY_ZIP_2022,
    HEAT_DEATHS_BY_ZIP_2023,
    fetch,
)

#: The county's suppression sentinel, used in the 2022 ZIP release.
SUPPRESSED = -999

#: Smallest published count in the 2022 release, and therefore the implied
#: disclosure threshold for that year.
DISCLOSURE_THRESHOLD = 6


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation, with average ranks for ties.

    Implemented directly rather than pulling in scipy: it is twenty lines, and the
    dependency budget is spent where it buys more. Returns ``None`` when either
    series is constant, since the correlation is undefined then.
    """
    if len(xs) != len(ys):
        raise ValueError("series must be the same length")
    n = len(xs)
    if n < 3:
        return None

    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: values[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2.0
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n))
    dy = sum((ry[i] - my) ** 2 for i in range(n))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy) ** 0.5


def bootstrap_auc_ci(
    scores: Sequence[float],
    labels: Sequence[bool],
    *,
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 12345,
) -> tuple[float, float] | None:
    """Percentile bootstrap confidence interval for AUC.

    The 2022 result reported a bare point estimate with a verbal caveat that the
    sample was small. An interval says the same thing quantitatively, and is what
    turns "the weighting might not help" into a defensible claim either way.
    """
    if not scores:
        return None
    rng = random.Random(seed)
    n = len(scores)
    draws: list[float] = []
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        value = auc([scores[i] for i in idx], [labels[i] for i in idx])
        if value is not None:
            draws.append(value)
    if len(draws) < iterations // 4:
        return None
    draws.sort()
    lo = draws[int((1 - confidence) / 2 * len(draws))]
    hi = draws[int((1 + confidence) / 2 * len(draws)) - 1]
    return (lo, hi)


class ValidationError_(CityVigilError):
    """Outcome data could not be assembled."""


@dataclass(frozen=True)
class ZipOutcome:
    """Recorded heat mortality for one ZIP code."""

    zip_code: str
    geometry: MultiPolygon
    #: Published count, or ``None`` when suppressed.
    deaths: int | None

    @property
    def suppressed(self) -> bool:
        return self.deaths is None

    @property
    def high_mortality(self) -> bool:
        """The binary label: did this ZIP reach the disclosure threshold?

        A suppressed ZIP is *known* to be below the threshold, so ``False`` here is
        an observation rather than an assumption.
        """
        return self.deaths is not None and self.deaths >= DISCLOSURE_THRESHOLD


#: Which release to validate against. 2023 is the default: its counts are
#: uncensored, so it supports rank correlation and confidence intervals rather
#: than only a binary above-threshold test.
RELEASES = {
    2022: (HEAT_DEATHS_BY_ZIP_2022, "HeatDeaths"),
    2023: (HEAT_DEATHS_BY_ZIP_2023, "Count_"),
}


def load_zip_outcomes(
    *, data_dir: Path = DEFAULT_DATA_DIR, download: bool = True, year: int = 2023
) -> dict[str, ZipOutcome]:
    """Load heat deaths by ZIP for one release year.

    The 2022 release suppresses counts below the disclosure threshold with -999;
    the 2023 release publishes actual counts including zeros. Both are handled, and
    ``ZipOutcome.suppressed`` distinguishes them per record.
    """
    if year not in RELEASES:
        raise ValidationError_(f"no outcome release for {year}; have {sorted(RELEASES)}")
    source, field = RELEASES[year]

    path = source.path(data_dir)
    if not path.is_file():
        if not download:
            raise ValidationError_(
                f"{source.key} is not present at {path}. "
                f"Run: python3 scripts/fetch_data.py"
            )
        path = fetch(source, data_dir=data_dir)

    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if not features:
        raise ValidationError_(f"{path} contains no ZIP features")

    out: dict[str, ZipOutcome] = {}
    for feature in features:
        props = feature.get("properties") or {}
        zip_code = str(props.get("ZipCode") or "").strip()
        if not zip_code:
            continue
        try:
            geometry = from_geojson_geometry(feature.get("geometry") or {})
        except ValueError:
            continue

        raw = props.get(field)
        deaths: int | None
        try:
            value = int(raw)  # type: ignore[arg-type]
            deaths = None if value == SUPPRESSED or value < 0 else value
        except (TypeError, ValueError):
            deaths = None

        out[zip_code] = ZipOutcome(zip_code=zip_code, geometry=geometry, deaths=deaths)

    if not out:
        raise ValidationError_(f"{path} yielded no usable ZIP outcomes")
    return out


def study_region(
    outcomes: dict[str, ZipOutcome],
    *,
    coverage: float = 0.8,
) -> tuple[tuple[float, float, float, float], list[str]]:
    """Choose a study region that captures most of the outcome without covering desert.

    Taking the bounding box of every ZIP with a published count works for a censored
    release, where only two dozen urban ZIPs are published. It fails badly for an
    uncensored one: all 137 Maricopa ZIPs carry a value, including the empty fringe,
    so the box becomes the whole 36,433 km² county — 330 heatmap tiles and 1.39
    million credits for a question that lives in the urban core. That was measured,
    not hypothesised; a run was aborted after it started down that path.

    Instead, ZIPs are taken in descending order of recorded deaths until ``coverage``
    of all recorded deaths is accounted for, and the region is the box around those.
    Validation then runs on every ZIP whose centre falls inside, so the sample still
    contains both high- and low-outcome ZIPs rather than only the worst.

    Returns ``(bbox, zip_codes_defining_it)``.
    """
    from .geometry import bbox_union

    counted = [o for o in outcomes.values() if o.deaths]
    if not counted:
        raise ValidationError_("no ZIP carries a nonzero death count")

    ordered = sorted(counted, key=lambda o: -(o.deaths or 0))
    total = sum(o.deaths or 0 for o in ordered)
    target = total * coverage

    chosen: list[ZipOutcome] = []
    running = 0
    for outcome in ordered:
        chosen.append(outcome)
        running += outcome.deaths or 0
        if running >= target:
            break

    return bbox_union(o.geometry.bbox for o in chosen), [o.zip_code for o in chosen]


def outcome_summary(outcomes: dict[str, ZipOutcome]) -> dict:
    """Counts and totals, including how much of the data is censored."""
    published = [o for o in outcomes.values() if not o.suppressed]
    return {
        "n_zips": len(outcomes),
        "n_published": len(published),
        "n_suppressed": sum(1 for o in outcomes.values() if o.suppressed),
        "n_high_mortality": sum(1 for o in outcomes.values() if o.high_mortality),
        "published_deaths_total": sum(o.deaths or 0 for o in published),
        "min_published": min((o.deaths or 0 for o in published), default=None),
        "max_published": max((o.deaths or 0 for o in published), default=None),
        "disclosure_threshold": DISCLOSURE_THRESHOLD,
        "censoring_note": (
            "Suppressed ZIPs are known to be below the disclosure threshold, so a "
            "negative label is an observation, not an assumption."
        ),
    }


# ---------------------------------------------------------------------- metrics


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Area under the ROC curve, via the rank-sum identity.

    Equal to the probability that a randomly chosen positive outranks a randomly
    chosen negative, with ties counted as half. Returns ``None`` when one class is
    absent, because AUC is undefined then.

    Implemented directly rather than pulled from scikit-learn: it is a dozen lines,
    and the dependency budget is spent where it buys more.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")

    positives = [s for s, y in zip(scores, labels) if y]
    negatives = [s for s, y in zip(scores, labels) if not y]
    if not positives or not negatives:
        return None

    wins = 0.0
    for p in positives:
        for n in negatives:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def top_k_precision(
    scores: Sequence[float], labels: Sequence[bool], k: int
) -> float | None:
    """Share of the top ``k`` ranked items that are positive.

    More operationally meaningful than AUC: if a city can only act on ten
    neighbourhoods, this is the question it is actually asking.
    """
    if k <= 0 or not scores:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return sum(1 for i in order if labels[i]) / len(order)


# ------------------------------------------------------------------ aggregation


def zip_index(outcomes: dict[str, ZipOutcome]) -> GridIndex:
    """Spatial index over ZIP polygons, for assigning tracts to ZIPs."""
    return GridIndex(((z, o.geometry) for z, o in outcomes.items()), cell_size=0.05)


@dataclass(frozen=True)
class ZipScore:
    """A ZIP's aggregated model scores and its observed outcome."""

    zip_code: str
    n_tracts: int
    population: int
    #: Vulnerability-weighted person-hours summed over the ZIP's tracts.
    weighted_person_hours: float
    #: Raw person-hours, the heat-and-population baseline.
    person_hours: float
    #: Mean exceedance hours, the heat-only baseline (no population at all).
    mean_exceedance_h: float
    deaths: int | None
    high_mortality: bool

    def to_dict(self) -> dict:
        return {
            "zip_code": self.zip_code,
            "n_tracts": self.n_tracts,
            "population": self.population,
            "weighted_person_hours": round(self.weighted_person_hours, 1),
            "person_hours": round(self.person_hours, 1),
            "mean_exceedance_h": round(self.mean_exceedance_h, 2),
            "deaths": self.deaths,
            "high_mortality": self.high_mortality,
        }


def aggregate_to_zips(
    tract_entries: Iterable,
    outcomes: dict[str, ZipOutcome],
    *,
    index: GridIndex | None = None,
) -> list[ZipScore]:
    """Roll tract-level exposure up to ZIP codes.

    ``tract_entries`` are :class:`~cityvigil.exposure.TractExposure` records. Each
    tract is assigned to the ZIP containing its representative centre, which is
    approximate where tracts straddle ZIP boundaries.
    """
    idx = index or zip_index(outcomes)
    buckets: dict[str, list] = {}

    for entry in tract_entries:
        zip_code = idx.find(entry.tract.geometry.centroid)
        if zip_code is None:
            continue
        buckets.setdefault(zip_code, []).append(entry)

    scores: list[ZipScore] = []
    for zip_code, entries in buckets.items():
        outcome = outcomes[zip_code]
        population = sum(e.tract.population for e in entries)
        scores.append(
            ZipScore(
                zip_code=zip_code,
                n_tracts=len(entries),
                population=population,
                weighted_person_hours=sum(e.weighted_person_hours for e in entries),
                person_hours=sum(e.person_hours for e in entries),
                mean_exceedance_h=(
                    sum(e.mean_exceedance_h for e in entries) / len(entries)
                ),
                deaths=outcome.deaths,
                high_mortality=outcome.high_mortality,
            )
        )
    return scores


# -------------------------------------------------------------------- reporting


@dataclass(frozen=True)
class ValidationResult:
    """Discrimination of each candidate score against recorded mortality."""

    n_zips: int
    n_high_mortality: int
    metrics: dict[str, dict[str, float | None]]
    scores: tuple[ZipScore, ...]

    @property
    def verdict(self) -> str:
        """A plain reading of whether the vulnerability weighting earned its place.

        Uses the bootstrap intervals rather than comparing point estimates, because
        two AUCs a few points apart on a small sample say nothing.
        """
        weighted = self.metrics.get("weighted_person_hours", {})
        heat_only = self.metrics.get("mean_exceedance_h", {})
        w, h = weighted.get("auc"), heat_only.get("auc")
        if w is None or h is None:
            return "undetermined: one class is absent, so AUC is undefined"

        w_lo, h_hi = weighted.get("auc_ci_low"), heat_only.get("auc_ci_high")
        w_rho, h_rho = weighted.get("spearman_vs_counts"), heat_only.get("spearman_vs_counts")
        rho_note = (
            f" Against actual death counts, rank correlation is {w_rho:+.3f} weighted "
            f"versus {h_rho:+.3f} for heat alone."
            if w_rho is not None and h_rho is not None
            else ""
        )

        # Separated intervals are the only basis for claiming a real difference.
        if w_lo is not None and h_hi is not None and w_lo > h_hi:
            return (
                f"vulnerability weighting helps, and the intervals separate: AUC "
                f"{w:.3f} (95% CI {w_lo:.3f}-{weighted['auc_ci_high']:.3f}) versus "
                f"{h:.3f} (CI {h_hi:.3f} upper) for heat alone.{rho_note}"
            )

        delta = w - h
        direction = "above" if delta > 0 else "below"
        return (
            f"not demonstrated: AUC {w:.3f} weighted versus {h:.3f} heat alone, "
            f"{abs(delta):.3f} {direction}, but the bootstrap intervals overlap "
            f"(weighted {weighted.get('auc_ci_low')}-{weighted.get('auc_ci_high')}, "
            f"heat {heat_only.get('auc_ci_low')}-{heat_only.get('auc_ci_high')}). "
            f"On this evidence the weighting cannot be claimed to improve "
            f"discrimination over a free baseline.{rho_note}"
        )

    def to_dict(self) -> dict:
        return {
            "n_zips": self.n_zips,
            "n_high_mortality": self.n_high_mortality,
            "metrics": self.metrics,
            "verdict": self.verdict,
            "limitations": [
                "Deaths are recorded by place of injury, not residence; most "
                "Maricopa heat deaths occur outdoors.",
                "33 high-mortality ZIPs of 92 is still a modest sample; the bootstrap "
                "intervals are reported precisely so differences are not over-read.",
                "Tracts are assigned to ZIPs by centre containment, which is approximate.",
                "One year, one county. Nothing here shows the ranking transfers.",
            ],
            "zips": [s.to_dict() for s in self.scores],
        }


def validate(scores: list[ZipScore], *, top_k: int = 10) -> ValidationResult:
    """Score every candidate ranking against recorded mortality.

    Reports three things per candidate:

    * **AUC** with a bootstrap confidence interval — discrimination, and how
      certain that estimate is. The interval is what the 2022 result lacked.
    * **Spearman correlation against actual death counts** — only meaningful for an
      uncensored release, and a stronger test than a binary threshold because it
      uses the magnitude of every observation rather than collapsing to yes/no.
    * **Precision at k** — the operationally useful question: of the k
      neighbourhoods a city could actually act on, how many mattered.
    """
    labels = [s.high_mortality for s in scores]
    counts = [float(s.deaths) if s.deaths is not None else None for s in scores]
    candidates = {
        "weighted_person_hours": [s.weighted_person_hours for s in scores],
        "person_hours": [s.person_hours for s in scores],
        "mean_exceedance_h": [s.mean_exceedance_h for s in scores],
        "population": [float(s.population) for s in scores],
    }

    # Rank correlation needs actual counts, so it is computed on the subset with them.
    with_counts = [i for i, c in enumerate(counts) if c is not None]

    metrics: dict[str, dict[str, float | None]] = {}
    for name, values in candidates.items():
        ci = bootstrap_auc_ci(values, labels)
        rho = (
            spearman([values[i] for i in with_counts], [counts[i] for i in with_counts])
            if len(with_counts) >= 3
            else None
        )
        metrics[name] = {
            "auc": auc(values, labels),
            "auc_ci_low": None if ci is None else round(ci[0], 4),
            "auc_ci_high": None if ci is None else round(ci[1], 4),
            "spearman_vs_counts": None if rho is None else round(rho, 4),
            "n_with_counts": len(with_counts),
            f"precision_at_{top_k}": top_k_precision(values, labels, top_k),
        }

    return ValidationResult(
        n_zips=len(scores),
        n_high_mortality=sum(labels),
        metrics=metrics,
        scores=tuple(scores),
    )
