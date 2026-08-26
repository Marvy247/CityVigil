"""Configuration, loaded from the environment.

Reads ``.env`` if :mod:`python-dotenv` is installed, but does not require it, so
the package works in a bare container with plain environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .cache import VALID_MODES, CacheMode
from .errors import ConfigError

DEFAULT_BASE_URL = "https://api.fortyguard.com"


def load_dotenv_if_present(path: str | Path = ".env") -> None:
    """Load ``.env`` into the environment when python-dotenv is available.

    Silently does nothing if the library or the file is absent — a caller that
    exports real environment variables should not be forced to install it.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    target = Path(path)
    if target.is_file():
        load_dotenv(target, override=False)


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    api_key: str | None
    base_url: str = DEFAULT_BASE_URL
    cache_dir: Path = Path("data/cache")
    cache_mode: CacheMode = "live"
    plan: str = "hackathon"
    timeout: float = 60.0

    @classmethod
    def from_env(cls, *, dotenv_path: str | Path = ".env") -> "Settings":
        """Build settings from environment variables, loading ``.env`` first."""
        load_dotenv_if_present(dotenv_path)

        mode = (os.getenv("CITYVIGIL_CACHE_MODE") or "live").strip().lower()
        if mode not in VALID_MODES:
            raise ConfigError(
                f"CITYVIGIL_CACHE_MODE must be one of {VALID_MODES}, got {mode!r}"
            )

        base = (os.getenv("FORTYGUARD_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")

        return cls(
            api_key=(os.getenv("FORTYGUARD_API_KEY") or "").strip() or None,
            base_url=base,
            cache_dir=Path((os.getenv("CITYVIGIL_CACHE_DIR") or "data/cache").strip()),
            cache_mode=mode,  # type: ignore[arg-type]
            plan=(os.getenv("CITYVIGIL_PLAN") or "hackathon").strip().lower(),
            timeout=float(os.getenv("CITYVIGIL_HTTP_TIMEOUT") or 60.0),
        )

    def require_api_key(self) -> str:
        """Return the API key, or explain precisely how to supply one."""
        if not self.api_key:
            raise ConfigError(
                "No FortyGuard API key. Copy .env.example to .env and set "
                "FORTYGUARD_API_KEY, or run in replay mode "
                "(CITYVIGIL_CACHE_MODE=replay) to use committed responses."
            )
        return self.api_key
