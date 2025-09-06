import sys
from pathlib import Path

import config
import Pinnacle_Scraper
import google_sheets_sync
import odds_sync

# Allow importing sync scripts from repository root
sys.path.append(str(Path(__file__).resolve().parent.parent))
import clv_sync

def hybrid_main():
    print("Starting Pinnacle scraper...")
    Pinnacle_Scraper.main()

    if getattr(config, "ENABLE_BETONLINE", False):
        try:
            print("Starting BetOnline scraper...")
            import BetOnline_Scraper
            BetOnline_Scraper.main()
        except Exception as e:
            print(f"[WARN] BetOnline step skipped: {e}")
    else:
        print("[INFO] BetOnline disabled via config.")

    print("Syncing CSV data to Google Sheets...")
    google_sheets_sync.partial_update_google_sheets()

    print("Refreshing Live/Detailed Odds from The Odds API...")
    odds_sync.main()

    print("Updating Closing Line & CLV%...")
    clv_sync.main()

if __name__ == "__main__":
    hybrid_main()
