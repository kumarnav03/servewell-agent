"""CLI: chunk + embed the KB into storage/chroma.

Usage: uv run python scripts/build_index.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from servewell.ingest.build_index import build_index  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(build_index(), indent=2))
