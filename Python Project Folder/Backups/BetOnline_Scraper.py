import os
import time
import random
import csv
import re
import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ---------------------------------------------------------
# CONFIG & MAPPINGS
# ---------------------------------------------------------
RECOGNIZED_SPORTS = {"Basketball", "Hockey", "Football", "Tennis", "Soccer", "Baseball"}

FALLBACK_SPORT_BY_LEAGUE = {
    "NCAA": "Basketball",
    "ATP": "Tennis",
    "WTA": "Tennis",
    "MLB": "Baseball",
    "NHL": "Hockey",
    "NFL": "Football",
}

THREE_POINT_KEYWORDS = [
    "3 point", "3-point", "3pt", "three point", "3 point field goals"
]

TEAM_NAME_MAPPING = {
    "NY":  "New York Knicks",
    "BOS": "Boston Celtics",
    "MIA": "Miami Heat",
    "LAL": "Los Angeles Lakers",
    "CHA": "Charlotte Hornets",
    "CLE": "Cleveland Cavaliers",
}

TEAM_SCHEDULE = {
    ("NY", "2025-03-19"): "Charlotte Hornets",
    ("NY", "2025-03-20"): "Philadelphia 76ers",
}

# ---------------------------------------------------------
# UTILITY FUNCTIONS
# ---------------------------------------------------------
def random_delay(base=1.0, variation=0.5):
    """Return a random float between (base - variation) and (base + variation)."""
    return random.uniform(base - variation, base + variation)

def init_driver():
    from selenium.webdriver.chrome.options import Options
    print("DEBUG: Starting Chrome with your user profile + stealth settings...")
    options = Options()
    # Adjust these paths for your local environment
    options.add_argument(r'--user-data-dir=C:\Users\jason\AppData\Local\Google\Chrome\User Data')
    options.add_argument('--profile-directory=Default')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    # Remove navigator.webdriver property
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': '''
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
        '''
    })
    return driver


def read_existing_bet_ids(csv_file_path="Bet_Tracking.csv"):
    existing_ids = set()
    if os.path.isfile(csv_file_path):
        with open(csv_file_path, newline="") as file:
            for row in csv.DictReader(file):
                bet_id = row.get("Bet ID#", "").strip()
                if bet_id:
                    existing_ids.add(bet_id)
    return existing_ids

def parse_float_safe(s):
    """Return float(s) or 0.0 if invalid."""
    try:
        return float(s)
    except:
        return 0.0

def american_odds_to_decimal(american_str):
    """
    Convert American odds (e.g. "-120", "+140") to decimal odds float.
    Return None if invalid.
    e.g. "-120" => ~1.8333, "+140" => 2.4
    """
    try:
        am = float(american_str)
        if am > 0:
            return 1.0 + (am / 100.0)
        else:
            return 1.0 + (100.0 / abs(am))
    except:
        return None

def decimal_to_american_str(dec_odds):
    """
    Convert decimal odds (e.g. 1.8333) back to an American odds string (e.g. "-120").
    Return None if dec_odds <= 1.
    """
    if dec_odds <= 1.0:
        return None
    prob = 1.0 / dec_odds
    if prob >= 0.5:
        neg = -100 * (prob / (1 - prob))
        return f"{neg:.0f}"
    else:
        pos = 100 * ((1 - prob) / prob)
        return f"+{pos:.0f}"

# ---------------------------------------------------------
# CSV UPDATE: FILL MISSING ODDS, CALCULATE PROFIT/LOSS
# ---------------------------------------------------------
def update_csv_betonline(bets, csv_file_path="Bet_Tracking.csv"):
    """
    1) If odds are missing and result != 'Loss', compute from stake + toWin => decimal => American.
    2) If 'Win', compute netProfit from final American odds => stake*(decOdds - 1).
    """
    file_exists = os.path.isfile(csv_file_path)
    existing_ids = read_existing_bet_ids(csv_file_path)
    fieldnames = [
        "Date", "Start Time", "Event ID", "Sport", "League", "Market", "Derivative",
        "Event/Match", "Bet", "Odds", "Stake", "Bookmaker", "Payout",
        "Closing Line", "CLV%", "Profit/Loss", "Notes/Comments", "Bet ID#", "Result"
    ]
    if not bets:
        print("DEBUG: No new bets to write.")
        return

    with open(csv_file_path, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        wrote_count = 0
        for b in bets:
            bet_id = b.get("betId", "Unknown")
            if bet_id in existing_ids:
                print(f"DEBUG: Skipping duplicate bet ID {bet_id}")
                continue

            # Clean up data
            date_str = b.get("eventDate", "")
            start_str = b.get("startTime", "")
            event_match = b.get("matchup", "").replace("/", " vs ")
            market_str = b.get("market", "").lower()
            derivative = "Yes" if any(market_str.endswith(s) for s in ["_q1", "_q2", "_q3", "_q4", "_h1", "_h2"]) else "No"
            odds_str = b.get("odds", "").strip()

            stake_str = b.get("stakeAmount", "0")
            stake_val = parse_float_safe(stake_str)
            towin_str = b.get("toWinAmount", "0")
            towin_val = parse_float_safe(towin_str)
            payout_str = b.get("payoutAmount", "0")
            result_str = b.get("result", "Pending")

            # (A) If no explicit odds & result != Loss, compute from stake + toWin
            if not odds_str and result_str != "Loss" and stake_val > 0 and towin_val > 0:
                dec_odds = 1.0 + (towin_val / stake_val)
                newly_computed = decimal_to_american_str(dec_odds)
                if newly_computed:
                    odds_str = newly_computed
                    print(f"DEBUG: Computed missing odds => {odds_str} from stake={stake_val}, toWin={towin_val}")

            # (B) Profit/Loss logic
            # If "Win", parse final odds => decimal => netProfit = stake*(decimal-1)
            # If that fails, fallback to toWin
            profit_loss = ""
            if result_str == "Win":
                dec = american_odds_to_decimal(odds_str) if odds_str else None
                if dec and dec > 1.0:
                    net_profit = stake_val * (dec - 1.0)
                    profit_loss = f"{net_profit:.2f}"
                else:
                    # fallback to toWin as net
                    profit_loss = f"{towin_val:.2f}" if towin_val else ""
            elif result_str == "Loss":
                profit_loss = f"{-stake_val:.2f}"
            elif result_str == "Refund":
                profit_loss = "0.00"

            writer.writerow({
                "Date": date_str,
                "Start Time": start_str,
                "Event ID": "",
                "Sport": b.get("sport", ""),
                "League": b.get("league", "") or "Unknown",
                "Market": market_str,
                "Derivative": derivative,
                "Event/Match": event_match,
                "Bet": b.get("betSelection", ""),
                "Odds": odds_str,
                "Stake": stake_str,
                "Bookmaker": "Betonline",
                "Payout": payout_str,
                "Closing Line": "",
                "CLV%": "",
                "Profit/Loss": profit_loss,
                "Notes/Comments": b.get("notes", ""),
                "Bet ID#": bet_id,
                "Result": result_str
            })
            wrote_count += 1

    print(f"DEBUG: Wrote {wrote_count} new Betonline bets to '{csv_file_path}' (duplicates skipped).")

# ---------------------------------------------------------
# PARSE LOGIC
# ---------------------------------------------------------
def parse_event_date_ymd(date_str):
    """Convert "03/19/2025" or "03/19/25" => "2025-03-19" (YYYY-MM-DD)."""
    try:
        if re.search(r"/\d{2}$", date_str):
            date_str = re.sub(r"(\d{2}/\d{2}/)(\d{2})$", r"\g<1>20\g<2>", date_str)
        dt = datetime.datetime.strptime(date_str, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except:
        return ""

def parse_start_time(raw_text):
    match = re.search(r"\b(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)", raw_text, re.IGNORECASE)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = match.group(2)
    ampm = match.group(4).upper()
    if ampm == "PM" and hour < 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}"

def is_player_prop(raw_text):
    lower = raw_text.lower()
    has_team_code = bool(re.search(r"\([A-Z]{2,3}\)", raw_text))
    has_stat_words = bool(re.search(r"(points|rebounds|assists)", raw_text, re.IGNORECASE))
    if re.search(r"spread", raw_text, re.IGNORECASE) or re.search(r"\s+vs\s+", raw_text, re.IGNORECASE):
        return False
    return (has_team_code or has_stat_words)

def infer_league_from_team(team_code):
    nba_teams = {"CHA","NY","NYK","LAL","BOS","MIA","POR","UTH","PHI","IND","WAS","CLE","SAC"}
    return "NBA" if team_code.upper() in nba_teams else ""

def trim_non_player_prop(selection):
    selection = re.sub(r"^\d+\s+", "", selection)
    selection = re.sub(r"\bbuying\b", "", selection, flags=re.IGNORECASE)
    selection = re.sub(r"\bFor Game\b", "", selection, flags=re.IGNORECASE)
    selection = re.sub(r"\s*[+\-]\s*(?:½|1/2|\.5)", "", selection, flags=re.IGNORECASE)
    selection = re.sub(r"\s+", " ", selection).strip()
    return selection

def parse_bet_card_python(container_text, short_bet_id="Unknown"):
    raw = container_text.strip()
    bet_data = {
        "betId": short_bet_id,
        "eventDate": "",
        "startTime": "",
        "sport": "Unknown",
        "league": "",
        "market": "",
        "matchup": "",
        "betSelection": "",
        "odds": "",
        "stakeAmount": "",
        "toWinAmount": "",
        "payoutAmount": "",
        "result": "",
        "notes": raw
    }

    # Ticket number
    ticket_match = re.search(r"Ticket\s+(?:Number|#)\s*[:\s]*([\d-]+)", raw, re.IGNORECASE)
    if ticket_match:
        bet_data["betId"] = ticket_match.group(1).strip()

    # Event date => YYYY-MM-DD
    date_match = re.search(r"\b(\d{2}\/\d{2}\/\d{2,4})\b", raw)
    if date_match:
        date_ymd = parse_event_date_ymd(date_match.group(1))
        if date_ymd:
            bet_data["eventDate"] = date_ymd

    # Start time => "10:10:00 PM" => "22:10"
    bet_data["startTime"] = parse_start_time(raw)

    # Stake & toWin
    amount_match = re.search(r"Amount:\s*\$([\d.]+)", raw, re.IGNORECASE)
    if amount_match:
        bet_data["stakeAmount"] = amount_match.group(1)

    towin_match = re.search(r"To\s*Win:\s*\$([\d.]+)", raw, re.IGNORECASE)
    if towin_match:
        bet_data["toWinAmount"] = towin_match.group(1)

    # If the site shows "Payout: $xxx"
    payout_match = re.search(r"Payout:\s*\$([\d.]+)", raw, re.IGNORECASE)
    if payout_match:
        bet_data["payoutAmount"] = payout_match.group(1)

    # Odds => "Odds: -120"
    odds_match = re.search(r"Odds:\s*([+-]\d{2,4}(?:\.\d+)?)", raw, re.IGNORECASE)
    if odds_match:
        bet_data["odds"] = odds_match.group(1)

    # Result => store as "Win"/"Loss"/"Refund"/"Pending"
    status_match = re.search(r"Status:\s*(Pending|Won|Lost|Refund)", raw, re.IGNORECASE)
    if status_match:
        st_lower = status_match.group(1).lower()
        if st_lower == "won":
            bet_data["result"] = "Win"
        elif st_lower == "lost":
            bet_data["result"] = "Loss"
        elif st_lower == "refund":
            bet_data["result"] = "Refund"
        else:
            bet_data["result"] = "Pending"

    # Decide if player prop
    if is_player_prop(raw):
        # default sport => "Basketball"
        if not bet_data["eventDate"]:
            now = datetime.datetime.now()
            bet_data["eventDate"] = now.strftime("%Y-%m-%d")

        bet_data["sport"] = "Basketball"
        team_code_match = re.search(r"\(([A-Z]{2,3})\)", raw)
        if team_code_match:
            code = team_code_match.group(1).upper()
            guess_league = infer_league_from_team(code)
            bet_data["league"] = guess_league if guess_league else "NBA"
            from_user_team = TEAM_NAME_MAPPING.get(code, code)
            key = (code, bet_data["eventDate"])
            if key in TEAM_SCHEDULE:
                opponent = TEAM_SCHEDULE[key]
                bet_data["matchup"] = f"{from_user_team} vs {opponent}"
            else:
                bet_data["matchup"] = from_user_team
        else:
            bet_data["league"] = "NBA"
            bet_data["matchup"] = "N/A"

        lower = raw.lower()
        if "rebounds" in lower:
            bet_data["market"] = "player_rebounds"
        elif "points" in lower and "reb" not in lower and "ast" not in lower:
            bet_data["market"] = "player_points"
        elif "assists" in lower:
            bet_data["market"] = "player_assists"
        elif ("pts" in lower and "reb" in lower and "ast" in lower) or ("points + rebounds + assists" in lower):
            bet_data["market"] = "player_points_rebounds_assists"
        else:
            if any(k in lower for k in THREE_POINT_KEYWORDS):
                bet_data["market"] = "player_threes"

        # multi-word name => "Josh Hart (NY) Under 12.5 Points"
        player_line = re.search(
            r"([A-Za-z.'-]+(?:\s+[A-Za-z.'-]+)*\s*\([A-Z]{2,3}\)\s+(Over|Under)\s+\d+(?:\.\d+)?\s*(Points|Rebounds|Assists)?)",
            raw,
            re.IGNORECASE
        )
        if player_line:
            bet_data["betSelection"] = player_line.group(1).strip()
        else:
            fallback_line = re.search(r"(Over|Under)\s+[\d.]+(\s+Points|\s+Rebounds|\s+Assists)?", raw, re.IGNORECASE)
            bet_data["betSelection"] = fallback_line.group(0).strip() if fallback_line else raw

    else:
        # Non-player approach
        parts = raw.split(" | ")
        if len(parts) > 0:
            chunk0 = parts[0].strip()
            chunk_split = chunk0.split(" - ")
            if len(chunk_split) >= 3:
                bet_data["sport"]  = chunk_split[0].strip()
                bet_data["league"] = chunk_split[1].strip()
                bet_data["matchup"] = chunk_split[2].strip()
                if len(chunk_split) >= 4:
                    maybe_mkt = chunk_split[3].lower()
                    if "spread" in maybe_mkt:
                        bet_data["market"] = "spreads"
                    elif "total" in maybe_mkt:
                        bet_data["market"] = "totals"
                    elif "moneyline" in maybe_mkt:
                        bet_data["market"] = "h2h"

        if len(parts) > 1:
            selection_chunk = parts[1].strip()
            odds_reg = re.search(r"[+\-]\d{2,3}(?:\.\d+)?", selection_chunk)
            if odds_reg:
                bet_data["odds"] = odds_reg.group(0)
                selection_chunk = selection_chunk.replace(odds_reg.group(0), "")
            selection_chunk = trim_non_player_prop(selection_chunk)
            bet_data["betSelection"] = selection_chunk

        if len(parts) > 2:
            dstr = parts[2].strip()
            d_ymd = parse_event_date_ymd(dstr)
            if d_ymd:
                bet_data["eventDate"] = d_ymd

        if len(parts) > 3:
            tstr = parts[3].strip()
            bet_data["startTime"] = parse_start_time(tstr)

        if len(parts) > 4:
            rstr = parts[4].strip()
            if re.match(r"^(lost|won|pending|refund)$", rstr, re.IGNORECASE):
                if rstr.lower() == "won":
                    bet_data["result"] = "Win"
                elif rstr.lower() == "lost":
                    bet_data["result"] = "Loss"
                elif rstr.lower() == "refund":
                    bet_data["result"] = "Refund"
                else:
                    bet_data["result"] = "Pending"

    # If date is still missing => fallback to today
    if not bet_data["eventDate"]:
        now = datetime.datetime.now()
        bet_data["eventDate"] = now.strftime("%Y-%m-%d")

    # Fallback for "Unknown" sport if league is recognized
    sp = bet_data["sport"]
    if not sp or sp == "Unknown" or sp not in RECOGNIZED_SPORTS:
        league_up = bet_data["league"].upper()
        for key, val in FALLBACK_SPORT_BY_LEAGUE.items():
            if key in league_up and val in RECOGNIZED_SPORTS:
                bet_data["sport"] = val
                break

    return bet_data

# ---------------------------------------------------------
# MAIN LOGIC
# ---------------------------------------------------------
def main():
    try:
        driver = init_driver()

        target_url = "https://www.betonline.ag/my-account/bet-history"
        print("DEBUG: Navigating directly to Bet History page...")
        driver.get(target_url)

        print("DEBUG: Waiting for the Bet History page to load...")
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[id^='row-']"))
            )
            print("DEBUG: Bet rows found! Page loaded.")
        except TimeoutException:
            print("DEBUG: Timed out waiting for bet rows to appear.")

        existing_ids = read_existing_bet_ids("Bet_Tracking.csv")
        print(f"DEBUG: Found {len(existing_ids)} existing Bet IDs in CSV.")

        bet_rows = driver.find_elements(By.CSS_SELECTOR, "[id^='row-']")
        print(f"DEBUG: Found {len(bet_rows)} bet rows on the page.")

        new_bets_data = []

        # Expand each row, parse container, store results
        for row in bet_rows:
            try:
                bet_id_elem = row.find_element(By.CSS_SELECTOR, "div.bet-history__table__body__rows__columns--id")
                short_bet_id = bet_id_elem.text.strip()
                if short_bet_id in existing_ids:
                    print(f"DEBUG: Skipping {short_bet_id} (already in CSV).")
                    continue

                print(f"DEBUG: Expanding bet {short_bet_id}")
                expand_icon = bet_id_elem.find_element(By.TAG_NAME, "i")
                ActionChains(driver).move_to_element(expand_icon).pause(random_delay(1,0.5)).click().perform()
                time.sleep(random_delay(2,1))

                row_id = row.get_attribute("id")  # e.g. "row-3"
                row_index = row_id.split("-")[-1]
                container_id = f"bethistory-{row_index}"
                try:
                    container = driver.find_element(By.CSS_SELECTOR, f"#{container_id}")
                except NoSuchElementException:
                    print(f"DEBUG: No expanded container found for {row_id} => {container_id}.")
                    continue

                container_text = container.text
                bet_data = parse_bet_card_python(container_text, short_bet_id=short_bet_id)
                if bet_data["betId"] not in existing_ids and bet_data["betId"] != "Unknown":
                    new_bets_data.append(bet_data)
                else:
                    print(f"DEBUG: Skipping container. Bet ID is '{bet_data['betId']}' or already in CSV.")
            except Exception as e:
                print("DEBUG: Error expanding/parsing row:", e)
                time.sleep(random_delay(1,0.5))

        update_csv_betonline(new_bets_data, "Bet_Tracking.csv")
        input("DEBUG: Press ENTER to close the browser...")
        driver.quit()
        print("DEBUG: Browser closed. Script ended.")
    except Exception as e:
        print("DEBUG: Unexpected error:", e)
        input("DEBUG: Press ENTER to close the browser...")

if __name__ == "__main__":
    main()


