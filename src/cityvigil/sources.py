"""Real external data sources, with citations and download provenance.

Every dataset CityVigil uses outside the FortyGuard API is declared here, with
its exact retrieval URL, its citation, and its licence. Nothing is fabricated and
nothing is a placeholder: an indicator that cannot be traced to a row in one of
these files does not enter the model.

Downloads are cached on disk and recorded in a manifest carrying the URL, byte
size, SHA-256 and retrieval timestamp, so a result can be tied to the exact bytes
that produced it. All three sources are US federal government works in the public
domain, which is why they can be redistributed with this project.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .errors import CityVigilError

#: Arizona = 04, Maricopa County = 013. Phoenix sits inside Maricopa.
STATE_FIPS = "04"
MARICOPA_FIPS = "013"

DEFAULT_DATA_DIR = Path("data/sources")
MANIFEST_NAME = "manifest.json"


class SourceError(CityVigilError):
    """A source could not be retrieved or failed verification."""


@dataclass(frozen=True)
class DataSource:
    """One external dataset."""

    key: str
    name: str
    url: str
    filename: str
    citation: str
    licence: str
    #: What this source contributes to the model, in one line.
    role: str

    def path(self, data_dir: Path = DEFAULT_DATA_DIR) -> Path:
        return Path(data_dir) / self.filename


def _tigerweb_tracts_url(state: str = STATE_FIPS, county: str = MARICOPA_FIPS) -> str:
    """Build the TIGERweb query returning tract polygons as GeoJSON in WGS84."""
    base = (
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
        "Tracts_Blocks/MapServer/0/query"
    )
    params = {
        "where": f"STATE='{state}' AND COUNTY='{county}'",
        "outFields": "GEOID,STATE,COUNTY,TRACT,NAME",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


SVI_ARIZONA = DataSource(
    key="svi_arizona_2022",
    name="CDC/ATSDR Social Vulnerability Index 2022 — Arizona, census tracts",
    url="https://svi.cdc.gov/Documents/Data/2022/csv/states/Arizona.csv",
    filename="svi_arizona_2022.csv",
    citation=(
        "Centers for Disease Control and Prevention / Agency for Toxic Substances "
        "and Disease Registry, Geospatial Research, Analysis and Services Program. "
        "CDC/ATSDR Social Vulnerability Index 2022 Database — Arizona."
    ),
    licence="US federal government work, public domain.",
    role=(
        "Tract population and the social vulnerability components: residents aged "
        "65+, below 150% of poverty, without a vehicle, with a disability, and "
        "uninsured, plus CDC's own overall percentile ranking."
    ),
)

MARICOPA_TRACT_GEOMETRY = DataSource(
    key="tracts_maricopa_2020",
    name="Census TIGERweb census tract boundaries — Maricopa County, AZ",
    url=_tigerweb_tracts_url(),
    filename="tracts_maricopa.geojson",
    citation="US Census Bureau, TIGERweb REST Services, Tracts_Blocks MapServer.",
    licence="US federal government work, public domain.",
    role="Tract polygons used to assign each FortyGuard heat tile to a tract.",
)

LODES_ARIZONA_WAC = DataSource(
    key="lodes8_az_wac_2021",
    name="LEHD LODES8 Workplace Area Characteristics — Arizona, 2021",
    url="https://lehd.ces.census.gov/data/lodes/LODES8/az/wac/az_wac_S000_JT00_2021.csv.gz",
    filename="az_wac_S000_JT00_2021.csv.gz",
    citation=(
        "US Census Bureau. LEHD Origin-Destination Employment Statistics (LODES8), "
        "Workplace Area Characteristics, Arizona, 2021."
    ),
    licence="US federal government work, public domain.",
    role=(
        "Jobs by NAICS sector at the workplace, aggregated to tract, to locate "
        "outdoor-exposed workers where they actually work during the day rather "
        "than where they sleep."
    ),
)

def _hrn_sites_url() -> str:
    """Build the Heat Relief Network query returning every site as GeoJSON.

    The service is the *current* season's network. It carries no historical
    snapshots, which constrains what can honestly be claimed — see the note on
    ``HEAT_RELIEF_NETWORK.role``.
    """
    base = (
        "https://services1.arcgis.com/MdyCMZnX1raZ7TS3/arcgis/rest/services/"
        "HRN_Public_view/FeatureServer/0/query"
    )
    params = {
        "where": "1=1",
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


HEAT_RELIEF_NETWORK = DataSource(
    key="hrn_maricopa_current",
    name="Maricopa Heat Relief Network — cooling, respite and hydration sites",
    url=_hrn_sites_url(),
    filename="hrn_sites.geojson",
    citation=(
        "Maricopa Association of Governments and Maricopa County Department of "
        "Public Health. Heat Relief Network public site layer (hrn.azmag.gov), "
        "HRN_Public_view feature service."
    ),
    licence="Published for public use by a regional government body.",
    role=(
        "Cooling-centre supply: site locations, type, per-weekday opening hours and "
        "accessibility. IMPORTANT: the service publishes only the CURRENT season "
        "(2026), not historical snapshots. It therefore cannot describe what was "
        "open during the 2024 study episode, and is used to ask 'where would "
        "today's network leave gaps during a heat event like that one' — never to "
        "claim what the county actually operated in 2024."
    ),
)

def _heat_deaths_zip_url() -> str:
    """Build the query returning 2022 heat deaths by ZIP as GeoJSON."""
    base = (
        "https://services.arcgis.com/ykpntM6e3tHvzKRJ/arcgis/rest/services/"
        "HeatdeathsbyzipcodeinMaricopaCounty2022/FeatureServer/0/query"
    )
    params = {
        "where": "1=1",
        "outFields": "ZipCode,HeatDeaths",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


HEAT_DEATHS_BY_ZIP_2022 = DataSource(
    key="heat_deaths_zip_2022",
    name="Heat-associated deaths by ZIP code, Maricopa County, 2022",
    url=_heat_deaths_zip_url(),
    filename="heat_deaths_zip_2022.geojson",
    citation=(
        "Maricopa County Department of Public Health, heat mortality surveillance. "
        "Published as the 'Heat deaths by zip code in Maricopa County (2022)' "
        "feature service."
    ),
    licence="Published for public use by a county public health department.",
    role=(
        "The independent outcome measure used to validate CityVigil's ranking. "
        "Counts below the disclosure threshold are suppressed with -999, so 118 of "
        "142 ZIPs are censored; the data supports a 'did this ZIP record at least "
        "6 heat deaths' test, not a continuous death-rate regression."
    ),
)

def _heat_deaths_2023_url() -> str:
    """Build the query returning 2023 heat deaths by ZIP as GeoJSON."""
    base = (
        "https://services.arcgis.com/ykpntM6e3tHvzKRJ/ArcGIS/rest/services/"
        "HeatReportMap2023/FeatureServer/0/query"
    )
    params = {
        "where": "1=1",
        "outFields": "ZipCode,CommunityN,Count_",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "geojson",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


HEAT_DEATHS_BY_ZIP_2023 = DataSource(
    key="heat_deaths_zip_2023",
    name="Heat-associated deaths by ZIP code, Maricopa County, 2023",
    url=_heat_deaths_2023_url(),
    filename="heat_deaths_zip_2023.geojson",
    citation=(
        "Maricopa County Department of Public Health, 2023 heat surveillance report "
        "map. Published as the 'HeatReportMap2023' feature service."
    ),
    licence="Published for public use by a county public health department.",
    role=(
        "The primary validation outcome. Unlike the 2022 ZIP release, counts here are "
        "NOT suppressed: 139 ZIPs carry actual values totalling 565 deaths, with real "
        "zeros. That supports rank correlation and bootstrap confidence intervals "
        "rather than only a binary above-threshold test, which is what made the 2022 "
        "result statistically weak. Provenance cross-checked against the 2022 release: "
        "the same ZIPs lead both years, counts are uniformly higher in 2023 (Maricopa's "
        "record year), and the two rank-correlate at 0.495 across ZIPs published in "
        "both."
    ),
)

SOURCES: dict[str, DataSource] = {
    s.key: s
    for s in (
        SVI_ARIZONA,
        MARICOPA_TRACT_GEOMETRY,
        LODES_ARIZONA_WAC,
        HEAT_RELIEF_NETWORK,
        HEAT_DEATHS_BY_ZIP_2022,
        HEAT_DEATHS_BY_ZIP_2023,
    )
}


# --------------------------------------------------------------------- fetching


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(data_dir: Path = DEFAULT_DATA_DIR) -> dict:
    """Read the provenance manifest, or an empty one."""
    path = Path(data_dir) / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_manifest(entries: dict, data_dir: Path) -> None:
    path = Path(data_dir) / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")


def _record(source: DataSource, target: Path, data_dir: Path) -> None:
    """Record (or refresh) the provenance entry describing the file on disk."""
    manifest = load_manifest(data_dir)
    manifest[source.key] = {
        "name": source.name,
        "url": source.url,
        "filename": source.filename,
        "bytes": target.stat().st_size,
        "sha256": _sha256(target),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "citation": source.citation,
        "licence": source.licence,
        "role": source.role,
    }
    _write_manifest(manifest, data_dir)


def fetch(
    source: DataSource,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    force: bool = False,
    timeout: float = 300.0,
) -> Path:
    """Download ``source`` if absent, record its provenance, return its path.

    Provenance is recorded for files already on disk too, not just fresh
    downloads. The manifest is meant to describe the bytes a result was computed
    from, and a file staged by hand or restored from the repository needs
    describing just as much as one pulled over the wire.

    :raises SourceError: on any transport failure or an empty response.
    """
    target = source.path(data_dir)
    if target.is_file() and not force:
        if source.key not in load_manifest(data_dir):
            _record(source, target, data_dir)
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    try:
        request = urllib.request.Request(
            source.url, headers={"User-Agent": "CityVigil/0.1 (hackathon project)"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response, tmp.open("wb") as fh:
            while chunk := response.read(1 << 20):
                fh.write(chunk)
    except Exception as exc:  # noqa: BLE001 - any failure is a source failure
        tmp.unlink(missing_ok=True)
        raise SourceError(f"could not fetch {source.key} from {source.url}: {exc}") from exc

    if tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise SourceError(f"{source.key} returned an empty response")

    tmp.replace(target)
    _record(source, target, data_dir)
    return target


def fetch_all(*, data_dir: Path = DEFAULT_DATA_DIR, force: bool = False) -> dict[str, Path]:
    """Fetch every declared source. Returns ``{key: path}``."""
    return {key: fetch(src, data_dir=data_dir, force=force) for key, src in SOURCES.items()}


def citations() -> list[str]:
    """Every citation, for the README and the briefing footer."""
    return [f"{s.name}. {s.citation} {s.licence}" for s in SOURCES.values()]
