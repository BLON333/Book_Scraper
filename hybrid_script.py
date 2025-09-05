import subprocess, sys
import config


def main() -> None:
    print("=== Pipeline start ===")
    # 1) Pinnacle
    try:
        subprocess.run([sys.executable, "Pinnacle_Scraper.py"], check=True)
        print("[OK] Pinnacle_Scraper")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] Pinnacle_Scraper failed: {e}")
    # 2) BetOnline: scraper or CSV merge
    if config.ENABLE_BETONLINE:
        try:
            subprocess.run([sys.executable, "BetOnline_Scraper.py"], check=True)
            print("[OK] BetOnline_Scraper")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] BetOnline_Scraper failed: {e}")
    else:
        subprocess.run([sys.executable, "import_betonline_csv.py"], check=False)
    # 3) Sync bets to Sheets
    subprocess.run([sys.executable, "google_sheets_sync.py"], check=True)
    # 4) Odds → Live & Detailed
    subprocess.run([sys.executable, "odds_sync.py"], check=True)
    # 5) CLV → write back
    subprocess.run([sys.executable, "clv_sync.py"], check=True)
    print("=== Pipeline end ===")


if __name__ == "__main__":
    main()

