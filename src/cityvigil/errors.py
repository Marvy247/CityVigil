"""Exception hierarchy for CityVigil.

Split deliberately into *our* faults (validation, config, cache) and *their*
faults (task failure, timeout, transport), because the two demand different
responses from the agent loop: a ValidationError means re-plan the request, a
TaskFailedError means retry or degrade.
"""

from __future__ import annotations


class CityVigilError(Exception):
    """Base class for every error raised by this package."""


# --------------------------------------------------------------- our problems


class ConfigError(CityVigilError):
    """Missing or malformed configuration (no API key, bad cache mode, ...)."""


class ValidationError(CityVigilError):
    """A request was rejected pre-flight, before any credits were spent.

    Raised by :mod:`cityvigil.guards`. Carries the offending field so the agent
    loop can decide what to change rather than blindly retrying.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class UnitError(CityVigilError):
    """Temperature units could not be established unambiguously.

    Deliberately fatal. The FortyGuard API takes ``threshold`` in Celsius while
    tile readings have been observed in Celsius in sample payloads and documented
    as Fahrenheit; silently guessing is how you get a confident wrong answer.
    """


class CacheMiss(CityVigilError):
    """Replay mode was requested but the response is not in the cache."""


# ------------------------------------------------------------- their problems


class TransportError(CityVigilError):
    """Network-level failure that survived all retries."""


class APIError(CityVigilError):
    """The API returned a non-OK status or an error envelope."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ActivityNotReady(CityVigilError):
    """Status endpoint 404s while the activity propagates. Retryable, not fatal."""

    def __init__(self, activity_id: str) -> None:
        super().__init__(f"activity {activity_id} is not queryable yet")
        self.activity_id = activity_id


class TaskFailed(CityVigilError):
    """The async task reached a terminal failure state. No credits charged."""

    def __init__(self, activity_id: str, detail: str = "") -> None:
        super().__init__(f"activity {activity_id} failed: {detail or 'no detail given'}")
        self.activity_id = activity_id
        self.detail = detail


class TaskTimeout(CityVigilError):
    """The async task did not terminate within the allotted wall-clock budget."""

    def __init__(self, activity_id: str, waited: float, last_status: str = "") -> None:
        super().__init__(
            f"activity {activity_id} still {last_status or 'unfinished'!r} "
            f"after {waited:.0f}s"
        )
        self.activity_id = activity_id
        self.waited = waited
        self.last_status = last_status
