import Pinnacle_Scraper
import google_sheets_sync
import config


def hybrid_main():
    print("Starting Pinnacle scraper...")
    Pinnacle_Scraper.main()

    print("Syncing CSV data to Google Sheets...")
    google_sheets_sync.partial_update_google_sheets()

    # Optional CLV pass (requires LIVE_ODDS_SHEET_ID)
    live_ok = getattr(config, "LIVE_ODDS_SHEET_ID", "").strip() != ""
    if live_ok:
        try:
            print("Updating Closing Line & CLV% from Live Odds...")
            import clv_sync
            clv_sync.sync_clv()
        except Exception as e:
            print(f"[WARN] CLV sync skipped: {e}")
    else:
        print("[INFO] LIVE_ODDS_SHEET_ID not set; skipping CLV sync.")


if __name__ == "__main__":
    hybrid_main()

