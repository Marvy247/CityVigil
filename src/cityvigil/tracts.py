"""Census tract profiles built from real federal data.

Joins three sources on the 11-digit tract GEOID:

* CDC/ATSDR SVI 2022 — population and social vulnerability components
* Census TIGERweb — tract polygons
* LEHD LODES8 WAC — jobs by NAICS sector at the workplace

Data handling decisions that matter
----------------------------------
**CDC's missing-value sentinel is -999, not NaN.** Eighteen Maricopa tracts carry
``RPL_THEMES = -999``. Read naively that becomes a vulnerability percentile of
minus nine hundred, which would silently dominate any weighted index. It is
converted to ``None`` here and those tracts fall back to component indicators.

**Twelve Maricopa tracts have zero population.** Industrial land, airport,
parkland. They are retained — a heat surface still covers them and outdoor workers
may still be present — but they contribute no resident person-hours, and every
share is guarded against division by zero.

**Jobs are counted where people work, not where they live.** LODES WAC is keyed on
workplace, which is the correct frame for daytime heat exposure. Residence-based
counts would place construction crews in their bedrooms at 3pm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .errors import CityVigilError
from .geometry import GridIndex, MultiPolygon, from_geojson_geometry
from .sources import (
    DEFAULT_DATA_DIR,
    LODES_ARIZONA_WAC,
    MARICOPA_TRACT_GEOMETRY,
    SVI_ARIZONA,
    fetch,
)

#: CDC/ATSDR uses -999 to mean "no data".
CDC_MISSING = -999

#: LODES WAC columns for sectors whose work is substantially outdoors or in
#: un-conditioned space. NAICS via the LODES CNS mapping:
#:   CNS01 = 11 Agriculture, Forestry, Fishing and Hunting
#:   CNS02 = 21 Mining, Quarrying, Oil and Gas Extraction
#:   CNS03 = 22 Utilities
#:   CNS04 = 23 Construction
#:   CNS08 = 48-49 Transportation and Warehousing
#: A defensible proxy, not a measurement: it over-counts warehouse staff in cooled
#: buildings and under-counts outdoor work in retail, services and landscaping.
OUTDOOR_SECTORS: tuple[str, ...] = ("CNS01", "CNS02", "CNS03", "CNS04", "CNS08")


class TractDataError(CityVigilError):
    """Tract data could not be assembled."""


def _clean_count(value: object) -> int:
    """Coerce an SVI count to a non-negative int, mapping the -999 sentinel to 0."""
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return 0 if number == CDC_MISSING or number < 0 else number


def _clean_percentile(value: object) -> float | None:
    """Coerce an SVI percentile to 0-1, mapping -999 and out-of-range to ``None``."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number == CDC_MISSING or not (0.0 <= number <= 1.0):
        return None
    return number


def _share(part: int, whole: int) -> float:
    """Safe share, zero when the denominator is zero."""
    return (part / whole) if whole > 0 else 0.0


@dataclass(frozen=True)
class Tract:
    """One census tract, with real counts from the SVI and LODES releases."""

    geoid: str
    name: str
    geometry: MultiPolygon

    # --- resident population, CDC/ATSDR SVI 2022 --------------------------
    population: int
    age65: int
    poverty150: int
    no_vehicle: int
    disability: int
    uninsured: int
    #: CDC's own overall SVI percentile (RPL_THEMES), 0-1. ``None`` when missing.
    svi_percentile: float | None

    # --- daytime workforce, LEHD LODES8 WAC 2021 --------------------------
    jobs_total: int
    jobs_outdoor: int

    @property
    def elderly_share(self) -> float:
        """Residents aged 65+. The strongest demographic predictor of heat death."""
        return _share(self.age65, self.population)

    @property
    def poverty_share(self) -> float:
        return _share(self.poverty150, self.population)

    @property
    def no_vehicle_share(self) -> float:
        """A direct proxy for inability to reach a cooling centre unaided."""
        return _share(self.no_vehicle, self.population)

    @property
    def disability_share(self) -> float:
        return _share(self.disability, self.population)

    @property
    def outdoor_job_share(self) -> float:
        return _share(self.jobs_outdoor, self.jobs_total)

    def to_dict(self) -> dict:
        return {
            "geoid": self.geoid,
            "name": self.name,
            "population": self.population,
            "age65": self.age65,
            "poverty150": self.poverty150,
            "no_vehicle": self.no_vehicle,
            "disability": self.disability,
            "uninsured": self.uninsured,
            "svi_percentile": self.svi_percentile,
            "jobs_total": self.jobs_total,
            "jobs_outdoor": self.jobs_outdoor,
            "elderly_share": round(self.elderly_share, 4),
            "poverty_share": round(self.poverty_share, 4),
            "outdoor_job_share": round(self.outdoor_job_share, 4),
        }


@dataclass
class TractCollection:
    """Tracts plus a lazily built spatial index over their geometry."""

    tracts: dict[str, Tract] = field(default_factory=dict)
    _index: GridIndex | None = field(default=None, repr=False)

    def __len__(self) -> int:
        return len(self.tracts)

    def __iter__(self) -> Iterator[Tract]:
        return iter(self.tracts.values())

    def __getitem__(self, geoid: str) -> Tract:
        return self.tracts[geoid]

    @property
    def index(self) -> GridIndex:
        if self._index is None:
            self._index = GridIndex((g, t.geometry) for g, t in self.tracts.items())
        return self._index

    def locate(self, lon: float, lat: float) -> Tract | None:
        """Tract containing a point, or ``None`` outside the county."""
        geoid = self.index.find((lon, lat))
        return self.tracts.get(geoid) if geoid else None

    def total_population(self) -> int:
        return sum(t.population for t in self.tracts.values())

    def summary(self) -> dict:
        pops = [t.population for t in self.tracts.values()]
        return {
            "n_tracts": len(self.tracts),
            "total_population": sum(pops),
            "zero_population_tracts": sum(1 for p in pops if p == 0),
            "missing_svi_percentile": sum(
                1 for t in self.tracts.values() if t.svi_percentile is None
            ),
            "total_jobs": sum(t.jobs_total for t in self.tracts.values()),
            "outdoor_jobs": sum(t.jobs_outdoor for t in self.tracts.values()),
        }

    def areas_km2(self) -> dict[str, float]:
        """Tract areas, for expressing counts as densities.

        Computed from the polygons rather than taken from a published field so it
        always matches the geometry actually being used for the spatial join.
        """
        return {geoid: t.geometry.area_km2 for geoid, t in self.tracts.items()}


# ----------------------------------------------------------------------- loading


def _load_svi(path: Path, county: str = "Maricopa") -> dict[str, dict]:
    """Parse the SVI CSV into ``{geoid: fields}`` for one county."""
    import pandas as pd

    frame = pd.read_csv(path, dtype={"FIPS": str}, low_memory=False)
    if "COUNTY" not in frame.columns:
        raise TractDataError(f"{path} has no COUNTY column; the schema may have changed")

    subset = frame[frame["COUNTY"].astype(str).str.contains(county, na=False)]
    if subset.empty:
        raise TractDataError(f"no {county} County rows found in {path}")

    required = ["FIPS", "E_TOTPOP", "E_AGE65", "E_POV150", "E_NOVEH", "RPL_THEMES"]
    absent = [c for c in required if c not in subset.columns]
    if absent:
        raise TractDataError(f"{path} is missing expected SVI columns: {absent}")

    out: dict[str, dict] = {}
    for row in subset.itertuples(index=False):
        geoid = str(getattr(row, "FIPS")).zfill(11)
        out[geoid] = {
            "population": _clean_count(getattr(row, "E_TOTPOP", 0)),
            "age65": _clean_count(getattr(row, "E_AGE65", 0)),
            "poverty150": _clean_count(getattr(row, "E_POV150", 0)),
            "no_vehicle": _clean_count(getattr(row, "E_NOVEH", 0)),
            "disability": _clean_count(getattr(row, "E_DISABL", 0)),
            "uninsured": _clean_count(getattr(row, "E_UNINSUR", 0)),
            "svi_percentile": _clean_percentile(getattr(row, "RPL_THEMES", None)),
        }
    return out


def _load_jobs(path: Path, state_county: str = "04013") -> dict[str, dict]:
    """Aggregate block-level LODES WAC rows to tract totals."""
    import pandas as pd

    frame = pd.read_csv(path, dtype={"w_geocode": str}, compression="gzip")
    if "w_geocode" not in frame.columns or "C000" not in frame.columns:
        raise TractDataError(f"{path} does not look like a LODES WAC file")

    present = [c for c in OUTDOOR_SECTORS if c in frame.columns]
    if not present:
        raise TractDataError(f"{path} has none of the expected CNS sector columns")

    frame = frame[frame["w_geocode"].str.startswith(state_county)].copy()
    frame["tract"] = frame["w_geocode"].str[:11]
    grouped = frame.groupby("tract")[["C000", *present]].sum()

    return {
        str(geoid): {
            "jobs_total": int(row["C000"]),
            "jobs_outdoor": int(sum(row[c] for c in present)),
        }
        for geoid, row in grouped.iterrows()
    }


def _load_geometry(path: Path) -> dict[str, tuple[str, MultiPolygon]]:
    """Parse tract polygons into ``{geoid: (name, geometry)}``."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if not features:
        raise TractDataError(f"{path} contains no tract features")

    out: dict[str, tuple[str, MultiPolygon]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        geoid = str(props.get("GEOID") or "").zfill(11)
        if not geoid.strip("0"):
            continue
        try:
            geometry = from_geojson_geometry(feature.get("geometry") or {})
        except ValueError:
            continue  # skip non-polygonal records rather than fail the whole load
        out[geoid] = (str(props.get("NAME") or geoid), geometry)
    return out


def load_tracts(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    county: str = "Maricopa",
    state_county_fips: str = "04013",
    download: bool = True,
) -> TractCollection:
    """Assemble the tract collection, downloading sources if needed.

    Tracts lacking geometry are dropped, since nothing can be spatially joined to
    them. Tracts lacking a LODES row keep zero jobs, which is the correct reading:
    no recorded workplace means no recorded workers.
    """
    paths: dict[str, Path] = {}
    for source in (SVI_ARIZONA, MARICOPA_TRACT_GEOMETRY, LODES_ARIZONA_WAC):
        path = source.path(data_dir)
        if not path.is_file():
            if not download:
                raise TractDataError(
                    f"{source.key} is not present at {path} and download=False. "
                    f"Run: python3 scripts/fetch_data.py"
                )
            path = fetch(source, data_dir=data_dir)
        paths[source.key] = path

    svi = _load_svi(paths[SVI_ARIZONA.key], county=county)
    jobs = _load_jobs(paths[LODES_ARIZONA_WAC.key], state_county=state_county_fips)
    geometry = _load_geometry(paths[MARICOPA_TRACT_GEOMETRY.key])

    tracts: dict[str, Tract] = {}
    for geoid, (name, geom) in geometry.items():
        stats = svi.get(geoid)
        if stats is None:
            continue  # geometry with no SVI row cannot be characterised
        job = jobs.get(geoid, {"jobs_total": 0, "jobs_outdoor": 0})
        tracts[geoid] = Tract(
            geoid=geoid,
            name=name,
            geometry=geom,
            jobs_total=job["jobs_total"],
            jobs_outdoor=job["jobs_outdoor"],
            **stats,
        )

    if not tracts:
        raise TractDataError(
            "no tracts survived the join between geometry and SVI — check that the "
            "county and FIPS arguments match the downloaded sources"
        )
    return TractCollection(tracts=tracts)
