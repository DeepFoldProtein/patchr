"""Server configuration: paths and env-derived constants, plus sys.path wiring so
the bundled boltz source (``<repo>/src``) is importable. Imported early (before any
boltz import) by server.py. Values are read once from the environment; the container
sets PATCHR_WORK_DIR etc., so they are treated as immutable for the process.
"""

import os
import sys
from pathlib import Path

# Repo root = parent of this server/ package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Job scratch (shared across replicas behind the LB).
WORK_DIR = Path(os.environ.get("PATCHR_WORK_DIR", "./patchr_jobs"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

# GPU device pin (per-replica) and GPU queue depth.
DEFAULT_DEVICE_ID = os.environ.get("PATCHR_DEVICE_ID") or os.environ.get("BOLTZ_DEVICE_ID")
GPU_QUEUE_MAX = int(os.environ.get("PATCHR_GPU_QUEUE_MAX", "4"))
