import config
import Pinnacle_Scraper
import google_sheets_sync
import odds_sync
import clv_sync

def hybrid_main():
    print("Starting Pinnacle scraper...")
    Pinnacle_Scraper.main()

    try:
        if getattr(config, "ENABLE_BETONLINE", False):
            import BetOnline_Scraper
            print("Starting BetOnline scraper...")
            BetOnline_Scraper.main()
    except Exception as e:
        print(f"[WARN] BetOnline step skipped: {e}")

    print("Syncing CSV data to Google Sheets...")
    google_sheets_sync.partial_update_google_sheets()

    print("Refreshing Live/Detailed Odds from The Odds API...")
    odds_sync.main()

    print("Updating Closing Line & CLV%...")
    clv_sync.sync_clv()

if __name__ == "__main__":
    hybrid_main()
