# Thin wrapper to run the canonical sync (with Event-ID backfill)
import runpy, os

BASE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(BASE, "Python Project Folder", "google_sheets_sync.py")

runpy.run_path(TARGET, run_name="__main__")
