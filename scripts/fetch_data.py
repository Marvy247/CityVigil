"""Download the external datasets CityVigil depends on.

    python3 scripts/fetch_data.py

Writes to ``data/sources/`` along with a ``manifest.json`` recording each file's
URL, size, SHA-256 and retrieval time. All three sources are US federal public
domain works, so they can be committed and redistributed with the project.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cityvigil.sources import DEFAULT_DATA_DIR, SOURCES, fetch, load_manifest  # noqa: E402
from cityvigil.tracts import load_tracts  # noqa: E402


def main() -> int:
    force = "--force" in sys.argv
    print(f"Fetching {len(SOURCES)} sources into {DEFAULT_DATA_DIR}/\n")

    for key, source in SOURCES.items():
        target = source.path(DEFAULT_DATA_DIR)
        existed = target.is_file() and not force
        path = fetch(source, data_dir=DEFAULT_DATA_DIR, force=force)
        size_mb = path.stat().st_size / 1e6
        print(f"  [{'cached' if existed else 'downloaded'}] {key}")
        print(f"      {source.name}")
        print(f"      {size_mb:.2f} MB -> {path}")
        print(f"      role: {source.role}")
        print()

    manifest = load_manifest(DEFAULT_DATA_DIR)
    print("Provenance manifest:")
    for key, entry in sorted(manifest.items()):
        print(f"  {key}: sha256 {entry['sha256'][:16]}… {entry['bytes']:,} bytes")

    print("\nBuilding tract collection…")
    tracts = load_tracts(data_dir=DEFAULT_DATA_DIR, download=False)
    print(json.dumps(tracts.summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
