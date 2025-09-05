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
def _norm_book(s: str) -> str:
    s = (s or "").strip().lower()
    return {"betonlineag": "betonline"}.get(s, s)


def _norm_market_from_api(api_market: str) -> str:
    m = (api_market or "").strip().lower()
    if m.startswith("alternate_"):
        m = m.replace("alternate_", "", 1)
    # only keep base key (h2h, spreads, totals, team_totals, etc.)
    return m


def _build_label_from_detailed(api_market: str, name_norm: str, point: str) -> str:
    """
    Construct a canonical label string from Detailed Odds columns:
    - totals:  'Over 9.5' / 'Under 9.5'
    - spreads: 'Team +3.5'
    - h2h:     'Team'
    """
    m = _norm_market_from_api(api_market)
    nm = (name_norm or "").strip()
    pt = (point or "").strip()

    # normalize half display issues (Â½ → ½)
    nm = nm.replace("Â½", "½")
    pt = pt.replace("Â½", "½")

    if m == "totals":
        # name_norm is 'Over' or 'Under'
        if nm:
            return f"{nm.title()} {pt}"
        return pt
    elif m == "spreads":
        # name_norm is Team; point is signed line (+/-)
        if pt and not pt.startswith(("+", "-")):
            # sign-less numbers should be treated as + if no sign is given
            pt = f"+{pt}"
        return f"{nm} {pt}".strip()
    else:
        # h2h or anything else: just the team/outcome name
        return nm


def pick_closing_line(event_rows: List[Dict[str, str]], wanted_market: str, wanted_label: str, bookmaker: str) -> Optional[str]:
    """
    event_rows: rows from 'Detailed Odds' for this Event ID
    wanted_market: your Bet sheet 'Market' value (may include suffix like _q1/_h1)
    wanted_label:  canonical Bet label (e.g., 'Over 9.5', 'Team +3.5', 'Team')
    """
    if not event_rows:
        return None

    base_market = (wanted_market or "").strip().lower()
    # strip suffix (_q1,_q2,_h1,_h2) to compare base keys; your Detailed tab is base market
    base_market = base_market.split("_")[0]

    target_book = _norm_book(bookmaker)

    # 1) exact bookmaker first
    for r in event_rows:
        book = _norm_book(r.get("Bookmaker") or r.get("Book") or r.get("Sportsbook") or "")
        api_mkt = _norm_market_from_api(r.get("API Market") or r.get("Market") or "")
        label = _build_label_from_detailed(
            api_mkt,
            r.get("Outcome Name (Normalized)")
            or r.get("Label")
            or r.get("Outcome")
            or r.get("Bet")
            or "",
            r.get("Outcome Point") or "",
        )
        if book == target_book and api_mkt == base_market and norm(label) == norm(wanted_label):
            odds = (r.get("Odds") or r.get("American") or r.get("Price") or "").strip()
            if odds:
                return odds

    # 2) fallback: any book that matches market + label
    for r in event_rows:
        api_mkt = _norm_market_from_api(r.get("API Market") or r.get("Market") or "")
        label = _build_label_from_detailed(
            api_mkt,
            r.get("Outcome Name (Normalized)")
            or r.get("Label")
            or r.get("Outcome")
            or r.get("Bet")
            or "",
            r.get("Outcome Point") or "",
        )
        if api_mkt == base_market and norm(label) == norm(wanted_label):
            odds = (r.get("Odds") or r.get("American") or r.get("Price") or "").strip()
            if odds:
                return odds

    return None


# Update parse_bet_market() to normalize label like your Bets do
def parse_bet_market(row: Dict[str, str]) -> Tuple[str, str]:
    market = (row.get("Market", "") or "").lower().strip()
    bet = (row.get("Bet", "") or "").strip().replace("Â½", "½")
    # unify whitespace
    bet = re.sub(r"\s+", " ", bet)

    # totals: 'Over N' / 'Under N'
    if re.match(r"^(over|under)\s+\d+(\.\d+)?(½)?$", bet, flags=re.I):
        label = bet.title()
    # spreads: capture trailing signed number and keep team + number
    elif re.search(r"[+\-]\d+(\.\d+)?(½)?$", bet):
        label = bet
    else:
        # h2h (team only)
        label = bet
    return market, label

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

