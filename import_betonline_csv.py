import os
import pandas as pd

DEFAULT_PATH = os.environ.get("BETONLINE_CSV_PATH", "BetOnline_Export.csv")
MASTER_CSV   = "Bet_Tracking.csv"

def main():
    if not os.path.exists(DEFAULT_PATH):
        print(f"No BetOnline CSV at {DEFAULT_PATH}; skipping.")
        return
    try:
        new_df = pd.read_csv(DEFAULT_PATH, dtype=str).fillna("")
    except Exception as e:
        print(f"Failed to read BetOnline CSV: {e}")
        return
    if os.path.exists(MASTER_CSV):
        base = pd.read_csv(MASTER_CSV, dtype=str).fillna("")
    else:
        base = pd.DataFrame()
    combined = pd.concat([base, new_df], ignore_index=True, sort=False).fillna("")
    if "Bet ID" in combined.columns:
        combined.drop_duplicates(subset=["Bet ID"], keep="first", inplace=True)
    elif "Bet ID#" in combined.columns:
        combined.drop_duplicates(subset=["Bet ID#"], keep="first", inplace=True)
    combined.to_csv(MASTER_CSV, index=False)
    print(f"Merged {len(new_df)} BetOnline rows → {MASTER_CSV} (total {len(combined)}).")

if __name__ == "__main__":
    main()
