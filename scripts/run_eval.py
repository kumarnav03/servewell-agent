"""CLI: run the Printers pilot evaluation. Usage: uv run python scripts/run_eval.py"""

import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
runpy.run_module("servewell.evaluation.run_eval", run_name="__main__")
