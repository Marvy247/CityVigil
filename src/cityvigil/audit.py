"""Audit trail.

The submission is judged in part on explaining which FortyGuard layers and
endpoints drove each decision. Rather than reconstructing that narrative at the
end, every call and every choice is recorded here as it happens, from the first
API request onward. The trail is the product, not documentation of the product.

Design notes
------------
* Records are append-only and JSON-serialisable, so the trail can be shipped
  straight to the UI or written next to an export.
* A layer choice records its *rationale* as a required field. If a caller cannot
  articulate why ``exceedance`` rather than ``tcm``, that is precisely the
  reasoning gap the organisers warned about.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal

RecordKind = Literal["api_call", "layer_choice", "decision", "guard_rejection", "note"]


@dataclass(frozen=True)
class AuditRecord:
    """One entry in the trail."""

    kind: RecordKind
    summary: str
    at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLog:
    """Append-only, JSON-serialisable record of everything the system did."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    # ---------------------------------------------------------------- writing

    def record(self, kind: RecordKind, summary: str, **detail: Any) -> AuditRecord:
        """Append a record and return it."""
        entry = AuditRecord(kind=kind, summary=summary, detail=detail)
        self._records.append(entry)
        return entry

    def api_call(
        self,
        endpoint: str,
        *,
        payload_digest: str,
        cached: bool,
        activity_id: str | None = None,
        duration_s: float | None = None,
        analytic_type: str | None = None,
        units: str | None = None,
        n_cells: int | None = None,
        **extra: Any,
    ) -> AuditRecord:
        """Record a call to the FortyGuard API, cached or live."""
        source = "cache" if cached else "live"
        label = f"{endpoint}" + (f" [{analytic_type}]" if analytic_type else "")
        return self.record(
            "api_call",
            f"{label} via {source}",
            endpoint=endpoint,
            payload_digest=payload_digest,
            cached=cached,
            activity_id=activity_id,
            duration_s=None if duration_s is None else round(duration_s, 2),
            analytic_type=analytic_type,
            units=units,
            n_cells=n_cells,
            **extra,
        )

    def layer_choice(
        self, analytic_type: str, *, question: str, rationale: str, **params: Any
    ) -> AuditRecord:
        """Record *why* a given analysis layer was selected.

        ``rationale`` is mandatory by design — see the module docstring.
        """
        if not rationale.strip():
            raise ValueError("a layer choice requires a non-empty rationale")
        return self.record(
            "layer_choice",
            f"chose {analytic_type} for: {question}",
            analytic_type=analytic_type,
            question=question,
            rationale=rationale,
            params=params,
        )

    def guard_rejection(self, field_name: str | None, message: str) -> AuditRecord:
        """Record a request rejected pre-flight, before any credits were spent."""
        return self.record(
            "guard_rejection",
            f"rejected before send ({field_name or 'unknown field'})",
            field=field_name,
            message=message,
        )

    def decision(self, summary: str, **detail: Any) -> AuditRecord:
        """Record an allocation or prioritisation decision."""
        return self.record("decision", summary, **detail)

    def note(self, summary: str, **detail: Any) -> AuditRecord:
        """Record free-form context worth surfacing in the trail."""
        return self.record("note", summary, **detail)

    # ---------------------------------------------------------------- reading

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[AuditRecord]:
        return iter(self._records)

    @property
    def records(self) -> list[AuditRecord]:
        """A copy of the trail, oldest first."""
        return list(self._records)

    def of_kind(self, kind: RecordKind) -> list[AuditRecord]:
        """Every record of one kind."""
        return [r for r in self._records if r.kind == kind]

    def endpoints_used(self) -> dict[str, int]:
        """Call counts per endpoint, for the "how we used the API" section."""
        counts: dict[str, int] = {}
        for r in self.of_kind("api_call"):
            key = str(r.detail.get("endpoint", "?"))
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    def layers_used(self) -> dict[str, int]:
        """Call counts per analysis layer."""
        counts: dict[str, int] = {}
        for r in self.of_kind("api_call"):
            key = r.detail.get("analytic_type")
            if key:
                counts[str(key)] = counts.get(str(key), 0) + 1
        return dict(sorted(counts.items()))

    def to_list(self) -> list[dict[str, Any]]:
        """The whole trail as plain dicts."""
        return [r.to_dict() for r in self._records]

    def write_json(self, path: str | Path) -> Path:
        """Write the trail to ``path``, creating parent directories."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "records": self.to_list(),
                    "endpoints_used": self.endpoints_used(),
                    "layers_used": self.layers_used(),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return target

    def render_text(self) -> str:
        """A compact human-readable rendering, for CLI output and briefings."""
        lines = []
        for r in self._records:
            lines.append(f"[{r.at}] {r.kind:<16} {r.summary}")
            if r.kind == "layer_choice":
                lines.append(f"{'':>22}why: {r.detail.get('rationale')}")
        return "\n".join(lines)
