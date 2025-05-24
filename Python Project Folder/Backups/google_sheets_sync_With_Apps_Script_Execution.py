import csv
import os
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

# Update the path to your new OAuth credentials file.
OAUTH_CREDENTIALS_FILE = r"C:\Users\jason\Documents\Python Project Folder\oauth_credentials.json"  # For Apps Script API calls

SHEET_ID = "10T1umWJko_HOvnEfMn_giLFYFk4O2zONAfdltA2FBv4"
SHEET_NAME = "Sheet1"
CSV_FILE_PATH = "bet_tracking.csv"

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"

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
    with open(csv_file_path, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader)

# -----------------------------
# GOOGLE SHEETS CONNECTION (existing)
# -----------------------------
def connect_google_sheets() -> Worksheet:
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
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
# PARTIAL UPDATE FUNCTION (existing)
# -----------------------------
def partial_update_google_sheets(csv_file_path: str = CSV_FILE_PATH) -> None:
    print("Starting Google Sheets sync from CSV...")
    sheet = connect_google_sheets()

    header_row_number = 7
    first_data_row_number = 8
    sheet_header, sheet_data_rows = get_sheet_headers_from_row(sheet, header_row_number)

    required_cols = ["Bet ID#", "Result", "Profit/Loss", "Date", "Start Time", "Event ID"]
    for col in required_cols:
        if col not in sheet_header:
            print(f"❌ Column '{col}' is missing in row {header_row_number} of the Google Sheet.")
            return

    bet_id_index = sheet_header.index("Bet ID#")
    event_id_index = sheet_header.index("Event ID")

    bet_id_to_row = build_bet_id_mapping(
        sheet_data_rows,
        bet_id_col_index=bet_id_index,
        first_data_row=first_data_row_number
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
        sort_sheet(sheet, header_row_number, first_data_row_number, sheet_header)
    except Exception as e:
        print(f"Error sorting the sheet: {e}")

    # -----------------------------
    # COPY FORMULA FROM N1/O1 DOWN TO LAST DATA ROW DYNAMICALLY
    # -----------------------------
    try:
        all_values = sheet.get_all_values()
        last_row = len(all_values)
        if last_row >= first_data_row_number:
            # Copy formula from N1 down from row N8 to last row
            source_N = {
                "sheetId": sheet.id,
                "startRowIndex": 0,         # Row 1 (0-indexed)
                "endRowIndex": 1,
                "startColumnIndex": 13,       # Column N (0-indexed)
                "endColumnIndex": 14,
            }
            destination_N = {
                "sheetId": sheet.id,
                "startRowIndex": first_data_row_number - 1,  # from row 8 (0-indexed)
                "endRowIndex": last_row,                      # to the last row
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

            # Copy formula from O1 down from row O8 to last row
            source_O = {
                "sheetId": sheet.id,
                "startRowIndex": 0,         # Row 1 (0-indexed)
                "endRowIndex": 1,
                "startColumnIndex": 14,       # Column O (0-indexed)
                "endColumnIndex": 15,
            }
            destination_O = {
                "sheetId": sheet.id,
                "startRowIndex": first_data_row_number - 1,  # from row 8 (0-indexed)
                "endRowIndex": last_row,                      # to the last row
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
            print(f"Formula in N1 copied down dynamically from N{first_data_row_number} to N{last_row}.")
            print(f"Formula in O1 copied down dynamically from O{first_data_row_number} to O{last_row}.")
        else:
            print("No data rows to copy formula into.")
    except Exception as e:
        print("Error copying formula from N1/O1 down:", e)

# -----------------------------
# NEW: CALL APPS SCRIPT FUNCTION VIA EXECUTION API
# -----------------------------
def call_apps_script_function(force_fresh: bool = False):
    """
    Calls the Google Apps Script function 'fetchOddsByEventMarketAndBet'
    using the Apps Script Execution API.
    
    If force_fresh is True, it deletes the existing token.json file so that
    a fresh OAuth flow is triggered.
    """
    import google.auth
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    # Scopes required for executing the script and accessing spreadsheets
    scopes = [
        'https://www.googleapis.com/auth/script.projects',
        'https://www.googleapis.com/auth/spreadsheets'
    ]
    token_file = 'token.json'
    
    # Force a fresh OAuth sign-in if requested
    if force_fresh and os.path.exists(token_file):
        os.remove(token_file)
        print("Force fresh OAuth: token.json removed.")

    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDENTIALS_FILE, scopes)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'w') as token:
            token.write(creds.to_json())

    service = build('script', 'v1', credentials=creds)

    # Use your provided script ID
    SCRIPT_ID = '1SP-HScT1-VkgKOC5oCBmWnXLzpRiUDfhkwUvSwMDOQvIdHxmJrOfg_5B'
    request_body = {"function": "fetchOddsByEventMarketAndBet"}
    response = service.scripts().run(scriptId=SCRIPT_ID, body=request_body).execute()

    if 'error' in response:
        error = response['error']['details'][0]
        print("Script error message: {}".format(error.get('errorMessage')))
        if 'scriptStackTraceElements' in error:
            print("Script error stacktrace:")
            for trace in error['scriptStackTraceElements']:
                print("\t-> {}: {}".format(trace.get('function'), trace.get('lineNumber')))
    else:
        print("Google Apps Script function executed successfully!")
        result = response.get('response', {}).get('result', {})
        print("Result from Apps Script:", result)

# -----------------------------
# MAIN FUNCTION
# -----------------------------
def main() -> None:
    try:
        partial_update_google_sheets()
    except Exception as e:
        print(f"An error occurred during Sheets sync: {e}")
    
    # Call the Apps Script function at the end.
    # Set force_fresh=True to force a fresh OAuth sign-in with the correct account.
    try:
        call_apps_script_function(force_fresh=True)
    except Exception as e:
        print(f"An error occurred calling the Apps Script function: {e}")
    
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()

