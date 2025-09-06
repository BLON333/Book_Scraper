# Thin wrapper to run the canonical sync (with Event-ID backfill)
import runpy, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(BASE, "Python Project Folder", "google_sheets_sync.py")

# Ensure we can import the project's config and modules
sys.path.insert(0, os.path.join(BASE, "Python Project Folder"))

runpy.run_path(TARGET, run_name="__main__")
