"""Content-addressed response cache.

Serves three purposes, in order of importance:

1. **Judges can run the project with no API key.** Cached responses are committed
   to the repo, so ``CITYVIGIL_CACHE_MODE=replay`` reproduces every figure in the
   submission offline. The official quickstart does the same thing for its parcel
   notebooks, and it is the difference between a demo that works on someone
   else's machine and one that does not.
2. **Reproducibility.** A backtest that silently re-queries the API is not a
   backtest. Pinning responses pins the evidence.
3. **Credits.** Heatmaps over a tiled city are the dominant cost.

The key is a digest of the endpoint plus the exact payload, so any change to the
question asked produces a different key. There is deliberately no expiry:
historical temperature data does not change, and for near-real-time windows the
caller should use ``refresh`` mode rather than rely on a TTL heuristic.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Literal

from .errors import CacheMiss, ConfigError

CacheMode = Literal["live", "replay", "refresh"]
VALID_MODES: tuple[str, ...] = ("live", "replay", "refresh")


def canonical_digest(endpoint: str, payload: Any) -> str:
    """Return a stable short digest for an ``(endpoint, payload)`` pair.

    ``sort_keys`` makes the digest independent of dict ordering, so a payload
    rebuilt in a different field order still hits the same cache entry.
    """
    blob = json.dumps(
        {"endpoint": endpoint, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


class ResponseCache:
    """A directory of JSON responses keyed by request digest.

    Parameters
    ----------
    directory:
        Where entries live. Created on demand.
    mode:
        ``live`` reads cache then falls back to the API and stores the result;
        ``replay`` never calls the API and raises :class:`CacheMiss` on a miss;
        ``refresh`` ignores existing entries and overwrites them.
    """

    def __init__(self, directory: str | Path, mode: CacheMode = "live") -> None:
        if mode not in VALID_MODES:
            raise ConfigError(f"cache mode must be one of {VALID_MODES}, got {mode!r}")
        self.directory = Path(directory)
        self.mode: CacheMode = mode
        self.hits = 0
        self.misses = 0
        self.writes = 0

    # ------------------------------------------------------------------ paths

    def path_for(self, endpoint: str, payload: Any) -> Path:
        """Return the on-disk path for a request, namespaced by endpoint.

        Entries are gzipped. A city-scale heatmap response is ~5 MB of JSON that
        is mostly repeated coordinate digits, and it compresses by roughly 10x.
        Since the cache is committed so the project replays without a key, that
        difference decides whether the repository is practical to clone.
        """
        digest = canonical_digest(endpoint, payload)
        slug = endpoint.strip("/").replace("/", "_") or "root"
        return self.directory / slug / f"{digest}.json.gz"

    def _legacy_path_for(self, endpoint: str, payload: Any) -> Path:
        """Path used before entries were compressed. Still read, never written."""
        return self.path_for(endpoint, payload).with_suffix("").with_suffix(".json")

    @staticmethod
    def _read_entry(path: Path) -> dict:
        """Load an entry, transparently handling gzipped and plain JSON."""
        try:
            if path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8") as fh:
                    return json.load(fh)
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, EOFError) as exc:
            raise ConfigError(f"corrupt cache entry {path}: {exc}") from exc

    # ------------------------------------------------------------------- read

    def get(self, endpoint: str, payload: Any) -> dict | None:
        """Return a cached response, or ``None`` if it should not be used.

        In ``refresh`` mode this always returns ``None``. In ``replay`` mode a
        miss raises :class:`CacheMiss`, because silently falling through to a
        live call would defeat the point of replay.
        """
        if self.mode == "refresh":
            return None

        for path in (self.path_for(endpoint, payload), self._legacy_path_for(endpoint, payload)):
            if path.is_file():
                entry = self._read_entry(path)
                self.hits += 1
                return entry.get("response")

        self.misses += 1
        if self.mode == "replay":
            raise CacheMiss(
                f"replay mode: no cached response for {endpoint} "
                f"(digest {canonical_digest(endpoint, payload)}). Re-run with "
                f"CITYVIGIL_CACHE_MODE=live to fetch it."
            )
        return None

    # ------------------------------------------------------------------ write

    def put(
        self,
        endpoint: str,
        payload: Any,
        response: Any,
        *,
        meta: dict | None = None,
    ) -> Path:
        """Store a response together with the payload that produced it.

        The payload is stored alongside deliberately: an opaque hash-named file is
        useless during review, whereas one that states the exact question asked is
        auditable evidence.
        """
        path = self.path_for(endpoint, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "endpoint": endpoint,
            "payload": payload,
            "response": response,
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "meta": meta or {},
        }
        tmp = path.with_name(path.name + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(entry, fh, default=str)
        os.replace(tmp, path)  # atomic, so a crash cannot leave a half-written entry
        self.writes += 1
        return path

    # ------------------------------------------------------------------ stats

    def stats(self) -> dict[str, Any]:
        """Return counters for the run, for reporting alongside credit usage."""
        return {
            "mode": self.mode,
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "directory": str(self.directory),
        }
