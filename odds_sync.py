import re
import sys
import time
from pathlib import Path
from typing import List, Tuple
import requests
from core import sheets
import config

ROOT = Path(__file__).resolve().parent
sys.path.append(str(ROOT))

def _norm_team(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("Â½", "½")
    return s

def refresh_live_odds():
    ws_live = sheets.open_ws(config.GOOGLE_SHEET_ID, config.LIVE_ODDS_TAB)
    header = ["League", "Event ID", "Event/Match", "Commence Time", "Bookmaker Count"]
    sheets.write_header(ws_live, header, header_row=1)
    rows: List[List[str]] = []
    for league in config.LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/odds"
        params = {"apiKey": config.ODDS_API_KEY, "regions": config.ODDS_REGIONS, "oddsFormat": config.ODDS_FORMAT, "markets": "h2h,spreads,totals"}
        try:
            r = requests.get(url, params=params, timeout=20)
        except Exception as e:
            print(f"[ERROR] Live odds request failed for {league}: {e}")
            continue
        if r.status_code != 200:
            print(f"[WARN] Live odds {league} HTTP {r.status_code}: {r.text[:200]}")
            continue
        for ev in r.json():
            home = _norm_team(ev.get("home_team", ""))
            away = _norm_team(ev.get("away_team", ""))
            matchup = f"{home} vs {away}" if (home and away) else (ev.get("sport_title") or "")
            rows.append([league, ev.get("id",""), matchup, ev.get("commence_time",""), len(ev.get("bookmakers", []))])
    if rows:
        ws_live.update("A2", rows, value_input_option="USER_ENTERED")
    print(f"[Live Odds] Wrote {len(rows)} events across {len(config.LEAGUES)} leagues.")

def _user_market_and_label(api_market: str, outcome: dict) -> Tuple[str,str,str]:
    key = (api_market or "").lower().strip()
    if key.startswith("alternate_"):
        key = key.replace("alternate_", "", 1)
    name = outcome.get("name") or outcome.get("description") or ""
    point = outcome.get("point", "")
    if key == "totals":
        side = name.split()[0].title() if name else ""
        return "totals", side, str(point).replace("Â½","½")
    if key == "spreads":
        nm = _norm_team(name)
        p = str(point or "")
        if p and p[0] not in "+-":
            p = f"+{p}"
        return "spreads", nm, p.replace("Â½","½")
    return "h2h", _norm_team(name), ""

def _fetch_event_odds(event_id: str, user_market: str, user_selection: str, league: str) -> List[List[str]]:
    m = user_market.lower()
    if m.startswith("spread"):
        mkts = "spreads,alternate_spreads"
    elif m.startswith("total"):
        mkts = "totals,alternate_totals"
    elif m in ("h2h","moneyline","ml"):
        mkts = "h2h"
    else:
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{league}/events/{event_id}/odds"
    params = {"apiKey": config.ODDS_API_KEY, "regions": config.ODDS_REGIONS, "oddsFormat": config.ODDS_FORMAT, "markets": mkts}
    try:
        r = requests.get(url, params=params, timeout=25)
    except Exception as e:
        print(f"[ERROR] Event odds failed {event_id}: {e}")
        return []
    if r.status_code != 200:
        print(f"[WARN] Event odds {event_id} ({league}) HTTP {r.status_code}: {r.text[:200]}")
        return []
    rows: List[List[str]] = []
    for bk in r.json().get("bookmakers", []):
        if bk.get("key") not in config.ALLOWED_BOOKS:
            continue
        bkname = bk.get("title") or bk.get("key")
        for market in bk.get("markets", []):
            api_key = market.get("key","")
            for oc in market.get("outcomes", []):
                user_mkt, name_norm, point_str = _user_market_and_label(api_key, oc)
                base = "h2h" if m in ("h2h","ml","moneyline") else ("spreads" if m.startswith("spread") else "totals")
                if user_mkt != base:
                    continue
                odds = str(oc.get("price",""))
                rows.append([event_id, user_mkt, user_selection, bkname, api_key, name_norm, str(point_str), odds])
    return rows

def refresh_detailed_odds_from_bets():
    ws_bets = sheets.open_ws(config.GOOGLE_SHEET_ID, config.BET_SHEET_TAB)
    event_ids = ws_bets.col_values(3)[config.BET_FIRST_DATA_ROW - 1:]  # C
    markets   = ws_bets.col_values(6)[config.BET_FIRST_DATA_ROW - 1:]  # F
    bets      = ws_bets.col_values(9)[config.BET_FIRST_DATA_ROW - 1:]  # I
    reqs = [(e.strip(), m.strip(), b.strip()) for e,m,b in zip(event_ids, markets, bets) if e and m and b]

    ws_det = sheets.open_ws(config.GOOGLE_SHEET_ID, config.DETAILED_ODDS_TAB)
    header = ["Event ID","User Market","User Bet Selection","Bookmaker","API Market","Outcome Name (Normalized)","Outcome Point","Odds"]
    sheets.write_header(ws_det, header, header_row=1)

    all_rows: List[List[str]] = []
    for idx, (eid, mkt, sel) in enumerate(reqs, 1):
        for league in config.LEAGUES:
            rows = _fetch_event_odds(eid, mkt, sel, league)
            if rows:
                all_rows.extend(rows)
                break
        if idx % 10 == 0:
            time.sleep(0.5)
    if all_rows:
        ws_det.update("A2", all_rows, value_input_option="USER_ENTERED")
    print(f"[Detailed Odds] Wrote {len(all_rows)} rows for {len(reqs)} bets.")

def main():
    print("Odds sync starting...")
    refresh_live_odds()
    refresh_detailed_odds_from_bets()
    print("Odds sync completed.")

if __name__ == "__main__":
    main()
