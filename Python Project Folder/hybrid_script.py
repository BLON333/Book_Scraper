import Pinnacle_Scraper
import google_sheets_sync

def hybrid_main():
    # Run the Pinnacle scraper to update the CSV file.
    print("Starting Pinnacle scraper...")
    Pinnacle_Scraper.main()
    
    # Sync the CSV data to Google Sheets.
    print("Syncing CSV data to Google Sheets...")
    google_sheets_sync.partial_update_google_sheets()

if __name__ == "__main__":
    hybrid_main()
