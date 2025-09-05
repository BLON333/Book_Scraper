import re
import sys
import time
from pathlib import Path
from typing import List

import requests

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT / "Python Project Folder"))
from core import sheets

import config

"""Synchronize odds data from The Odds API to Google Sheets."""

def _norm_team(s: str) -> str:
    s = (s or "").strip()
    # very light normalization; expand as needed
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bSt(?!\.)\b", "State", s, flags=re.I)
    s = s.replace("Â½","½")
    return s

def refresh_live_odds():
    ws = sheets.open_ws(config.GOOGLE_SHEET_ID, config.LIVE_ODDS_TAB)
    header = ["League", "Event ID", "Event/Match", "Commence Time", "Bookmaker Count"]
    sheets.write_header(ws, header)

    rowbuf = []
    for league in config.LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/odds"
        params = {
            "apiKey": config.ODDS_API_KEY,
            "regions": config.ODDS_REGIONS,
            "oddsFormat": config.ODDS_FORMAT,
            "markets": "h2h,spreads,totals"
        }
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            print(f"[WARN] Live odds {league} HTTP {r.status_code}: {r.text[:200]}")
            continue
        data = r.json()
        for evt in data:
            home = _norm_team(evt.get("home_team",""))
            away = _norm_team(evt.get("away_team",""))
            matchup = f"{home} vs {away}".strip()
            event_id = evt.get("id","")
            commence = evt.get("commence_time","")
            bk_count = len(evt.get("bookmakers",[]))
            rowbuf.append([league, event_id, matchup, commence, bk_count])

    if rowbuf:
        ws.update(f"A2", rowbuf, value_input_option="USER_ENTERED")
    print(f"[Live Odds] Wrote {len(rowbuf)} rows.")

def _build_user_market_and_label(mkt_key: str, outcome: dict, league: str, bet_select_hint: str = "") -> (str, str, str):
    """
    Returns (user_market, name_norm, point_str)
    - user_market is one of 'h2h','spreads','totals' plus any alternate normalized away
    - name_norm is team name for h2h/spreads, or 'Over'/'Under' for totals
    - point_str is outcome.point (may be signed for spreads, numeric for totals)
    """
    key = (mkt_key or "").lower().strip()
    if key.startswith("alternate_"):
        key = key.replace("alternate_", "", 1)

    name = outcome.get("name","") or ""
    desc = outcome.get("description","") or ""
    point = outcome.get("point","")
    # totals: keep Over/Under in name_norm
    if key == "totals":
        name_norm = name.split()[0].title()  # Over or Under
        return "totals", name_norm, str(point or "").replace("Â½","½")
    # spreads: name is team, keep signed point
    elif key == "spreads":
        name_norm = _norm_team(name)
        p = str(point or "")
        if p and not p.startswith(("+","-")):
            p = f"+{p}"
        return "spreads", name_norm, p.replace("Â½","½")
    else:
        # h2h
        name_norm = _norm_team(name or desc)
        return "h2h", name_norm, ""

def _rows_for_event(event_id: str, user_market: str, bet_select: str, league: str) -> List[List[str]]:
    """
    Fetch per-event odds for allowed books and build rows for Detailed Odds.
    """
    rows = []
    markets = []
    if user_market.lower().startswith("spreads"):
        markets = ["spreads","alternate_spreads"]
    elif user_market.lower().startswith("totals"):
        markets = ["totals","alternate_totals"]
    elif user_market.lower() in ("h2h","moneyline","ml"):
        markets = ["h2h"]
    elif user_market.lower().startswith("player_"):
        # out of scope for CLV sync today; skip quietly
        return rows
    else:
        return rows

    url = f"https://api.the-odds-api.com/v4/sports/{league}/events/{event_id}/odds"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": config.ODDS_REGIONS,
        "oddsFormat": config.ODDS_FORMAT,
        "markets": ",".join(markets)
    }
    r = requests.get(url, params=params, timeout=25)
    if r.status_code != 200:
        print(f"[WARN] Event {event_id} {league} HTTP {r.status_code}: {r.text[:200]}")
        return rows

    data = r.json()
    for bk in data.get("bookmakers", []):
        if bk.get("key","") not in config.ALLOWED_BOOKS:
            continue
        bk_title = bk.get("title","")
        for m in bk.get("markets", []):
            api_mkt = m.get("key","")
            for oc in m.get("outcomes", []):
                user_mkt, name_norm, pt = _build_user_market_and_label(api_mkt, oc, league, bet_select)
                # Only keep the primary family that matches our bet intent
                fam = user_market.split("_")[0].lower()
                if user_mkt != fam:
                    continue
                rows.append([
                    event_id,
                    user_mkt,
                    bet_select,
                    bk_title,
                    api_mkt,
                    name_norm,
                    str(pt),
                    str(oc.get("price",""))
                ])
    return rows

def refresh_detailed_odds_from_bets():
    ws_bets = sheets.open_ws(config.GOOGLE_SHEET_ID, config.BET_SHEET_TAB)

    # read Event ID (col 3), Market (6), Bet (9) from bet rows
    event_ids = ws_bets.col_values(3)[config.BET_FIRST_DATA_ROW-1:]   # C
    markets   = ws_bets.col_values(6)[config.BET_FIRST_DATA_ROW-1:]   # F
    bets      = ws_bets.col_values(9)[config.BET_FIRST_DATA_ROW-1:]   # I

    triplets = []
    for eid, mkt, sel in zip(event_ids, markets, bets):
        eid = (eid or "").strip()
        mkt = (mkt or "").strip().lower()
        sel = (sel or "").strip()
        if eid and mkt and sel:
            triplets.append((eid, mkt, sel))

    ws_det = sheets.open_ws(config.GOOGLE_SHEET_ID, config.DETAILED_ODDS_TAB)
    header = [
        "Event ID","User Market","User Bet Selection","Bookmaker",
        "API Market","Outcome Name (Normalized)","Outcome Point","Odds"
    ]
    sheets.write_header(ws_det, header)

    out_rows = []
    for i, (eid, mkt, sel) in enumerate(triplets, start=1):
        # try each league until the event is found
        found_any = False
        for league in config.LEAGUES:
            rs = _rows_for_event(eid, mkt, sel, league)
            if rs:
                out_rows.extend(rs)
                found_any = True
                break
        if not found_any:
            # not fatal, skip if The Odds API doesn't know that event under our chosen leagues
            pass
        # small backoff to be gentle with API
        if i % 10 == 0:
            time.sleep(0.5)

    if out_rows:
        ws_det.update("A2", out_rows, value_input_option="USER_ENTERED")
    print(f"[Detailed Odds] Wrote {len(out_rows)} rows.")

def main():
    print("Refreshing Live Odds...")
    refresh_live_odds()
    print("Refreshing Detailed Odds (from Bets)...")
    refresh_detailed_odds_from_bets()
    print("Done.")

if __name__ == "__main__":
    main()
