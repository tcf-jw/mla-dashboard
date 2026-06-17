"""One-off full-history backfill. Equivalent to `python -m mla_dashboard.refresh --backfill`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mla_dashboard.refresh import run  # noqa: E402

if __name__ == "__main__":
    run(backfill=True)
