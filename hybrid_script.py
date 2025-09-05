import subprocess, sys
from pathlib import Path
from core.logging_utils import info, ok, warn
import config


def main() -> None:
    info("=== Pipeline start ===")
    # 1) Pinnacle
    if Path("Pinnacle_Scraper.py").exists():
        try:
            subprocess.run([sys.executable, "Pinnacle_Scraper.py"], check=True)
            ok("Pinnacle_Scraper")
        except subprocess.CalledProcessError as e:
            warn(f"Pinnacle_Scraper failed: {e}")
    else:
        warn("Pinnacle_Scraper.py not found in repo root; skipping Pinnacle scrape.")
    # 2) BetOnline: scraper or CSV merge
    if config.ENABLE_BETONLINE:
        if Path("BetOnline_Scraper.py").exists():
            try:
                subprocess.run([sys.executable, "BetOnline_Scraper.py"], check=True)
                ok("BetOnline_Scraper")
            except subprocess.CalledProcessError as e:
                warn(f"BetOnline_Scraper failed: {e}")
        else:
            warn("BetOnline_Scraper.py not found; skipping BetOnline scrape.")
    else:
        subprocess.run([sys.executable, "import_betonline_csv.py"], check=False)
    # 3) Sync bets to Sheets
    subprocess.run([sys.executable, "google_sheets_sync.py"], check=True)
    # 4) Odds → Live & Detailed
    subprocess.run([sys.executable, "odds_sync.py"], check=True)
    # 5) CLV → write back
    subprocess.run([sys.executable, "clv_sync.py"], check=True)
    info("=== Pipeline end ===")


if __name__ == "__main__":
    main()

