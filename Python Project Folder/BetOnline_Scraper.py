import os
import sys
import time
import random
import csv
import re
import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
def csv_path(name="Bet_Tracking.csv"):
    return os.path.join(REPO_ROOT, name)

import config

SERVICE_ACCOUNT_FILE = os.path.join(REPO_ROOT, "credentials.json")

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ---------------------------------------------------------
# OFFICIAL TEAM MAPPING & CANONICALIZATION
# ---------------------------------------------------------
OFFICIAL_TEAM_MAPPING = {
    "byu cougars": "byu",
    "iowa state cyclones": "iowa state",
    # Add or modify mappings as needed
}

def canonicalize_matchup(match_str, team_mapping=OFFICIAL_TEAM_MAPPING):
    """
    Normalize a matchup string by splitting on ' vs ' or '@', then
    mapping teams to simpler names if present in OFFICIAL_TEAM_MAPPING.
    Sort them so it's consistent. 'A vs B' => 'a vs b'.
    """
    s = match_str.lower().strip()
    if " vs " in s:
        teams = s.split(" vs ")
    elif "@" in s:
        teams = s.split("@")
    else:
        teams = [s]
    canonical_teams = [team_mapping.get(team.strip(), team.strip()) for team in teams]
    canonical_teams.sort()
    return " vs ".join(canonical_teams)


def _looks_like_sheet_id(value: str) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    if len(v) < 25:
        return False
    return all(c.isalnum() or c in "-_" for c in v)


def _resolve_sheet_id_and_tab(spreadsheet_id=None, sheet_name=None):
    if spreadsheet_id and _looks_like_sheet_id(spreadsheet_id):
        sid = spreadsheet_id.strip()
        tab = sheet_name or getattr(config, "LIVE_ODDS_TAB", "Live Odds")
    else:
        sid = getattr(config, "GOOGLE_SHEET_ID", "").strip()
        tab = sheet_name or spreadsheet_id or getattr(config, "LIVE_ODDS_TAB", "Live Odds")
    print(f"DEBUG: Using spreadsheet_id='{sid}', sheet_name='{tab}'")
    return sid, tab

# ---------------------------------------------------------
# CONFIGURATION & CONSTANTS
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
THREE_POINT_KEYWORDS = ["3 point", "3-point", "3pt", "three point", "3 point field goals"]

TEAM_NAME_MAPPING = {
    "NY":  "New York Knicks",
    "BOS": "Boston Celtics",
    "MIA": "Miami Heat",
    "LAL": "Los Angeles Lakers",
    "CHA": "Charlotte Hornets",
    "CLE": "Cleveland Cavaliers",
    # etc.
}

TEAM_SCHEDULE = {
    # (team_code, eventDate) : "Opponent Name"
    ("NY", "2025-03-19"): "Charlotte Hornets",
    ("NY", "2025-03-20"): "Philadelphia 76ers",
}

CAD_CONVERSION_RATE = 1.44  # Convert USD => CAD
STATIC_WAIT_SECONDS = int(os.getenv("STATIC_WAIT_SECONDS", "20"))

# ---------------------------------------------------------
# UTILITY FUNCTIONS
# ---------------------------------------------------------
def random_delay(base=1.0, variation=0.5):
    """Return a random float between (base - variation) and (base + variation)."""
    return random.uniform(base - variation, base + variation)

def simulate_random_mouse_movement(driver, moves=3):
    """
    Add small random mouse movements to appear more human-like.
    """
    try:
        for _ in range(moves):
            offset_x = random.randint(-20, 20)
            offset_y = random.randint(-20, 20)
            ActionChains(driver).move_by_offset(offset_x, offset_y).perform()
            time.sleep(random_delay(0.3, 0.2))
    except Exception as e:
        print("DEBUG: Mouse movement error:", e)

def init_driver():
    """
    Launch Chrome either by attaching to an existing instance (if
    config.ATTACH_TO_RUNNING is True) or by starting a new session with the
    configured user profile.
    """
    from selenium.webdriver.chrome.options import Options
    print("DEBUG: Starting Chrome...")

    attach = getattr(config, "ATTACH_TO_RUNNING", False)
    options = Options()

    if attach:
        print("DEBUG: Attaching to existing Chrome at 127.0.0.1:9222")
        options.debugger_address = "127.0.0.1:9222"
    else:
        user_data_dir = getattr(
            config,
            "CHROME_USER_DATA_DIR",
            r"C:\Users\jason\ChromeProfiles\PinnacleBot",
        )
        profile_dir = getattr(config, "CHROME_PROFILE_DIR", "Default")
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory={profile_dir}")

    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def check_interstitial(driver):
    """Return True if the page shows a challenge/interstitial."""
    try:
        text = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return False
    markers = [
        "just a moment",
        "verify you are human",
        "403",
        "429",
        "forbidden",
        "too many requests",
    ]
    if any(m in text for m in markers):
        print("DEBUG: Detected possible interstitial challenge.")
        return True
    return False


def navigate_and_wait(driver, url, container_selector="#bets", timeout=60):
    """Navigate to a URL and wait for the target container to render."""
    driver.get(url)
    wait = WebDriverWait(driver, timeout)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    if check_interstitial(driver):
        return False
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, container_selector)))
    wait.until(
        lambda d: d.execute_script(
            "return document.querySelector(arguments[0]).offsetHeight",
            container_selector,
        )
        > 0
    )
    return True

def scroll_bets(driver, scroll_container_selector="#bets", pause_time=2, max_scrolls=10):
    """
    Scroll down repeatedly within the #bets container, to load all rows.
    """
    try:
        container = driver.find_element(By.CSS_SELECTOR, scroll_container_selector)
        last_height = driver.execute_script("return arguments[0].scrollHeight", container)
        for i in range(max_scrolls):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", container)
            time.sleep(pause_time)
            new_height = driver.execute_script("return arguments[0].scrollHeight", container)
            if new_height == last_height:
                print(f"DEBUG: Scrolling down complete after {i+1} iterations.")
                break
            last_height = new_height
    except Exception as e:
        print(f"DEBUG: Could not scroll container: {e}")

def scroll_bets_up(driver, scroll_container_selector="#bets", pause_time=2):
    """
    Scroll the container all the way up.
    """
    try:
        container = driver.find_element(By.CSS_SELECTOR, scroll_container_selector)
        driver.execute_script("arguments[0].scrollTop = 0", container)
        time.sleep(pause_time)
        current_top = driver.execute_script("return arguments[0].scrollTop", container)
        if current_top == 0:
            print("DEBUG: Scrolled all the way up.")
        else:
            print(f"DEBUG: Scrolling up not complete, current scrollTop: {current_top}")
    except Exception as e:
        print(f"DEBUG: Could not scroll up container: {e}")

def login_handshake_betonline(driver, max_wait_secs=120):
    """
    If bet history rows are not visible, prompt the user to log in manually.
    We poll until rows appear or timeout.
    """
    import time, sys
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    wait = WebDriverWait(driver, 5)

    def has_rows():
        try:
            driver.find_element(By.CSS_SELECTOR, "[id^='row-']")
            return True
        except Exception:
            return False

    if has_rows():
        return True

    print("[LOGIN] BetOnline: please log in in the opened window. Waiting up to", max_wait_secs, "seconds...")
    deadline = time.time() + max_wait_secs
    last = -1
    while time.time() < deadline:
        if has_rows():
            print("\n[LOGIN] Detected bet history rows. Continuing.")
            return True
        remain = int(deadline - time.time())
        if remain != last:
            last = remain
            sys.stdout.write(f"\r[LOGIN] {remain:3d}s remaining... ")
            sys.stdout.flush()
        time.sleep(1)

    print("\n[LOGIN] Timed out waiting for BetOnline login.")
    return False

def read_existing_bet_ids(csv_file_path=None):
    csv_file_path = csv_file_path or csv_path()
    existing_ids = set()
    if not os.path.isfile(csv_file_path):
        return existing_ids
    with open(csv_file_path, newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        print(f"DEBUG: '{csv_file_path}' has 0 data rows; returning empty ID set.")
        return existing_ids
    for row in rows:
        bet_id = row.get("Bet ID#", "").strip()
        if bet_id:
            existing_ids.add(bet_id)
    return existing_ids

def parse_float_safe(s):
    try:
        return float(s)
    except:
        return 0.0

def american_odds_to_decimal(american_str):
    """
    Convert e.g. -120 => 1.8333..., +150 => 2.5, etc.
    """
    try:
        val = float(american_str)
        if val > 0:
            return 1.0 + (val / 100.0)
        else:
            return 1.0 + (100.0 / abs(val))
    except:
        return None

def decimal_to_american_str(dec_odds):
    """
    Convert decimal odds => American (approx).
    E.g. 1.83 => -120, 2.5 => +150
    """
    if dec_odds <= 1.0:
        return ""
    prob = 1.0 / dec_odds
    if prob >= 0.5:
        neg = -100 * (prob / (1 - prob))
        return f"{neg:.0f}"
    else:
        pos = 100 * ((1 - prob) / prob)
        return f"+{pos:.0f}"

# ---------------------------------------------------------
# CSV UPDATE FUNCTIONS (New Bets, Grade Settled, Merge Event IDs)
# ---------------------------------------------------------
def update_csv_betonline(bets, csv_file_path=None):
    """
    Append new bets to CSV. For each bet:
      - Format date => YYYY-MM-DD
      - Convert partial fraction stake => float if needed
      - If no odds but stake & toWin are present, compute them
      - Compute profit/loss in CAD if result is Win or Loss
    """
    csv_file_path = csv_file_path or csv_path()
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

            # Format date => YYYY-MM-DD
            date_str = b.get("eventDate", "")
            try:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                date_str = dt.strftime("%Y-%m-%d")
            except:
                pass

            start_str = b.get("startTime", "")
            event_match = b.get("matchup", "").replace("/", " vs ")
            market_str = b.get("market", "").lower()

            # Derivative => "Yes" if market ends in _q1, _q2, _q3, _q4, _h1, _h2
            derivative = "Yes" if any(market_str.endswith(s) for s in ["_q1", "_q2", "_q3", "_q4", "_h1", "_h2"]) else "No"

            odds_str = b.get("odds", "").strip()
            stake_str = b.get("stakeAmount", "0")
            stake_val = parse_float_safe(stake_str)
            result_str = b.get("result", "Pending")

            # If odds missing and bet is not "loss" => maybe compute from stake & toWin
            if not odds_str and result_str.lower() != "loss":
                towin_val = parse_float_safe(b.get("toWinAmount", "0"))
                if stake_val > 0 and towin_val > 0:
                    dec_odds = 1.0 + (towin_val / stake_val)
                    computed = decimal_to_american_str(dec_odds)
                    if computed:
                        odds_str = computed
                        print(f"DEBUG: Computed missing odds => {odds_str} from stake={stake_val}, toWin={towin_val}")

            # Profit/Loss in CAD
            profit_loss = ""
            if result_str.lower() == "win":
                dec = american_odds_to_decimal(odds_str) if odds_str else None
                if dec and dec > 1.0:
                    net_profit_usd = stake_val * (dec - 1.0)
                    profit_loss = f"{net_profit_usd * CAD_CONVERSION_RATE:.2f}"
            elif result_str.lower() == "loss":
                profit_loss = f"{-stake_val * CAD_CONVERSION_RATE:.2f}"
            elif result_str.lower() == "refund":
                profit_loss = "0.00"

            row_dict = {
                "Date": date_str,
                "Start Time": start_str,
                "Event ID": b.get("eventID", ""),
                "Sport": b.get("sport", ""),
                "League": b.get("league", "") or "Unknown",
                "Market": market_str,
                "Derivative": derivative,
                "Event/Match": event_match,
                "Bet": b.get("betSelection", ""),
                "Odds": odds_str,
                "Stake": stake_str,
                "Bookmaker": "Betonline",
                "Payout": b.get("payoutAmount", ""),
                "Closing Line": "",
                "CLV%": "",
                "Profit/Loss": profit_loss,
                "Notes/Comments": b.get("notes", ""),
                "Bet ID#": bet_id,
                "Result": result_str
            }
            writer.writerow(row_dict)
            wrote_count += 1

    print(f"DEBUG: Wrote {wrote_count} new Betonline bets to '{csv_file_path}' (duplicates skipped).")

def get_bet_status_no_expand(driver, bet_id):
    """
    Return "Win", "Loss", "Refund", or "Pending" by reading the status column
    in the main table row (no expansion).
    """
    js_snippet = r"""
    return (function(bId){
      let idCells = document.querySelectorAll("div.bet-history__table__body__rows__columns--id");
      for (let cell of idCells) {
        let text = cell.innerText.trim();
        if (text === bId) {
          let rowEl = cell.closest("[id^='row-']");
          if (!rowEl) return "Pending";
          let statusEl = rowEl.querySelector("div.bet-history__table__body__rows__columns--status");
          if (!statusEl) return "Pending";
          let statusText = statusEl.innerText.trim().toLowerCase();
          if (statusText.includes("won")) return "Win";
          if (statusText.includes("lost")) return "Loss";
          if (statusText.includes("refund")) return "Refund";
          return "Pending";
        }
      }
      return "Pending";
    })(arguments[0]);
    """
    return driver.execute_script(js_snippet, bet_id)

def recalc_profit_loss(row):
    """
    Recompute Profit/Loss in CAD if the bet is now Win or Loss or Refund.
    """
    result_str = row.get("Result", "").strip().lower()
    stake_str  = row.get("Stake", "0").strip()
    odds_str   = row.get("Odds", "").strip()
    stake_val  = parse_float_safe(stake_str)
    profit_loss = ""

    if result_str == "pending":
        profit_loss = ""
    elif result_str == "refund":
        profit_loss = "0.00"
    elif result_str == "loss":
        profit_loss = f"{-stake_val * CAD_CONVERSION_RATE:.2f}"
    elif result_str == "win":
        dec = american_odds_to_decimal(odds_str) if odds_str else None
        if dec and dec > 1.0:
            net_profit_usd = stake_val * (dec - 1.0)
            profit_loss = f"{net_profit_usd * CAD_CONVERSION_RATE:.2f}"

    row["Profit/Loss"] = profit_loss
    return row

def grade_settled_bets(driver, csv_file_path=None):
    """
    For any bet in CSV that is 'Pending', see if it's now 'Won'/'Lost'/'Refund'
    in the main table, then update CSV accordingly.
    """
    csv_file_path = csv_file_path or csv_path()
    if not os.path.isfile(csv_file_path):
        print(f"DEBUG: CSV '{csv_file_path}' not found. Skipping grade_settled_bets.")
        return

    with open(csv_file_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"DEBUG: '{csv_file_path}' has 0 data rows; skipping grade_settled_bets.")
        return

    updated_count = 0
    for row in rows:
        current_result = row.get("Result", "").strip().lower()
        if current_result == "pending":
            bet_id = row.get("Bet ID#", "").strip()
            if not bet_id:
                continue
            new_status = get_bet_status_no_expand(driver, bet_id)
            if new_status in ["Win", "Loss", "Refund"]:
                row["Result"] = new_status
                row = recalc_profit_loss(row)
                updated_count += 1

    if updated_count > 0:
        fieldnames = rows[0].keys()
        with open(csv_file_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"DEBUG: Updated {updated_count} bets in '{csv_file_path}'.")
    else:
        print("DEBUG: No pending bets were updated.")

# ---------------------------------------------------------
# PARSING LOGIC FOR NEW BETS (HYBRID APPROACH)
# ---------------------------------------------------------
def parse_event_date_ymd(date_str):
    """
    Convert e.g. '03/19/25' => '2025-03-19' or '03/19/2025' => '2025-03-19'.
    """
    try:
        # If 2-digit year => expand
        if re.search(r"/\d{2}$", date_str):
            date_str = re.sub(r"(\d{2}/\d{2}/)(\d{2})$", r"\g<1>20\g<2>", date_str)
        dt = datetime.datetime.strptime(date_str, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except:
        return ""

def parse_start_time(raw_text):
    """
    Extract '10:10:00 PM' => '22:10'. If not found, return ''.
    """
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
    """
    Heuristic: if it has parentheses with 2-3 uppercase letters, plus Over/Under stats,
    it's likely a player prop. If it has 'spread' or ' vs ', it's probably not a player prop.
    """
    lower = raw_text.lower()
    has_team_code  = bool(re.search(r"\([A-Z]{2,3}\)", raw_text))
    has_stat_words = bool(re.search(r"(points|rebounds|assists)", raw_text, re.IGNORECASE))
    if re.search(r"spread", raw_text, re.IGNORECASE) or re.search(r"\s+vs\s+", raw_text, re.IGNORECASE):
        return False
    return (has_team_code or has_stat_words)

def infer_league_from_team(team_code):
    """
    Map short code => 'NBA' if recognized, else ''.
    """
    nba_teams = {"CHA","NY","NYK","LAL","BOS","MIA","POR","UTH","PHI","IND","WAS","CLE","SAC"}
    return "NBA" if team_code.upper() in nba_teams else ""

def trim_non_player_prop(selection):
    """
    Remove leading rotation #, 'For Game', 'buying',
    Convert '7½' => '7.5', remove partial fraction like +½, +.5, etc.
    """
    # remove leading rotation number (digits + space)
    selection = re.sub(r"^\d+\s+", "", selection, flags=re.IGNORECASE)
    # remove 'For Game'
    selection = re.sub(r"\bFor Game\b", "", selection, flags=re.IGNORECASE)
    # remove 'buying'
    selection = re.sub(r"\bbuying\b", "", selection, flags=re.IGNORECASE)

    # Convert e.g. '7½' => '7.5'
    selection = re.sub(r"(\d+)½", r"\1.5", selection)

    # Remove partial fraction like +½ or +.5 or +1/2
    selection = re.sub(r"\s*[+\-]\s*(?:½|1/2|\.5)", "", selection, flags=re.IGNORECASE)

    # Remove extra spaces
    selection = re.sub(r"\s+", " ", selection).strip()
    return selection

def parse_bet_card_python(container_text, short_bet_id="Unknown"):
    """
    Hybrid parse function that tries to detect if it's a player prop or a non-player prop.
    Returns a dict with all extracted fields:
      betId, eventDate, startTime, sport, league, market, matchup,
      betSelection, odds, stakeAmount, toWinAmount, payoutAmount, result, notes
    """
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
        "result": "Pending",
        "notes": raw
    }

    # A) Ticket Number
    ticket_match = re.search(r"Ticket\s+(?:Number|#)\s*[:\s]*([\d-]+)", raw, re.IGNORECASE)
    if ticket_match:
        bet_data["betId"] = ticket_match.group(1).strip()

    # B) Event Date => 'YYYY-MM-DD'
    date_match = re.search(r"\b(\d{2}\/\d{2}\/\d{2,4})\b", raw)
    if date_match:
        date_ymd = parse_event_date_ymd(date_match.group(1))
        if date_ymd:
            bet_data["eventDate"] = date_ymd

    # C) Start Time => 'HH:MM'
    bet_data["startTime"] = parse_start_time(raw)

    # D) Extract stake, toWin, payout (with commas)
    amount_match = re.search(r"Amount:\s*\$([\d,\.]+)", raw, re.IGNORECASE)
    if amount_match:
        stake_str = amount_match.group(1).replace(",", "")
        bet_data["stakeAmount"] = stake_str

    towin_match = re.search(r"To\s*Win:\s*\$([\d,\.]+)", raw, re.IGNORECASE)
    if towin_match:
        towin_str = towin_match.group(1).replace(",", "")
        bet_data["toWinAmount"] = towin_str

    payout_match = re.search(r"Payout:\s*\$([\d,\.]+)", raw, re.IGNORECASE)
    if payout_match:
        payout_str = payout_match.group(1).replace(",", "")
        bet_data["payoutAmount"] = payout_str

    # E) Extract explicit odds => "Odds: -120"
    odds_match = re.search(r"Odds:\s*([+\-]\d{2,4}(?:\.\d+)?)(?!\s*for)", raw, re.IGNORECASE)
    if odds_match:
        bet_data["odds"] = odds_match.group(1)

    # F) Extract result => "Status: Pending/Won/Lost/Refund"
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

    # G) Decide if player prop
    if is_player_prop(raw):
        # =========== Player Prop Approach ===========
        if not bet_data["eventDate"]:
            now = datetime.datetime.now()
            bet_data["eventDate"] = now.strftime("%Y-%m-%d")

        bet_data["sport"] = "Basketball"  # fallback
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
            # check for 3 point FG
            if any(k in lower for k in THREE_POINT_KEYWORDS):
                bet_data["market"] = "player_threes"

        # e.g. "Josh Hart (NY) Under 12.5 Points"
        player_line = re.search(
            r"([A-Za-z.'\-]+\s+[A-Za-z.'\-]+\s*\([A-Z]{2,3}\)\s+(Over|Under)\s+\d+(?:\.\d+)?\s*(Points|Rebounds|Assists)?)",
            raw, re.IGNORECASE
        )
        if player_line:
            bet_data["betSelection"] = player_line.group(1).strip()
        else:
            fallback_line = re.search(r"(Over|Under)\s+\d+(?:\.\d+)?\s*(Points|Rebounds|Assists)?", raw, re.IGNORECASE)
            bet_data["betSelection"] = fallback_line.group(0).strip() if fallback_line else raw

    else:
        # =========== Non-Player Prop Approach ===========
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
                    elif "moneyline" in maybe_mkt or "h2h" in maybe_mkt:
                        bet_data["market"] = "h2h"

        selection_chunk = ""
        if len(parts) > 1:
            selection_chunk = parts[1].strip()

        # Always do basic trim
        selection_chunk = trim_non_player_prop(selection_chunk)
        market_lower = bet_data.get("market", "").lower()

        if market_lower in ["h2h", "moneyline"]:
            # e.g. "New York Yankees +125"
            ml_match = re.search(r"([+\-]\d{2,4}(?:\.\d+)?)(\s*(For Game)?)?\s*$", selection_chunk, re.IGNORECASE)
            if ml_match:
                found_odds = ml_match.group(1)
                selection_chunk = selection_chunk[:ml_match.start()].strip()
                bet_data["odds"] = found_odds
            bet_data["market"] = "h2h"  # force 'h2h'
            bet_data["betSelection"] = selection_chunk

        elif market_lower == "spreads":
            # e.g. "TeamName +6.5 -110"
            pm_matches = re.findall(r"[+\-]\d+(?:\.\d+)?", selection_chunk)
            spread_val = None
            odds_val = None
            for match in pm_matches:
                numeric_part = re.sub(r"[+\-\.]", "", match)
                if len(numeric_part) < 3:
                    spread_val = match
                else:
                    odds_val = match
            if spread_val:
                if not spread_val.startswith("+") and not spread_val.startswith("-"):
                    spread_val = "+" + spread_val
                if odds_val:
                    selection_chunk = selection_chunk.replace(odds_val, "").strip()
                    bet_data["odds"] = odds_val
                bet_data["betSelection"] = selection_chunk + " " + spread_val
            else:
                bet_data["betSelection"] = selection_chunk

        elif market_lower == "totals":
            # e.g. "Over 7.5"
            m = re.search(r"(Over|Under)\s+\d+(?:\.\d+)?", selection_chunk, re.IGNORECASE)
            if m:
                bet_data["betSelection"] = m.group(0).strip()
            else:
                bet_data["betSelection"] = selection_chunk
        else:
            # fallback => just set betSelection
            bet_data["betSelection"] = selection_chunk

        # If STILL no market => fallback to h2h
        if not bet_data["market"]:
            bet_data["market"] = "h2h"
            # also remove trailing +/- odds if present
            trailing_ml = re.search(r"([+\-]\d{2,4}(?:\.\d+)?)(\s*(For Game)?)?\s*$", bet_data["betSelection"])
            if trailing_ml:
                found_odds = trailing_ml.group(1)
                bet_data["betSelection"] = bet_data["betSelection"][:trailing_ml.start()].strip()
                bet_data["odds"] = found_odds

        # parse date/time from parts if not found
        if len(parts) > 2:
            dstr = parts[2].strip()
            d_ymd = parse_event_date_ymd(dstr)
            if d_ymd:
                bet_data["eventDate"] = d_ymd

        if len(parts) > 3:
            tstr = parts[3].strip()
            stime = parse_start_time(tstr)
            if stime:
                bet_data["startTime"] = stime

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

    # If still missing date, fallback to today
    if not bet_data["eventDate"]:
        now = datetime.datetime.now()
        bet_data["eventDate"] = now.strftime("%Y-%m-%d")

    # If no recognized sport => fallback from league
    sp = bet_data["sport"]
    if not sp or sp == "Unknown" or sp not in RECOGNIZED_SPORTS:
        league_up = bet_data["league"].upper()
        for key, val in FALLBACK_SPORT_BY_LEAGUE.items():
            if key in league_up and val in RECOGNIZED_SPORTS:
                bet_data["sport"] = val
                break

    return bet_data

# ---------------------------------------------------------
# GOOGLE SHEETS FUNCTIONS FOR MERGING EVENT IDS
# ---------------------------------------------------------
def build_matchup_dict_from_live_odds(spreadsheet_id=None, sheet_name=None):
    """
    Connect to a Google Sheet containing [League, Event ID, Event/Match, ...],
    build a dictionary {canonical_matchup: event_id}.
    """
    sid, tab = _resolve_sheet_id_and_tab(spreadsheet_id, sheet_name)
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sid).worksheet(tab)
        data = sheet.get_all_values()
        print("Sheet data:", data)
    except Exception as e:
        print(f"Google Sheets error: {e}")
        return {}

    if len(data) < 2:
        return {}

    header = data[0]
    try:
        event_id_idx = header.index("Event ID")
        matchup_idx  = header.index("Event/Match")
    except ValueError:
        return {}

    matchup_dict = {}
    for row in data[1:]:
        if len(row) <= max(event_id_idx, matchup_idx):
            continue
        event_id = row[event_id_idx].strip()
        matchup_raw = row[matchup_idx].strip()
        canonical = canonicalize_matchup(matchup_raw)
        matchup_dict[canonical] = event_id

    return matchup_dict

def merge_event_ids_into_csv(csv_file=None, spreadsheet_id=None, sheet_name=None):
    """
    For any row in CSV that has an empty or 'unknown' Event ID,
    attempt to match the Event/Match with the Google Sheet's canonical dictionary
    if the date/time is in the future.
    """
    csv_file = csv_file or csv_path()
    if not os.path.isfile(csv_file):
        print(f"DEBUG: CSV file '{csv_file}' not found. Skipping event ID merge.")
        return

    matchup_dict = build_matchup_dict_from_live_odds(spreadsheet_id, sheet_name)
    if not matchup_dict:
        print("DEBUG: No matchup_dict built from Google Sheets. Possibly empty sheet or error.")
        return

    with open(csv_file, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print(f"DEBUG: CSV '{csv_file}' is empty. Nothing to update.")
        return

    fieldnames = list(rows[0].keys())
    now = datetime.datetime.now()
    updated_count = 0

    print(f"DEBUG: Merging Event IDs from GSheet -> CSV. We have {len(rows)} rows in CSV...")
    print("DEBUG: matchup_dict keys:", list(matchup_dict.keys()))

    for idx, row in enumerate(rows):
        current_event_id = row.get("Event ID", "").strip()
        if current_event_id.lower() in ["", "unknown"]:
            date_str = row.get("Date", "").strip()
            time_str = row.get("Start Time", "").strip()
            dt_str   = f"{date_str} {time_str}"
            try:
                event_datetime = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            except Exception:
                print(f"DEBUG: Row {idx}: Could not parse date/time => '{dt_str}'. Skipping ID merge.")
                continue

            match_str = row.get("Event/Match", "").strip()
            if not match_str:
                continue

            print(f"DEBUG: Row {idx}: Date/Time => {dt_str}, Event/Match => '{match_str}'")
            canonical = canonicalize_matchup(match_str)
            print(f"DEBUG: Row {idx}: canonical='{canonical}'")

            new_event_id = matchup_dict.get(canonical, "Unknown")
            if new_event_id != "Unknown":
                row["Event ID"] = new_event_id
                updated_count += 1
                print(f"DEBUG: Row {idx}: Updated Event ID to '{new_event_id}'")
            else:
                print(f"DEBUG: Row {idx}: No dictionary entry found for '{canonical}'. Remains 'Unknown'.")

    if updated_count > 0:
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"DEBUG: Updated {updated_count} rows in '{csv_file}' with Event IDs.")
    else:
        print("DEBUG: No event IDs were updated.")

# ---------------------------------------------------------
# MAIN LOGIC
# ---------------------------------------------------------
def main():
    try:
        driver = init_driver()
        target_url = "https://www.betonline.ag/my-account/bet-history"
        if not navigate_and_wait(driver, target_url):
            driver.quit()
            return
        print("DEBUG: Waiting for the Bet History page to load...")
        print(f"Static wait before proceeding: {STATIC_WAIT_SECONDS}s …")
        time.sleep(STATIC_WAIT_SECONDS)
        if check_interstitial(driver):
            print("DEBUG: Interstitial detected after initial load. Exiting.")
            driver.quit()
            return

        # Scroll down to load all bet rows, then scroll up
        scroll_bets(driver, scroll_container_selector="#bets", pause_time=2, max_scrolls=10)
        scroll_bets_up(driver, scroll_container_selector="#bets", pause_time=2)
        simulate_random_mouse_movement(driver, moves=3)

        existing_ids = read_existing_bet_ids(csv_path())
        print(f"DEBUG: Found {len(existing_ids)} existing Bet IDs in CSV.")

        bet_rows = driver.find_elements(By.CSS_SELECTOR, "[id^='row-']")
        print(f"DEBUG: Found {len(bet_rows)} bet rows on the page.")

        new_bets_data = []
        for row in bet_rows:
            simulate_random_mouse_movement(driver, moves=2)
            try:
                bet_id_elem = row.find_element(By.CSS_SELECTOR, "div.bet-history__table__body__rows__columns--id")
                short_bet_id = bet_id_elem.text.strip()
                if short_bet_id in existing_ids:
                    print(f"DEBUG: Skipping {short_bet_id} (already in CSV).")
                    continue

                print(f"DEBUG: Expanding bet {short_bet_id}")
                expand_icon = bet_id_elem.find_element(By.TAG_NAME, "i")
                ActionChains(driver).move_to_element(expand_icon).pause(random_delay(1, 0.5)).click().perform()
                time.sleep(random_delay(2, 1))

                row_id = row.get_attribute("id")
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
                time.sleep(random_delay(1, 0.5))

        # Write new bets
        update_csv_betonline(new_bets_data, csv_path())

        # Attempt to grade settled bets
        grade_settled_bets(driver, csv_path())

        # Merge event IDs from Google Sheets
        merge_event_ids_into_csv(
            csv_file=csv_path(),
            spreadsheet_id=None,  # use config.GOOGLE_SHEET_ID via resolver
            sheet_name=getattr(config, "LIVE_ODDS_TAB", "Live Odds")
        )

        input("DEBUG: Press ENTER to close the browser...")
        driver.quit()
        print("DEBUG: Browser closed. Script ended.")

    except Exception as e:
        print("DEBUG: Unexpected error:", e)
        input("DEBUG: Press ENTER to close the browser...")

if __name__ == "__main__":
    main()


