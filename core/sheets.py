import gspread
from google.oauth2.service_account import Credentials


def client():
    return gspread.authorize(Credentials.from_service_account_file(
        "credentials.json", scopes=["https://www.googleapis.com/auth/spreadsheets"]
    ))


def open_ws(sheet_id: str, tab: str):
    gc = client()
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=tab, rows=1000, cols=30)


def write_header(ws, headers):
    ws.clear()
    ws.update("A1", [headers], value_input_option="USER_ENTERED")
