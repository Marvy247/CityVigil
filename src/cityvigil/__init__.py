"""CityVigil — autonomous protective intelligence for extreme heat.

Phase 1 (foundation) public surface. See ``PLAN.md`` for the full roadmap.
"""

from __future__ import annotations

from .audit import AuditLog, AuditRecord
from .cache import ResponseCache, canonical_digest
from .config import Settings
from .errors import (
    APIError,
    ActivityNotReady,
    CacheMiss,
    CityVigilError,
    ConfigError,
    TaskFailed,
    TaskTimeout,
    TransportError,
    UnitError,
    ValidationError,
)
from .fg_client import FortyGuardClient
from .geometry import GridIndex, MultiPolygon, Polygon, haversine_km, ring_area_km2
from .layers import (
    LAYER_GUIDE,
    TIME_OF_MEASURE_NOTE,
    ExposureLayers,
    HeatSurface,
    Tile,
    explain_layer_choice,
    parse_surface,
)
from .supply import CoolingSite, coverage_for_tracts, load_sites, open_site_count_by_hour
from .tracts import Tract, TractCollection, load_tracts
from .units import api_threshold_celsius, c_to_f, f_to_c, infer_tile_unit
from .validation import auc, load_zip_outcomes, validate
from .vulnerability import VulnerabilityModel, Weights

__version__ = "0.1.0"

__all__ = [
    "AuditLog",
    "AuditRecord",
    "ResponseCache",
    "canonical_digest",
    "Settings",
    "FortyGuardClient",
    "ExposureLayers",
    "HeatSurface",
    "Tile",
    "LAYER_GUIDE",
    "TIME_OF_MEASURE_NOTE",
    "explain_layer_choice",
    "parse_surface",
    "GridIndex",
    "MultiPolygon",
    "Polygon",
    "haversine_km",
    "ring_area_km2",
    "Tract",
    "TractCollection",
    "load_tracts",
    "VulnerabilityModel",
    "Weights",
    "CoolingSite",
    "load_sites",
    "coverage_for_tracts",
    "open_site_count_by_hour",
    "auc",
    "validate",
    "load_zip_outcomes",
    "api_threshold_celsius",
    "c_to_f",
    "f_to_c",
    "infer_tile_unit",
    "CityVigilError",
    "ConfigError",
    "ValidationError",
    "UnitError",
    "CacheMiss",
    "TransportError",
    "APIError",
    "ActivityNotReady",
    "TaskFailed",
    "TaskTimeout",
    "__version__",
]
