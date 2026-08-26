"""Run the CityVigil API for local development.

    python3 scripts/serve.py

Binds to 127.0.0.1 deliberately: the process holds a FortyGuard API key and has
no authentication, so it must not be reachable from the network. See the security
note in ``cityvigil.api``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("cityvigil.api:app", host="127.0.0.1", port=8000, reload=False)
