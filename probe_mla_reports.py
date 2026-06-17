"""One-off script: probe unconfigured MLA API report IDs to discover what data they hold.

Run this on a machine with internet access:
    python probe_mla_reports.py

It tries report IDs 1-20 (skipping the ones we already use) and prints a sample of each
response so you can see what's there. 90CL / manufacturing beef prices should stand out.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from mla_dashboard.client import MLAClient, MLAApiError  # noqa: E402

KNOWN = {1, 2, 3, 4, 5, 7, 10}  # already configured
PROBE_IDS = [i for i in range(1, 21) if i not in KNOWN]

client = MLAClient()

for rid in PROBE_IDS:
    try:
        rows = client.get_all(rid, {"fromDate": "2024-01-01", "toDate": "2024-03-31", "page": 1})
        if not rows:
            print(f"Report {rid:>2}: empty (no data for that date range)")
            continue
        keys = list(rows[0].keys())
        sample = rows[0]
        # Look for any key that contains "CL", "lean", "grind", "manuf", "trim", "90"
        interesting = any(
            any(kw in str(v).lower() or kw in k.lower()
                for kw in ("90", "cl", "lean", "grind", "manuf", "trim", "process"))
            for k, v in sample.items()
        )
        flag = "  *** LOOKS INTERESTING ***" if interesting else ""
        print(f"Report {rid:>2}: {len(rows)} rows   keys={keys}{flag}")
        print(f"          sample: {sample}")
    except MLAApiError as e:
        print(f"Report {rid:>2}: API error — {e}")
    except Exception as e:
        print(f"Report {rid:>2}: {type(e).__name__}: {e}")
    print()
    time.sleep(1)  # polite delay
