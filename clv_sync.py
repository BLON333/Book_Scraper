import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT / "Python Project Folder"))

from core.odds_labeling import base_market, build_label
import config

# ---------- Helpers ----------
def american_to_prob(odds: str) -> Optional[float]:
    try:
        s = str(odds).strip().replace(" ", "")
        if not s:
            return None
        v = float(s.replace("+", ""))
        if v > 0:
            return 100.0 / (v + 100.0)
        else:
            return -v / (-v + 100.0)
    except Exception:
        return None

def clean_money(x: str) -> str:
    return re.sub(r"[^\d\.-]", "", str(x or "")).strip()

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def open_sheet_by_id(sheet_id: str):
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)

# ---------- Load Bet Tracking rows ----------
def load_bets() -> Tuple[gspread.Worksheet, List[Dict[str, str]], List[str]]:
    bet_book = open_sheet_by_id(config.GOOGLE_SHEET_ID)
    ws = bet_book.worksheet(config.BET_SHEET_TAB)
    header = ws.row_values(config.BET_HEADER_ROW)
    all_vals = ws.get_all_values()
    rows = []
    for r in all_vals[config.BET_FIRST_DATA_ROW - 1:]:
        if not any(cell.strip() for cell in r):
            continue
        row = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        rows.append(row)
    return ws, rows, header

# ---------- Load Detailed Odds into a lookup ----------
def load_detailed_odds() -> Dict[str, List[Dict[str, str]]]:
    odds_book = open_sheet_by_id(config.GOOGLE_SHEET_ID)
    ws = odds_book.worksheet(config.DETAILED_ODDS_TAB)
    vals = ws.get_all_values()
    if not vals:
        return {}
    header = vals[0]
    idx = {h: i for i, h in enumerate(header)}
    lookup: Dict[str, List[Dict[str, str]]] = {}
    for r in vals[1:]:
        if not any(c.strip() for c in r):
            continue
        event_id = r[idx.get("Event ID", -1)].strip() if idx.get("Event ID", -1) >= 0 else ""
        if not event_id:
            continue
        entry = {h: (r[i] if i < len(r) else "") for i, h in enumerate(header)}
        lookup.setdefault(event_id, []).append(entry)
    return lookup

# ---------- Matching logic ----------
def parse_bet_market(row: Dict[str, str]) -> Tuple[str, str]:
    market = (row.get("Market", "") or "").lower().strip()
    bet = (row.get("Bet", "") or "").strip().replace("Â½", "½")
    bet = re.sub(r"\s+", " ", bet)
    if re.match(r"^(over|under)\s+\d+(\.\d+)?(½)?$", bet, flags=re.I):
        label = bet.title()
    elif re.search(r"[+\-]\d+(\.\d+)?(½)?$", bet):
        label = bet
    else:
        label = bet
    return market, label

def _norm_book(s: str) -> str:
    s = (s or "").strip().lower()
    return {"betonlineag": "betonline"}.get(s, s)

def _norm_market_from_api(api_market: str) -> str:
    return base_market(api_market)

def _build_label_from_detailed(row: Dict[str, str]) -> str:
    api_raw = row.get("API Market") or row.get("Market") or ""
    name = (
        row.get("Outcome Name (Normalized)")
        or row.get("Label")
        or row.get("Outcome")
        or row.get("Bet")
        or ""
    )
    point = row.get("Outcome Point") or ""
    return build_label(api_raw, name, point)

def pick_closing_line(
    event_rows: List[Dict[str, str]],
    wanted_market: str,
    wanted_label: str,
    bookmaker: str,
) -> Optional[str]:
    """Match a bet row to closing odds from Detailed Odds."""
    if not event_rows:
        return None
    base_mkt = _norm_market_from_api(wanted_market)
    target_book = _norm_book(bookmaker)
    for r in event_rows:
        book = _norm_book(r.get("Bookmaker") or r.get("Book") or r.get("Sportsbook") or "")
        api_mkt = _norm_market_from_api(r.get("API Market") or r.get("Market") or "")
        label = _build_label_from_detailed(r)
        if book == target_book and api_mkt == base_mkt and norm(label) == norm(wanted_label):
            odds = (r.get("Odds") or r.get("American") or r.get("Price") or "").strip()
            if odds:
                return odds
    for r in event_rows:
        api_mkt = _norm_market_from_api(r.get("API Market") or r.get("Market") or "")
        label = _build_label_from_detailed(r)
        if api_mkt == base_mkt and norm(label) == norm(wanted_label):
            odds = (r.get("Odds") or r.get("American") or r.get("Price") or "").strip()
            if odds:
                return odds
    return None

# ---------- Main sync ----------
def sync_clv():
    ws_bets, bets, header = load_bets()
    detailed = load_detailed_odds()

    def col_idx(name: str) -> int:
        return header.index(name) + 1 if name in header else -1

    col_closing = col_idx("Closing Line")
    col_clv = col_idx("CLV%")

    if col_closing < 0 or col_clv < 0:
        print("Missing 'Closing Line' or 'CLV%' columns in Bet sheet header.")
        return

    updates = []
    start_row = config.BET_FIRST_DATA_ROW
    for i, row in enumerate(bets, start=start_row):
        event_id = (row.get("Event ID", "") or "").strip()
        bookmaker = (row.get("Bookmaker", "") or "").strip()
        entry_odds = (row.get("Odds", "") or "").strip()
        market, label = parse_bet_market(row)
        if not event_id or not entry_odds:
            continue
        event_rows = detailed.get(event_id, [])
        closing = pick_closing_line(event_rows, market, label, bookmaker)
        if not closing:
            continue
        p_entry = american_to_prob(entry_odds)
        p_closing = american_to_prob(closing)
        if p_entry and p_entry > 0 and p_closing:
            clv = ((p_closing / p_entry) - 1.0) * 100.0
            updates.append((i, closing, f"{clv:.2f}"))

    if not updates:
        print("No CLV updates found.")
        return

    cell_updates = []
    for r, closing, clv in updates:
        cell_updates.append({"range": gspread.utils.rowcol_to_a1(r, col_closing), "values": [[closing]]})
        cell_updates.append({"range": gspread.utils.rowcol_to_a1(r, col_clv), "values": [[clv]]})

    ws_bets.batch_update([{ "range": u["range"], "values": u["values"] } for u in cell_updates])
    print(f"Updated {len(updates)} rows with Closing Line & CLV%.")

if __name__ == "__main__":
    sync_clv()
