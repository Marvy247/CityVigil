"""FortyGuard Temperature API client.

Differences from the official quickstart client, all of them deliberate:

* **Guards run first.** A malformed request is rejected locally with the offending
  field named, before it can return a plausible answer to the wrong question.
* **Caching is built in.** Responses are content-addressed on disk, so the whole
  project replays offline with no key and no credits.
* **Every call is audited.** Endpoint, layer, payload digest, cache status,
  activity id and duration land in an :class:`~cityvigil.audit.AuditLog` as they
  happen.
* **Retries are explicit.** Transport failures and 5xx/429 responses back off and
  retry; task failures do not (they are free, but they are also deterministic).
* **Units are never guessed.** Thresholds are converted to Celsius at the
  boundary, and tile readings are checked for credibility on the way out.

Verified API behaviour this is built against
-------------------------------------------
``POST /v1/<endpoint>`` returns ``{"data": {"activity_id": ...}}``; progress is
read from ``GET /v1/status/{activity_id}`` which may 404 briefly right after
submission; terminal states are ``Completed``/``succeeded`` and ``failed``/
``error``; credits are charged only on completion. Confirmed live against
``api.fortyguard.com`` on a Phoenix AOI, which also established that ``tcm`` tile
readings are **Celsius** despite the quickstart docstring describing Fahrenheit.
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

import requests

from .audit import AuditLog
from .cache import ResponseCache, canonical_digest
from .config import Settings
from .errors import (
    ActivityNotReady,
    APIError,
    TaskFailed,
    TaskTimeout,
    TransportError,
    ValidationError,
)
from .guards import (
    ANALYTIC_TYPES,
    canonical_aoi,
    validate_aoi,
    validate_analytic,
    validate_date_time,
    validate_granularity,
)
from .units import Unit, api_threshold_celsius

TERMINAL_SUCCESS = frozenset({"succeeded", "completed", "success"})
TERMINAL_FAILURE = frozenset({"failed", "error", "failure"})

#: Endpoints available only on Premium plans. Kept off the critical path.
PREMIUM_ENDPOINTS = frozenset({"/v1/satellite", "/v1/streetview", "/v1/heat_intelligence"})

AnalyticType = Literal["tcm", "time_of_measure", "exceedance", "persistence"]


class FortyGuardClient:
    """Guarded, cached, audited client for the FortyGuard Temperature API.

    Parameters
    ----------
    settings:
        Resolved configuration. Defaults to :meth:`Settings.from_env`.
    audit:
        Trail to append to. One is created if not supplied.
    cache:
        Response cache. Built from ``settings`` if not supplied.
    session:
        HTTP session. Injectable so tests can run without a network.
    max_retries:
        Attempts for transport errors and retryable status codes.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        audit: AuditLog | None = None,
        cache: ResponseCache | None = None,
        session: Any | None = None,
        max_retries: int = 3,
    ) -> None:
        self.settings = settings or Settings.from_env()
        # `is None` rather than `or`: AuditLog implements __len__, so an empty log
        # is falsy and `audit or AuditLog()` would silently discard the caller's
        # log and record into an orphan. That broke the audit endpoint once.
        self.audit = AuditLog() if audit is None else audit
        self.cache = (
            ResponseCache(self.settings.cache_dir, self.settings.cache_mode)
            if cache is None
            else cache
        )
        self.max_retries = max_retries
        self._session = requests.Session() if session is None else session

        # In replay mode no key is needed: every response comes from disk.
        if self.settings.cache_mode != "replay":
            key = self.settings.require_api_key()
            self._session.headers.update(
                {"api-key": key, "Content-Type": "application/json"}
            )

    # ------------------------------------------------------------- transport

    def _retryable(self, status: int) -> bool:
        return status == 429 or 500 <= status < 600

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue one HTTP request with backoff on transport and 5xx/429 errors."""
        url = f"{self.settings.base_url}{path}"
        kwargs.setdefault("timeout", self.settings.timeout)
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._session.request(method, url, **kwargs)
            except Exception as exc:  # noqa: BLE001 - any transport failure is retryable
                last_error = exc
                if attempt == self.max_retries:
                    raise TransportError(
                        f"{method} {path} failed after {attempt} attempts: {exc}"
                    ) from exc
                self._sleep_backoff(attempt)
                continue

            status = getattr(response, "status_code", 0)
            if self._retryable(status) and attempt < self.max_retries:
                self._sleep_backoff(attempt)
                continue
            return response

        raise TransportError(f"{method} {path} exhausted retries: {last_error}")

    def _sleep_backoff(self, attempt: int) -> None:
        """Exponential backoff with jitter, to avoid synchronised retries."""
        time.sleep(min(2.0 ** (attempt - 1), 8.0) * (0.5 + random.random() / 2))

    @staticmethod
    def _envelope(response: Any, path: str) -> dict:
        """Unwrap the standard ``{"error": ..., "data": ...}`` envelope."""
        status = getattr(response, "status_code", 0)
        if not getattr(response, "ok", False):
            text = getattr(response, "text", "")
            raise APIError(
                f"{path} -> {status}: {text[:400]}", status=status, body=text[:2000]
            )
        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise APIError(f"{path} returned non-JSON body", status=status) from exc
        if isinstance(body, dict) and body.get("error"):
            raise APIError(
                f"{path} returned an error envelope: {body.get('message', body)}",
                status=status,
            )
        return body

    # ------------------------------------------------------- submit and poll

    def submit(self, path: str, payload: dict) -> str:
        """POST a task and return its ``activity_id``."""
        body = self._envelope(self._request("POST", path, json=payload), path)
        data = body.get("data") if isinstance(body, dict) else None
        activity_id = (data or {}).get("activity_id")
        if not activity_id:
            raise APIError(f"{path} response had no data.activity_id: {str(body)[:300]}")
        return str(activity_id)

    def get_status(self, activity_id: str) -> dict:
        """Return the raw status payload, or raise :class:`ActivityNotReady` on 404."""
        path = f"/v1/status/{activity_id}"
        response = self._request("GET", path)
        if getattr(response, "status_code", 0) == 404:
            raise ActivityNotReady(activity_id)
        body = self._envelope(response, path)
        return body.get("data", body) if isinstance(body, dict) else {}

    def wait_for(
        self,
        activity_id: str,
        *,
        poll_interval: float = 3.0,
        timeout: float = 600.0,
        on_tick: Callable[[str, dict], None] | None = None,
    ) -> dict:
        """Poll until the task terminates, returning its ``result`` payload.

        Tolerates the post-submit 404 window rather than treating it as failure.
        """
        started = time.monotonic()
        deadline = started + timeout
        last_status = ""

        while True:
            try:
                data = self.get_status(activity_id)
            except ActivityNotReady:
                last_status = "pending"
                if on_tick:
                    on_tick(last_status, {})
                if time.monotonic() >= deadline:
                    raise TaskTimeout(activity_id, time.monotonic() - started, last_status)
                time.sleep(poll_interval)
                continue

            last_status = str(data.get("status", "")).strip().lower()
            if on_tick:
                on_tick(last_status, data)

            if last_status in TERMINAL_SUCCESS:
                return data.get("result", data)
            if last_status in TERMINAL_FAILURE:
                raise TaskFailed(activity_id, str(data.get("message") or data)[:300])
            if time.monotonic() >= deadline:
                raise TaskTimeout(activity_id, time.monotonic() - started, last_status)
            time.sleep(poll_interval)

    # --------------------------------------------------------- cached calls

    def _run(
        self,
        path: str,
        payload: dict,
        *,
        poll_interval: float,
        timeout: float,
        audit_extra: dict[str, Any] | None = None,
    ) -> dict:
        """Cache-aware submit-and-wait. Returns the ``result`` payload."""
        digest = canonical_digest(path, payload)
        extra = dict(audit_extra or {})

        cached = self.cache.get(path, payload)
        if cached is not None:
            self.audit.api_call(path, payload_digest=digest, cached=True, **extra)
            return cached

        started = time.monotonic()
        activity_id = self.submit(path, payload)
        result = self.wait_for(activity_id, poll_interval=poll_interval, timeout=timeout)
        duration = time.monotonic() - started

        self.cache.put(
            path, payload, result, meta={"activity_id": activity_id, "duration_s": round(duration, 2)}
        )
        self.audit.api_call(
            path,
            payload_digest=digest,
            cached=False,
            activity_id=activity_id,
            duration_s=duration,
            **extra,
        )
        return result

    # -------------------------------------------------------------- heatmap

    def create_heatmap(
        self,
        polygon_aoi: dict,
        *,
        start_date: str,
        filter_type: int,
        analytic_type: AnalyticType = "tcm",
        granularity: int = 100,
        start_time: str | None = None,
        end_time: str | None = None,
        end_date: str | None = None,
        threshold: float | None = None,
        threshold_unit: Unit = "C",
        direction: str | None = None,
        poll_interval: float = 3.0,
        timeout: float = 600.0,
    ) -> dict:
        """``POST /v1/heatmap`` — a thermal or analysis surface over an AOI.

        Analysis layers and what they actually return:

        ``tcm``
            Snapshot temperatures. Tiles carry ``average_temperature`` /
            ``min_temperature`` / ``max_temperature`` in **Celsius** (verified
            live; the quickstart docstring's Fahrenheit claim is incorrect).
        ``time_of_measure``
            UTC hour-of-day 0–23 at which each tile peaks.
        ``exceedance``
            **Count of hours** each tile spends past ``threshold``. Not
            degree-hours — multiplying by population gives person-hours directly.
        ``persistence``
            Longest *continuous* run of such hours, i.e. no-relief duration.

        ``threshold`` may be given in either unit via ``threshold_unit``; it is
        converted to the Celsius value the API requires. ``exceedance`` and
        ``persistence`` require it, the other two forbid it.

        :raises ValidationError: if the request would ask the wrong question.
        """
        if analytic_type not in ANALYTIC_TYPES:
            raise ValidationError(
                f"analytic_type must be one of {ANALYTIC_TYPES}, got {analytic_type!r}",
                field="analytic_type",
            )

        threshold_c = (
            None if threshold is None else api_threshold_celsius(threshold, threshold_unit)
        )

        try:
            validate_analytic(analytic_type, threshold_c, direction)
            validate_granularity(granularity)
            aoi_report = validate_aoi(polygon_aoi, plan=self.settings.plan)
            aoi = canonical_aoi(polygon_aoi)
            date_time = validate_date_time(
                start_date, filter_type, start_time, end_time, end_date
            )
        except ValidationError as exc:
            self.audit.guard_rejection(exc.field, str(exc))
            raise

        payload: dict[str, Any] = {
            "polygon_aoi": aoi,
            "date_time": date_time,
            "granularity": granularity,
            "analytic_type": analytic_type,
        }
        if threshold_c is not None:
            payload["threshold"] = threshold_c
        if direction is not None:
            payload["direction"] = direction

        result = self._run(
            "/v1/heatmap",
            payload,
            poll_interval=poll_interval,
            timeout=timeout,
            audit_extra={
                "analytic_type": analytic_type,
                "granularity_m": granularity,
                "aoi_km2": aoi_report["area_km2"],
                "aoi_region": aoi_report["region"],
                "threshold_c": threshold_c,
                "direction": direction,
                "window": date_time,
            },
        )
        return result

    # ------------------------------------------------------------ env params

    def environmental_parameters(
        self,
        latitude: float,
        longitude: float,
        temperature: float,
        *,
        start_date: str,
        filter_type: int,
        start_time: str | None = None,
        end_time: str | None = None,
        end_date: str | None = None,
        analysis: Iterable[str] | None = None,
        poll_interval: float = 3.0,
        timeout: float = 600.0,
    ) -> dict:
        """``POST /v1/env_params`` — heat index, humidity, air quality, irradiance.

        ``temperature`` is the reference air temperature in Celsius, normally
        taken from a ``tcm`` tile covering this point.
        """
        try:
            date_time = validate_date_time(
                start_date, filter_type, start_time, end_time, end_date
            )
        except ValidationError as exc:
            self.audit.guard_rejection(exc.field, str(exc))
            raise

        payload: dict[str, Any] = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "temperature": float(temperature),
            "date_time": date_time,
        }
        if analysis is not None:
            payload["analysis"] = list(analysis)

        return self._run(
            "/v1/env_params",
            payload,
            poll_interval=poll_interval,
            timeout=timeout,
            audit_extra={"point": [longitude, latitude], "window": date_time},
        )

    # ---------------------------------------------------------------- usage

    def usage(self) -> dict:
        """``POST /v1/system/fetch-api-key-usage`` — plan and credit summary.

        Not an async task and not credit-charged, so it bypasses the cache.
        """
        path = "/v1/system/fetch-api-key-usage"
        key = self.settings.require_api_key()
        body = self._envelope(self._request("POST", path, json={"api_key": key}), path)
        summary = body.get("credit_summary", {}) if isinstance(body, dict) else {}
        self.audit.api_call(
            path,
            payload_digest=canonical_digest(path, {"api_key": "<redacted>"}),
            cached=False,
            credits_remaining=summary.get("cycle_remaining_credits"),
            credits_used=summary.get("cycle_used_credits") or summary.get("cycle_credits_used"),
        )
        return body

    def credits_remaining(self) -> int | None:
        """Remaining credits in the current cycle, or ``None`` if unavailable."""
        try:
            return int(self.usage().get("credit_summary", {}).get("cycle_remaining_credits"))
        except (APIError, TransportError, TypeError, ValueError):
            return None

    # ---------------------------------------------------------------- extras

    def write_audit(self, path: str | Path = "outputs/audit.json") -> Path:
        """Persist the audit trail."""
        return self.audit.write_json(path)

    def run_stats(self) -> dict[str, Any]:
        """Cache counters plus endpoint and layer tallies for this run."""
        return {
            "cache": self.cache.stats(),
            "endpoints_used": self.audit.endpoints_used(),
            "layers_used": self.audit.layers_used(),
            "audit_records": len(self.audit),
        }
