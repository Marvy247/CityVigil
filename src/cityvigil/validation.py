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
* **Small numbers.** 24 positive ZIPs is a thin sample; a difference in AUC of a
  few points is not meaningful.
* **ZIP boundaries are not tract boundaries.** Tract scores are aggregated to ZIPs
  by containment of the tract centre, which is approximate.
* **One year, one county.** Nothing here establishes that the ranking transfers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .errors import CityVigilError
from .geometry import GridIndex, MultiPolygon, from_geojson_geometry
from .sources import DEFAULT_DATA_DIR, HEAT_DEATHS_BY_ZIP_2022, fetch

#: The county's suppression sentinel. Same value CDC uses, different dataset.
SUPPRESSED = -999

#: Smallest published count, and therefore the implied disclosure threshold.
DISCLOSURE_THRESHOLD = 6


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


def load_zip_outcomes(
    *, data_dir: Path = DEFAULT_DATA_DIR, download: bool = True
) -> dict[str, ZipOutcome]:
    """Load heat deaths by ZIP, mapping the suppression sentinel to ``None``."""
    path = HEAT_DEATHS_BY_ZIP_2022.path(data_dir)
    if not path.is_file():
        if not download:
            raise ValidationError_(
                f"{HEAT_DEATHS_BY_ZIP_2022.key} is not present at {path}. "
                f"Run: python3 scripts/fetch_data.py"
            )
        path = fetch(HEAT_DEATHS_BY_ZIP_2022, data_dir=data_dir)

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

        raw = props.get("HeatDeaths")
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
        """A plain reading of whether the vulnerability weighting earned its place."""
        weighted = self.metrics.get("weighted_person_hours", {}).get("auc")
        heat_only = self.metrics.get("mean_exceedance_h", {}).get("auc")
        if weighted is None or heat_only is None:
            return "undetermined: one class is absent, so AUC is undefined"

        delta = weighted - heat_only
        if abs(delta) < 0.02:
            return (
                f"no meaningful difference (AUC {weighted:.3f} weighted vs "
                f"{heat_only:.3f} heat alone). On this evidence the vulnerability "
                f"weighting does not improve discrimination."
            )
        if delta > 0:
            return (
                f"vulnerability weighting helps: AUC {weighted:.3f} vs "
                f"{heat_only:.3f} for heat alone, a gain of {delta:+.3f}."
            )
        return (
            f"vulnerability weighting HURTS: AUC {weighted:.3f} vs {heat_only:.3f} "
            f"for heat alone, a change of {delta:+.3f}. The weighting is not "
            f"justified by this outcome data."
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
                "24 positive ZIPs is a small sample; small AUC differences are noise.",
                "Tracts are assigned to ZIPs by centre containment, which is approximate.",
                "One year, one county. Nothing here shows the ranking transfers.",
            ],
            "zips": [s.to_dict() for s in self.scores],
        }


def validate(scores: list[ZipScore], *, top_k: int = 10) -> ValidationResult:
    """Score every candidate ranking against recorded mortality."""
    labels = [s.high_mortality for s in scores]
    candidates = {
        "weighted_person_hours": [s.weighted_person_hours for s in scores],
        "person_hours": [s.person_hours for s in scores],
        "mean_exceedance_h": [s.mean_exceedance_h for s in scores],
        "population": [float(s.population) for s in scores],
    }

    metrics: dict[str, dict[str, float | None]] = {}
    for name, values in candidates.items():
        metrics[name] = {
            "auc": auc(values, labels),
            f"precision_at_{top_k}": top_k_precision(values, labels, top_k),
        }

    return ValidationResult(
        n_zips=len(scores),
        n_high_mortality=sum(labels),
        metrics=metrics,
        scores=tuple(scores),
    )
