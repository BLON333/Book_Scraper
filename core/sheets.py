from typing import List
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _client():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(sheet_id: str) -> gspread.Spreadsheet:
    return _client().open_by_key(sheet_id)


def open_ws(sheet_id: str, title: str, rows: int = 1000, cols: int = 26) -> gspread.Worksheet:
    ss = open_spreadsheet(sheet_id)
    try:
        ws = ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=rows, cols=cols)
    return ws


def write_header(ws: gspread.Worksheet, header: List[str], header_row: int = 1):
    ws.clear()
    col_count = max(len(header), ws.col_count)
    if ws.col_count < col_count:
        ws.resize(rows=ws.row_count, cols=col_count)
    ws.update(f"A{header_row}", [header])


def clear_below(ws: gspread.Worksheet, start_row: int, last_col_letter: str = "Z"):
    end_row = ws.row_count
    rng = f"A{start_row}:{last_col_letter}{end_row}"
    ws.spreadsheet.batch_clear([rng])

