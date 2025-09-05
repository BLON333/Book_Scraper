import re
from typing import Dict, List, Optional, Tuple
from core import sheets
from core import odds_labeling
import config


def american_to_prob(odds: str) -> Optional[float]:
    s = str(odds).strip()
    if not s:
        return None
    try:
        n = int(s[1:]) if s.startswith("+") else int(s)
    except Exception:
        return None
    if n == 0:
        return None
    if s.startswith("+"):
        return 100.0 / (n + 100.0)
    return float(abs(n)) / (abs(n) + 100.0)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("Â½", "½").strip().lower())


def load_bets() -> Tuple[List[str], List[List[str]]]:
    ws = sheets.open_ws(config.GOOGLE_SHEET_ID, config.BET_SHEET_TAB)
    header = ws.row_values(config.BET_HEADER_ROW)
    data = ws.get_all_values()[config.BET_FIRST_DATA_ROW - 1 :]
    return header, data


def load_detailed_odds() -> List[Dict[str, str]]:
    ws = sheets.open_ws(config.GOOGLE_SHEET_ID, config.DETAILED_ODDS_TAB)
    vals = ws.get_all_values()
    if not vals:
        return []
    header = vals[0]
    out = []
    for r in vals[1:]:
        if not any(r):
            continue
        out.append({header[i]: (r[i] if i < len(r) else "") for i in range(len(header))})
    return out


def parse_bet_market(market: str, bet: str) -> Tuple[str, str]:
    m = (market or "").lower().strip()
    b = (bet or "").strip()
    if re.match(r"^(?i)(over|under)\s+\d+(\.\d+)?(½)?$", b):
        side, num = b.split()[0].title(), b.split()[1].replace("Â½", "½")
        return "totals", f"{side} {num}"
    m = (
        "spreads"
        if m.startswith("spread")
        else ("totals" if m.startswith("total") else ("h2h" if m in ("h2h", "ml", "moneyline") else m))
    )
    m2 = re.search(r"([+-]?\d+(\.\d+)?(½)?)$", b)
    if m == "spreads" and m2:
        p = m2.group(1)
        if not p.startswith(("+", "-")):
            b = b.replace(p, f"+{p}")
    return m, b.replace("Â½", "½")


def _norm_book(s: str) -> str:
    x = (s or "").strip().lower()
    return {"betonline.ag": "betonline", "betonlineag": "betonline"}.get(x, x)


def pick_closing_line(event_rows: List[Dict[str, str]], market: str, bet_label: str, bookmaker: str) -> Optional[str]:
    base_mkt = odds_labeling.base_market(market)
    target_book = _norm_book(bookmaker)
    # pass 1: same book
    for r in event_rows:
        api_mkt = odds_labeling.base_market(r.get("API Market") or r.get("Market") or "")
        if api_mkt != base_mkt:
            continue
        label = odds_labeling.build_label(
            r.get("API Market", ""), r.get("Outcome Name (Normalized)", ""), r.get("Outcome Point", "")
        )
        if norm(_norm_book(r.get("Bookmaker") or r.get("Book", ""))) == target_book and norm(label) == norm(bet_label):
            return (r.get("Odds") or "").strip()
    # pass 2: any book
    for r in event_rows:
        api_mkt = odds_labeling.base_market(r.get("API Market") or r.get("Market") or "")
        if api_mkt != base_mkt:
            continue
        label = odds_labeling.build_label(
            r.get("API Market", ""), r.get("Outcome Name (Normalized)", ""), r.get("Outcome Point", "")
        )
        if norm(label) == norm(bet_label):
            return (r.get("Odds") or "").strip()
    return None


def main():
    header, bet_rows = load_bets()
    det_rows = load_detailed_odds()
    from collections import defaultdict

    by_event = defaultdict(list)
    for r in det_rows:
        by_event[(r.get("Event ID") or "").strip()].append(r)

    def col(name: str) -> int:
        return header.index(name) + 1 if name in header else -1

    c_event = col("Event ID")
    c_market = col("Market")
    c_bet = col("Bet")
    c_book = col("Bookmaker")
    c_entry = col("Odds")
    c_close = col("Closing Line")
    c_clv = col("CLV%")
    if min(c_event, c_market, c_bet, c_book, c_entry, c_close, c_clv) < 0:
        print(
            "Missing required columns in Bets (need: Event ID, Market, Bet, Bookmaker, Odds, Closing Line, CLV%)."
        )
        return
    ws = sheets.open_ws(config.GOOGLE_SHEET_ID, config.BET_SHEET_TAB)
    updated = 0
    for i, row in enumerate(bet_rows, start=config.BET_FIRST_DATA_ROW):
        ev_id = (row[c_event - 1] if c_event - 1 < len(row) else "").strip()
        market = (row[c_market - 1] if c_market - 1 < len(row) else "").strip()
        bet = (row[c_bet - 1] if c_bet - 1 < len(row) else "").strip()
        book = (row[c_book - 1] if c_book - 1 < len(row) else "").strip()
        entry = (row[c_entry - 1] if c_entry - 1 < len(row) else "").strip()
        if not (ev_id and market and bet and entry):
            continue
        mkt, label = parse_bet_market(market, bet)
        rows = by_event.get(ev_id, [])
        closing = pick_closing_line(rows, mkt, label, book)
        if not closing:
            continue
        p_entry = american_to_prob(entry)
        p_close = american_to_prob(closing)
        if not (p_entry and p_close and p_entry > 0):
            continue
        clv_pct = (p_close / p_entry - 1.0) * 100.0
        ws.update_cell(i, c_close, str(closing))
        ws.update_cell(i, c_clv, f"{clv_pct:.2f}")
        updated += 1
    print(f"Updated {updated} rows with Closing Line & CLV%.")


if __name__ == "__main__":
    main()
