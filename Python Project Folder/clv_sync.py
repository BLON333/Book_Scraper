import re, math, time
from typing import Dict, List, Tuple, Optional
import gspread
from google.oauth2.service_account import Credentials
import config

# ---------- Helpers ----------
def american_to_prob(odds: str) -> Optional[float]:
    try:
        s = str(odds).strip().replace(" ", "")
        if not s: return None
        v = float(s.replace("+",""))
        if v > 0:  return 100.0 / (v + 100.0)
        else:      return -v / (-v + 100.0)
    except Exception:
        return None

def clean_money(x: str) -> str:
    return re.sub(r"[^\d\.-]", "", str(x or "")).strip()

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def open_sheet_by_id(sheet_id: str):
    creds = Credentials.from_service_account_file(
        "credentials.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)

# ---------- Load Bet Tracking rows ----------
def load_bets() -> Tuple[gspread.Worksheet, List[Dict[str, str]], List[str]]:
    bet_book = open_sheet_by_id(config.GOOGLE_SHEET_ID)
    ws = bet_book.worksheet(config.BET_SHEET_TAB)
    # header row:
    header = ws.row_values(config.BET_HEADER_ROW)
    # data rows:
    all_vals = ws.get_all_values()
    rows = []
    for r in all_vals[config.BET_FIRST_DATA_ROW - 1:]:
        if not any(cell.strip() for cell in r):  # skip blank
            continue
        row = { header[i]: (r[i] if i < len(r) else "") for i in range(len(header)) }
        rows.append(row)
    return ws, rows, header

# ---------- Load Detailed Odds into a lookup ----------
def load_detailed_odds() -> Dict[str, List[Dict[str, str]]]:
    odds_book = open_sheet_by_id(config.LIVE_ODDS_SHEET_ID)
    ws = odds_book.worksheet(config.DETAILED_ODDS_TAB)
    vals = ws.get_all_values()
    if not vals: return {}
    header = vals[0]
    idx = { h: i for i, h in enumerate(header) }
    lookup: Dict[str, List[Dict[str, str]]] = {}
    for r in vals[1:]:
        if not any(c.strip() for c in r): continue
        event_id = r[idx.get("Event ID", -1)].strip() if idx.get("Event ID", -1) >= 0 else ""
        if not event_id: continue
        entry = { h: (r[i] if i < len(r) else "") for i, h in enumerate(header) }
        lookup.setdefault(event_id, []).append(entry)
    return lookup

# ---------- Matching logic ----------
def parse_bet_market(row: Dict[str, str]) -> Tuple[str, str]:
    """
    Return (market_key, label_key) to match 'Detailed Odds' rows.
    market_key is one of {'h2h','spreads','totals','team_totals', ...} including segment suffix (e.g., 'totals_q1').
    label_key is the normalized selection like 'Over 9.5' or 'Team +3.5' or 'Team'.
    """
    market = (row.get("Market","") or "").lower().strip()
    bet    = (row.get("Bet","") or "").strip()
    # normalize weird half char
    bet = bet.replace("Â½","½").replace("  ", " ")
    # pull spread value if present
    lab = bet
    # simplify: treat anything starting with Over/Under as totals
    if re.match(r"^(over|under)\b", bet, flags=re.I):
        lab = re.sub(r"\s+", " ", bet.title())
    elif re.search(r"[+\-]\d+(\.\d+)?", bet):
        # keep team + number
        lab = re.sub(r"\s+", " ", bet)
    else:
        # h2h: keep team name only
        lab = re.sub(r"\s+@\s+.*$", "", bet)

    return market, lab

def pick_closing_line(event_rows: List[Dict[str,str]], market_key: str, label_key: str, bookmaker: str) -> Optional[str]:
    if not event_rows: return None
    # Try exact book first
    def norm_book(s): return norm(s).replace("betonlineag","betonline")
    target_book = norm_book(bookmaker)
    # heuristic: columns present in Detailed Odds: ['Event ID','Book','Market','Label','Odds', ...]
    # we accept aliases: Book/Bookmaker/Sportsbook, Market, Label, Odds (American)
    for r in event_rows:
        book = r.get("Book") or r.get("Bookmaker") or r.get("Sportsbook") or ""
        mkt  = (r.get("Market") or "").lower().strip()
        lab  = r.get("Label") or r.get("Outcome") or r.get("Bet") or ""
        if norm_book(book)==target_book and mkt==market_key and norm(lab)==norm(label_key):
            odds = (r.get("Odds") or r.get("American") or r.get("Price") or "").strip()
            if odds: return odds

    # fallback: try any book with same market/label (e.g., Pinnacle)
    for r in event_rows:
        mkt  = (r.get("Market") or "").lower().strip()
        lab  = r.get("Label") or r.get("Outcome") or r.get("Bet") or ""
        if mkt==market_key and norm(lab)==norm(label_key):
            odds = (r.get("Odds") or r.get("American") or r.get("Price") or "").strip()
            if odds: return odds
    return None

# ---------- Main sync ----------
def sync_clv():
    ws_bets, bets, header = load_bets()
    detailed = load_detailed_odds()

    # column indices to write back
    def col_idx(name: str) -> int:
        return header.index(name) + 1 if name in header else -1
    col_closing = col_idx("Closing Line")
    col_clv     = col_idx("CLV%")

    if col_closing < 0 or col_clv < 0:
        print("Missing 'Closing Line' or 'CLV%' columns in Bet sheet header.")
        return

    updates = []  # (row_number, closing_line, clv_pct)
    start_row = config.BET_FIRST_DATA_ROW
    for i, row in enumerate(bets, start=start_row):
        event_id  = (row.get("Event ID","") or "").strip()
        bookmaker = (row.get("Bookmaker","") or "").strip()
        entry_odds = (row.get("Odds","") or "").strip()
        market, label = parse_bet_market(row)

        if not event_id or not entry_odds:
            continue
        event_rows = detailed.get(event_id, [])
        closing = pick_closing_line(event_rows, market, label, bookmaker)
        if not closing:
            continue
        p_entry   = american_to_prob(entry_odds)
        p_closing = american_to_prob(closing)
        if p_entry and p_entry > 0 and p_closing:
            clv = ((p_closing / p_entry) - 1.0) * 100.0
            updates.append( (i, closing, f"{clv:.2f}") )

    # batch write
    if not updates:
        print("No CLV updates found.")
        return

    cell_updates = []
    for r, closing, clv in updates:
        cell_updates.append( { "range": gspread.utils.rowcol_to_a1(r, col_closing), "values": [[closing]] } )
        cell_updates.append( { "range": gspread.utils.rowcol_to_a1(r, col_clv),     "values": [[clv]] } )

    ws_bets.batch_update( [ {"range": u["range"], "values": u["values"]} for u in cell_updates ] )
    print(f"Updated {len(updates)} rows with Closing Line & CLV%.")

if __name__ == "__main__":
    sync_clv()

