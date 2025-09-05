import pandas as pd
from core import sheets
import config

CSV_PATH = "Bet_Tracking.csv"

def main():
    ws = sheets.open_ws(config.GOOGLE_SHEET_ID, config.BET_SHEET_TAB)
    try:
        df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    except FileNotFoundError:
        print(f"[ERROR] CSV not found: {CSV_PATH}")
        return
    # Header alias mapping
    header_map = {"Bet ID#": "Bet ID"}
    df.rename(columns={k:v for k,v in header_map.items() if k in df.columns}, inplace=True)
    # Clear old data rows (keep headers)
    sheets.clear_below(ws, config.BET_FIRST_DATA_ROW, last_col_letter="Z")
    if len(df):
        rows = [list(r) for r in df.to_records(index=False)]
        ws.update(f"A{config.BET_FIRST_DATA_ROW}", rows, value_input_option="USER_ENTERED")
    print(f"[Sheets Sync] Synced {len(df)} rows to '{config.BET_SHEET_TAB}'.")

if __name__ == "__main__":
    main()
