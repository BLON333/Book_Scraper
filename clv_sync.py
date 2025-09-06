"""Sync Closing Line values using consensus pricing.

This script reads bet tracking data and detailed odds from Google Sheets,
computes a consensus closing line across configured bookmakers and writes
the resulting odds and CLV% back to the bet sheet.

It relies on :mod:`core.consensus_pricer` for devigging and consensus
probabilities.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Dict, Iterable, List, Optional, Tuple

from core import odds_labeling, sheets
from core.consensus_pricer import BetKey, compute_consensus, extract_book_quotes
from core.logging_utils import info, warn

import config


# ---------------------------------------------------------------------------
# Odds helpers
# ---------------------------------------------------------------------------


def american_to_prob(odds: str) -> Optional[float]:
    """Convert American odds (as string) to implied probability."""

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
    """Normalize whitespace and half symbols for comparison."""

    return re.sub(r"\s+", " ", (s or "").replace("Â½", "½").strip().lower())


# ---------------------------------------------------------------------------
# Sheet loaders
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_bet_market(market: str, bet: str) -> Tuple[str, str]:
    """Normalize market/bet strings from Sheet1 for :class:`BetKey`."""

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
    """Return a normalized book key matching Odds API identifiers."""

    x = (s or "").strip().lower()
    return {"betonline.ag": "betonline", "betonlineag": "betonline"}.get(x, x)


def _build_events(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Iterable[Dict[str, int]]]]:
    """Convert Detailed Odds rows into API-like event structures."""

    events: Dict[str, Dict[str, Dict[str, List[Dict[str, object]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for r in rows:
        ev_id = (r.get("Event ID") or "").strip()
        book = _norm_book(r.get("Bookmaker") or r.get("Book", ""))
        market = (r.get("API Market") or r.get("Market") or "").strip()
        name = r.get("Outcome Name (Normalized)", "")
        point = r.get("Outcome Point", "")
        price_s = (r.get("Odds") or "").replace(" ", "").strip()
        if not (ev_id and book and market and price_s):
            continue
        try:
            price = int(price_s)
        except Exception:
            continue

        outcome: Dict[str, object] = {"name": name, "price": price}
        if point:
            outcome["point"] = point
        events[ev_id][book][market].append(outcome)

    out: Dict[str, Dict[str, object]] = {}
    for ev_id, books in events.items():
        bms = []
        for book, markets in books.items():
            mkts = []
            for mkey, outs in markets.items():
                mkts.append({"key": mkey, "outcomes": outs})
            bms.append({"key": book, "markets": mkts})
        out[ev_id] = {"bookmakers": bms}
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    header, bet_rows = load_bets()
    det_rows = load_detailed_odds()

    events = _build_events(det_rows)
    event_consensus: Dict[str, Dict[BetKey, object]] = {}
    for ev_id, event in events.items():
        # Intentionally call extract_book_quotes for explicitness/logging.
        extract_book_quotes(event, config.ALLOWED_BOOKS)
        event_consensus[ev_id] = compute_consensus(event, config.ALLOWED_BOOKS)

    def col(name: str) -> int:
        return header.index(name) + 1 if name in header else -1

    c_event = col("Event ID")
    c_market = col("Market")
    c_bet = col("Bet")
    c_entry = col("Odds")
    c_close = col("Closing Line")
    c_clv = col("CLV%")

    if min(c_event, c_market, c_bet, c_entry, c_close, c_clv) < 0:
        warn(
            "Missing required columns in Bets (need: Event ID, Market, Bet, Odds, Closing Line, CLV%).",
        )
        return

    ws = sheets.open_ws(config.GOOGLE_SHEET_ID, config.BET_SHEET_TAB)
    updated = 0

    for i, row in enumerate(bet_rows, start=config.BET_FIRST_DATA_ROW):
        ev_id = (row[c_event - 1] if c_event - 1 < len(row) else "").strip()
        market = (row[c_market - 1] if c_market - 1 < len(row) else "").strip()
        bet = (row[c_bet - 1] if c_bet - 1 < len(row) else "").strip()
        entry = (row[c_entry - 1] if c_entry - 1 < len(row) else "").strip()
        if not (ev_id and market and bet and entry):
            continue

        mkt, label = parse_bet_market(market, bet)
        key = BetKey(mkt, label)
        res = event_consensus.get(ev_id, {}).get(key)
        if not res or not res.consensus_probability or not res.consensus_odds:
            warn(f"No consensus for {ev_id} {label}")
            continue

        p_entry = american_to_prob(entry)
        if not p_entry or p_entry <= 0:
            warn(f"Invalid entry odds '{entry}' for {ev_id} {label}")
            continue

        clv_pct = (res.consensus_probability / p_entry - 1.0) * 100.0
        ws.update_cell(i, c_close, str(res.consensus_odds))
        ws.update_cell(i, c_clv, f"{clv_pct:.2f}")
        info(
            f"{ev_id} {label}: books={res.books} consensus_odds={res.consensus_odds} prob={res.consensus_probability:.4f}"
        )
        updated += 1

    info(f"Updated {updated} rows with Closing Line & CLV%.")


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()

