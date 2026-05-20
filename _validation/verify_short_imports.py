"""Verify all __init__.py short imports work after T-015."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

checks = [
    ("csv_dashboard.charts",      "generate_charts"),
    ("csv_dashboard.quality",     "run"),
    ("csv_dashboard.profiling",   "profile_dataframe"),
    ("csv_dashboard.insights",    "ChartSpec"),
    ("csv_dashboard.insights",    "ChartSpecList"),
    ("csv_dashboard.transparency","build"),
    ("csv_dashboard.transparency","show_in_streamlit"),
    ("csv_dashboard.ingestion",   "load_csv"),
    ("csv_dashboard.ingestion",   "FileLoadError"),
]

all_ok = True
for module, name in checks:
    try:
        mod = __import__(module, fromlist=[name])
        obj = getattr(mod, name)
        print(f"  OK  from {module} import {name}")
    except Exception as e:
        print(f"  FAIL  from {module} import {name}  →  {e}")
        all_ok = False

print()
print("PASS" if all_ok else "FAIL — see above")
sys.exit(0 if all_ok else 1)
