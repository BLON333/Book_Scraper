

import csv
import os, unicodedata, config
import datetime
from typing import List, Dict, Tuple, Optional

import gspread
from gspread import Worksheet
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials

# -----------------------------
# CONFIGURATION
# -----------------------------
SERVICE_ACCOUNT_FILE = "credentials.json"  # For Google Sheets sync

CSV_FILE_PATH = os.getenv("BET_CSV_PATH", "Bet_Tracking.csv")
SHEET_ID = getattr(config, "GOOGLE_SHEET_ID", "")
SHEET_NAME = getattr(config, "BET_SHEET_TAB", "Sheet1")
HEADER_ROW = getattr(config, "BET_HEADER_ROW", 7)
FIRST_DATA_ROW = getattr(config, "BET_FIRST_DATA_ROW", 8)

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"

HEADER_ALIASES = {
    "Bet ID#": ["bet id#", "bet id", "ticket #", "ticket number", "ticket", "wager #", "wager id"],
    "Profit/Loss": ["profit/loss", "profit / loss", "p/l", "net", "net profit"],
    "Date": ["date"],
    "Start Time": ["start time", "time"],
    "Event ID": ["event id", "game id", "match id"],
    "Result": ["result", "status", "outcome"],
}


def _norm(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).replace("\u200b", "").replace("\xa0", " ")
    return s.strip()


def canonicalize_header_list(header_row):
    rev = {}
    for canon, variants in HEADER_ALIASES.items():
        rev[_norm(canon).lower()] = canon
        for v in variants:
            rev[_norm(v).lower()] = canon
    out = []
    for h in header_row:
        key = _norm(h).lower()
        out.append(rev.get(key, _norm(h)))
    return out

# -----------------------------
# HELPER FUNCTIONS (existing)
# -----------------------------
def convert_profit_loss(pl_str: str) -> float:
    try:
        cleaned = pl_str.replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0

def parse_event_datetime(date_str: str, time_str: str) -> Optional[datetime.datetime]:
    try:
        event_date = datetime.datetime.strptime(date_str, DATE_FORMAT).date()
        event_time = datetime.datetime.strptime(time_str, TIME_FORMAT).time()
        return datetime.datetime.combine(event_date, event_time)
    except ValueError:
        return None

def should_keep(event_dt: datetime.datetime) -> bool:
    now = datetime.datetime.now()
    local_date = now.date()
    main_day = local_date - datetime.timedelta(days=1) if now.hour < 3 else local_date
    event_date = event_dt.date()
    event_time = event_dt.time()
    if event_date == main_day:
        return True
    elif event_date == main_day + datetime.timedelta(days=1):
        return event_time < datetime.time(3, 0)
    return False

def read_csv_data(csv_file_path: str) -> List[Dict[str, str]]:
    if not os.path.isfile(csv_file_path):
        raise FileNotFoundError(f"CSV file '{csv_file_path}' not found.")
    
    # List of encodings to try
    encodings = ['utf-8', 'cp1252', 'latin-1']
    for enc in encodings:
        try:
            with open(csv_file_path, mode="r", newline="", encoding=enc) as file:
                reader = csv.DictReader(file)
                data = list(reader)
                print(f"CSV file successfully read with {enc} encoding.")
                return data
        except UnicodeDecodeError as e:
            print(f"Failed to decode CSV file using {enc} encoding: {e}")
    raise UnicodeDecodeError(f"CSV file '{csv_file_path}' could not be decoded with tried encodings.")

# -----------------------------
# GOOGLE SHEETS CONNECTION (existing)
# -----------------------------
def connect_google_sheets() -> Worksheet:
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, 
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    print("Connected to Google Sheets.")
    return sheet

# -----------------------------
# SHEET HELPER FUNCTIONS (existing)
# -----------------------------
def get_sheet_headers_from_row(sheet: Worksheet, header_row: int) -> Tuple[List[str], List[List[str]]]:
    all_values = sheet.get_all_values()
    if len(all_values) < header_row:
        raise ValueError(f"Sheet doesn't have enough rows to read headers at row {header_row}.")
    header = all_values[header_row - 1]
    data_rows = all_values[header_row:]
    return header, data_rows

def build_bet_id_mapping(data_rows: List[List[str]], bet_id_col_index: int, first_data_row: int) -> Dict[str, int]:
    mapping = {}
    for i, row in enumerate(data_rows, start=first_data_row):
        if bet_id_col_index < len(row):
            bet_id = row[bet_id_col_index].strip()
            if bet_id:
                mapping[bet_id] = i
    return mapping

def sort_sheet(sheet: Worksheet, header_row: int, first_data_row: int, sheet_header: List[str]) -> None:
    all_values = sheet.get_all_values()
    data_rows = all_values[first_data_row - 1:]
    data_rows = [row for row in data_rows if any(cell.strip() for cell in row)]
    try:
        result_index = sheet_header.index("Result")
    except ValueError:
        print("Error: 'Result' column not found in header during sort.")
        return
    try:
        start_time_index = sheet_header.index("Start Time")
    except ValueError:
        print("Error: 'Start Time' column not found in header during sort.")
        return

    def sort_key(row):
        result = row[result_index].strip().lower() if len(row) > result_index else ""
        group = 0 if result in ("", "pending") else 1
        if group == 0:
            time_str = row[start_time_index].strip() if len(row) > start_time_index else ""
            try:
                time_obj = datetime.datetime.strptime(time_str, TIME_FORMAT).time()
            except Exception:
                time_obj = datetime.time(0, 0)
            return (group, time_obj)
        else:
            return (group,)

    sorted_rows = sorted(data_rows, key=sort_key)
    if not sorted_rows:
        return
    start_cell = rowcol_to_a1(first_data_row, 1)
    end_cell = rowcol_to_a1(first_data_row + len(sorted_rows) - 1, len(sheet_header))
    range_address = f"{start_cell}:{end_cell}"
    sheet.update(range_address, sorted_rows, value_input_option="USER_ENTERED")
    print("Sheet rows sorted: pending bets at the top, settled bets at the bottom, with pending bets ordered by start time.")

# -----------------------------
# EVENT ID BACKFILL (new)
# -----------------------------
def backfill_event_ids_from_live_odds(sh):
    """
    Backfill empty 'Event ID' in Bets (Sheet1) using a lookup from 'Live Odds',
    keyed by 'Event/Match'. Uses headers so it works regardless of column order.
    - Does NOT overwrite existing Event IDs.
    - Trims whitespace on both sides before matching.
    - Fails soft with a single summary line.
    """
    import config

    try:
        ws_live = sh.worksheet(config.LIVE_ODDS_TAB)
        ws_bets = sh.worksheet(config.BET_SHEET_TAB)
    except Exception:
        print("[Sheets Sync] Skipped Event ID backfill: Live Odds or Bets tab not found.")
        return

    live_values = ws_live.get_all_values()
    bets_values = ws_bets.get_all_values()
    if not live_values or not bets_values:
        print("[Sheets Sync] Skipped Event ID backfill: one of the tabs is empty.")
        return

    # Live Odds headers are in the first row
    live_header = live_values[0]
    # Bets headers are at BET_HEADER_ROW
    bets_header_row_idx = config.BET_HEADER_ROW - 1
    if bets_header_row_idx >= len(bets_values):
        print("[Sheets Sync] Skipped Event ID backfill: Bets header row not found.")
        return
    bets_header = bets_values[bets_header_row_idx]

    # Helper to find column index by header name (case sensitive as per spec)
    def find_col(header, name):
        try:
            return header.index(name)
        except ValueError:
            return -1

    # Resolve columns by header (no hardcoded column letters)
    li_event_id = find_col(live_header, "Event ID")
    li_event_match = find_col(live_header, "Event/Match")
    bi_event_id = find_col(bets_header, "Event ID")
    bi_event_match = find_col(bets_header, "Event/Match")

    if min(li_event_id, li_event_match, bi_event_id, bi_event_match) < 0:
        print("[Sheets Sync] Skipped Event ID backfill: required headers not found.")
        return

    import re

    def _canon_match(s: str) -> str:
        s = (s or "").lower().strip()
        s = re.sub(r"\s+@\s+|\s+at\s+", " vs ", s)
        s = re.sub(r"\s+vs\.?\s+", " vs ", s)
        s = re.sub(r"\s+", " ", s)
        return s

    def _canon_pair(s: str) -> tuple:
        c = _canon_match(s)
        if " vs " in c:
            a, b = [p.strip() for p in c.split(" vs ", 1)]
            return tuple(sorted([a, b]))
        return (c, "")

    lookup = {}
    pair_lookup = {}
    for row in live_values[1:]:
        if len(row) <= max(li_event_id, li_event_match):
            continue
        em_raw = (row[li_event_match] or "").strip()
        eid = (row[li_event_id] or "").strip()
        if not em_raw or not eid:
            continue
        c = _canon_match(em_raw)
        lookup[c] = eid
        pair_lookup[_canon_pair(em_raw)] = eid

    updates = []
    start = config.BET_FIRST_DATA_ROW
    for r, row in enumerate(bets_values[start - 1:], start=start):
        if len(row) <= max(bi_event_id, bi_event_match):
            continue
        current_id = (row[bi_event_id] or "").strip()
        if current_id:
            continue
        em_bets_raw = (row[bi_event_match] or "").strip()
        if not em_bets_raw:
            continue

        cb = _canon_match(em_bets_raw)
        if " total " in cb and " vs " not in cb:
            continue

        eid = lookup.get(cb) or pair_lookup.get(_canon_pair(em_bets_raw))
        if eid:
            updates.append((r, bi_event_id + 1, eid))

    if not updates:
        print("[Sheets Sync] Backfilled 0 Event IDs from Live Odds (Sheet1).")
        return

    for r, c, val in updates:
        ws_bets.update_cell(r, c, val)

    print(f"[Sheets Sync] Backfilled {len(updates)} Event IDs from Live Odds (Sheet1).")

# -----------------------------
# PARTIAL UPDATE FUNCTION (existing)
# -----------------------------
def partial_update_google_sheets(csv_file_path: str = CSV_FILE_PATH) -> gspread.Spreadsheet:
    print("Starting Google Sheets sync from CSV...")
    sheet = connect_google_sheets()

    sheet_header, sheet_data_rows = get_sheet_headers_from_row(sheet, HEADER_ROW)
    sheet_header = canonicalize_header_list(sheet_header)

    required_cols = ["Bet ID#", "Result", "Profit/Loss", "Date", "Start Time", "Event ID"]
    for col in required_cols:
        if col not in sheet_header:
            print(f"❌ Column '{col}' is missing in row {HEADER_ROW} of the Google Sheet.")
            print('Header row seen by script:', sheet_header)
            return

    bet_id_index = sheet_header.index("Bet ID#")
    event_id_index = sheet_header.index("Event ID")

    bet_id_to_row = build_bet_id_mapping(
        sheet_data_rows,
        bet_id_col_index=bet_id_index,
        first_data_row=FIRST_DATA_ROW
    )

    csv_rows = read_csv_data(csv_file_path)
    print(f"DEBUG: CSV has {len(csv_rows)} rows.")

    updated_count = 0
    appended_count = 0

    for idx, csv_row in enumerate(csv_rows, start=1):
        print(f"DEBUG: CSV row #{idx} => {csv_row}")
        bet_id = csv_row.get("Bet ID#", "").strip()
        if not bet_id:
            print(f"WARNING: Row #{idx} has no 'Bet ID#'; skipping.")
            continue

        dt_obj = parse_event_datetime(csv_row.get("Date", "").strip(), csv_row.get("Start Time", "").strip())
        if dt_obj is None:
            print(f"WARNING: Row #{idx} => cannot parse date/time; skipping.")
            continue

        csv_event_id = csv_row.get("Event ID", "").strip()

        if bet_id in bet_id_to_row:
            row_num = bet_id_to_row[bet_id]
            try:
                current_sheet_event_id = sheet.cell(row_num, event_id_index + 1).value or ""
            except Exception as e:
                print(f"WARNING: Could not retrieve current event ID for Bet ID {bet_id} at row {row_num}: {e}")
                current_sheet_event_id = ""

            if csv_event_id and (not current_sheet_event_id or current_sheet_event_id.lower() == "unknown"):
                print(f"Updating 'Event ID' for Bet ID {bet_id} in row {row_num}")
                try:
                    sheet.update_cell(row_num, event_id_index + 1, csv_event_id)
                    updated_count += 1
                except Exception as e:
                    print(f"Error updating 'Event ID' for Bet ID {bet_id}: {e}")

            try:
                current_result = sheet.cell(row_num, sheet_header.index("Result") + 1).value or ""
            except Exception as e:
                print(f"WARNING: Could not retrieve current result for Bet ID {bet_id} at row {row_num}: {e}")
                current_result = ""

            if current_result.strip().lower() in ["", "pending"]:
                new_result = csv_row.get("Result", "").strip()
                pl_value = convert_profit_loss(csv_row.get("Profit/Loss", "").strip())
                print(f"Updating row {row_num} for Bet ID {bet_id}")
                try:
                    sheet.update_cell(row_num, sheet_header.index("Result") + 1, new_result)
                    pl_cell = rowcol_to_a1(row_num, sheet_header.index("Profit/Loss") + 1)
                    sheet.update(pl_cell, [[pl_value]], value_input_option="USER_ENTERED")
                    updated_count += 1
                except Exception as e:
                    print(f"Error updating row {row_num} for Bet ID {bet_id}: {e}")
            else:
                print(f"DEBUG: Row #{idx} => Bet ID {bet_id} is already settled with '{current_result}', skipping update.")
        else:
            current_date = datetime.datetime.now().date()
            if dt_obj.date() == current_date and dt_obj.time() < datetime.time(3, 0):
                print(f"DEBUG: Row #{idx} => event is today with start time before 03:00; skipping new bet.")
                continue
            if not should_keep(dt_obj):
                print(f"DEBUG: Row #{idx} => not in keep window; skipping new bet.")
                continue

            new_result = csv_row.get("Result", "").strip()
            pl_value = convert_profit_loss(csv_row.get("Profit/Loss", "").strip())

            new_row_values = []
            for col_name in sheet_header:
                if col_name == "Profit/Loss":
                    new_row_values.append(pl_value)
                else:
                    new_row_values.append(csv_row.get(col_name, ""))
            print(f"Appending new row for Bet ID {bet_id}: {new_row_values}")
            try:
                sheet.append_row(new_row_values, value_input_option="USER_ENTERED")
                appended_count += 1
            except Exception as e:
                print(f"Error appending row for Bet ID {bet_id}: {e}")
                raise

    print(f"CSV sync complete: {updated_count} rows updated, {appended_count} rows appended.")

    try:
        sort_sheet(sheet, HEADER_ROW, FIRST_DATA_ROW, sheet_header)
    except Exception as e:
        print(f"Error sorting the sheet: {e}")

    # -----------------------------
    # COPY FORMULA FROM N1/O1 DOWN TO LAST DATA ROW DYNAMICALLY
    # -----------------------------
    try:
        all_values = sheet.get_all_values()
        last_row = len(all_values)
        if last_row >= FIRST_DATA_ROW:
            # Copy formula from N1 down from row N{FIRST_DATA_ROW} to last row
            source_N = {
                "sheetId": sheet.id,
                "startRowIndex": 0,         # Row 1 (0-indexed)
                "endRowIndex": 1,
                "startColumnIndex": 13,       # Column N (0-indexed)
                "endColumnIndex": 14,
            }
            destination_N = {
                "sheetId": sheet.id,
                "startRowIndex": FIRST_DATA_ROW - 1,  # starting row
                "endRowIndex": last_row,               # to the last row
                "startColumnIndex": 13,
                "endColumnIndex": 14,
            }
            request_N = {
                "copyPaste": {
                    "source": source_N,
                    "destination": destination_N,
                    "pasteType": "PASTE_FORMULA",
                    "pasteOrientation": "NORMAL"
                }
            }

            # Copy formula from O1 down from row O{FIRST_DATA_ROW} to last row
            source_O = {
                "sheetId": sheet.id,
                "startRowIndex": 0,         # Row 1 (0-indexed)
                "endRowIndex": 1,
                "startColumnIndex": 14,       # Column O (0-indexed)
                "endColumnIndex": 15,
            }
            destination_O = {
                "sheetId": sheet.id,
                "startRowIndex": FIRST_DATA_ROW - 1,  # starting row
                "endRowIndex": last_row,               # to the last row
                "startColumnIndex": 14,
                "endColumnIndex": 15,
            }
            request_O = {
                "copyPaste": {
                    "source": source_O,
                    "destination": destination_O,
                    "pasteType": "PASTE_FORMULA",
                    "pasteOrientation": "NORMAL"
                }
            }

            # Batch both requests
            body = {
                "requests": [request_N, request_O]
            }
            sheet.spreadsheet.batch_update(body)
            print(f"Formula in N1 copied down dynamically from N{FIRST_DATA_ROW} to N{last_row}.")
            print(f"Formula in O1 copied down dynamically from O{FIRST_DATA_ROW} to O{last_row}.")
        else:
            print("No data rows to copy formula into.")
    except Exception as e:
        print("Error copying formula from N1/O1 down:", e)

    return sheet.spreadsheet

# -----------------------------
# MAIN FUNCTION
# -----------------------------
def main() -> None:
    sh = None
    try:
        sh = partial_update_google_sheets()
    except Exception as e:
        print(f"An error occurred during Sheets sync: {e}")
    if sh:
        backfill_event_ids_from_live_odds(sh)

    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
