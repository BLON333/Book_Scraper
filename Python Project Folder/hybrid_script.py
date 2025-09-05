import config
import Pinnacle_Scraper
import google_sheets_sync
import odds_sync
import clv_sync

def hybrid_main():
    print("Starting Pinnacle scraper...")
    Pinnacle_Scraper.main()

    print("Syncing CSV data to Google Sheets...")
    google_sheets_sync.partial_update_google_sheets()

    print("Refreshing Live/Detailed Odds from The Odds API...")
    odds_sync.main()

    print("Updating Closing Line & CLV%...")
    clv_sync.sync_clv()

if __name__ == "__main__":
    hybrid_main()
