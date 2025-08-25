import os
import time
import csv
import random, tempfile
import re
import undetected_chromedriver as uc
import config
from datetime import datetime, timedelta
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import SessionNotCreatedException, WebDriverException, TimeoutException
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# -----------------------------------------------------------------------------
# OFFICIAL TEAM MAPPING & CANONICALIZATION
# -----------------------------------------------------------------------------
OFFICIAL_TEAM_MAPPING = {
    "byu cougars": "byu",
    "iowa state cyclones": "iowa state",
    # Add or modify mappings as needed
}

def canonicalize_matchup(match_str, team_mapping=OFFICIAL_TEAM_MAPPING):
    """
    Normalize a matchup string by splitting on " vs " or "@", then mapping teams.
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

# -----------------------------------------------------------------------------
# UTILITY FUNCTIONS
# -----------------------------------------------------------------------------
def random_delay(base=1.0, variation=0.5):
    return random.uniform(base - variation, base + variation)

def init_driver():
    # Option 1: attach to a running Chrome with my profile (manual start)
    # Manual start example (outside Python):
    # "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^
    #   --remote-debugging-port=9222 ^
    #   --user-data-dir="C:\\Users\\jason\\AppData\\Local\\Google\\Chrome\\User Data" ^
    #   --profile-directory="Default"
    if getattr(config, "ATTACH_TO_RUNNING", False):
        print("Attaching to an already running Chrome (127.0.0.1:9222)...")
        opts = uc.ChromeOptions()
        opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
        driver = uc.Chrome(options=opts)
        print("✅ Attached to running Chrome with profile.")
        return driver

    print("Opening Chrome with your profile...")
    options = uc.ChromeOptions()

    # Real profile (from config.py)
    user_data_dir = getattr(config, "CHROME_USER_DATA_DIR", None)
    profile_dir   = getattr(config, "CHROME_PROFILE_DIR", "Default")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")
    if profile_dir:
        options.add_argument(f"--profile-directory={profile_dir}")

    # Stability flags
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--start-maximized")
    options.add_argument(f"--remote-debugging-port={random.randint(40000, 49000)}")

    try:
        driver = uc.Chrome(options=options)
        print(f"✅ Attached to profile: {profile_dir}")
        return driver
    except (SessionNotCreatedException, WebDriverException) as e:
        print(f"❌ Couldn’t attach to Chrome profile ({profile_dir}): {e}")

        # Enforce real profile if required
        if getattr(config, "REQUIRE_PROFILE", True):
            raise

        # Optional fallback to temp profile
        print("[WARN] Falling back to a temporary profile (login not persisted).")
        temp_dir = tempfile.mkdtemp(prefix="pinn_uc_")
        fresh = uc.ChromeOptions()
        fresh.add_argument(f"--user-data-dir={temp_dir}")
        fresh.add_argument("--no-first-run")
        fresh.add_argument("--no-default-browser-check")
        fresh.add_argument("--disable-extensions")
        fresh.add_argument("--disable-background-networking")
        fresh.add_argument("--start-maximized")
        fresh.add_argument(f"--remote-debugging-port={random.randint(40000, 49000)}")
        driver = uc.Chrome(options=fresh)
        print("Opened Chrome with a temporary profile.")
        return driver


def navigate_with_retry(driver, url, max_attempts=3, timeout=20):
    target_host = urlparse(url).netloc

    def loaded():
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            return urlparse(driver.current_url).netloc == target_host
        except Exception:
            return False

    for _ in range(max_attempts):
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
        except Exception:
            pass
        if loaded():
            return True
        try:
            driver.execute_script(f"window.location.href = '{url}'")
        except Exception:
            pass
        if loaded():
            return True
        try:
            driver.execute_cdp_cmd("Page.enable", {})
            driver.execute_cdp_cmd("Page.navigate", {"url": url})
        except Exception:
            pass
        if loaded():
            return True
    return False

def is_logged_in(driver):
    """
    Return True if the user appears to be logged in; otherwise False.
    """
    try:
        if driver.find_elements(By.CSS_SELECTOR, "button[data-test-id='account-menu']"):
            return True
        if driver.find_elements(By.CSS_SELECTOR, "div[data-test-id='balance-container']"):
            return True
        if not driver.find_elements(By.CSS_SELECTOR, "button[data-test-id='Button']"):
            return True
    except Exception:
        return False
    return False

def perform_login(driver):
    """
    Attempt to perform a login sequence if the user is not already logged in.
    """
    print("Performing login steps...")
    try:
        login_button = driver.find_element(By.CSS_SELECTOR, "button[data-test-id='Button']")
        ActionChains(driver).move_to_element_with_offset(
            login_button, random.uniform(-3, 3), random.uniform(-3, 3)
        ).pause(random_delay(1, 0.5)).click().perform()
        time.sleep(random_delay(5, 2))
    except Exception as e:
        print(f"Error clicking login button: {e}")

    time.sleep(random_delay(3, 1))

    # Check "Remember Me" checkbox
    checkbox_script = """
    let checkbox = document.querySelector("i.icon-check-box-tick-icon");
    if (checkbox) {
        let rect = checkbox.getBoundingClientRect();
        let event = new MouseEvent("mousemove", {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: rect.left + Math.random() * 6 - 3,
            clientY: rect.top + Math.random() * 6 - 3
        });
        checkbox.dispatchEvent(event);
        checkbox.click();
    }
    """
    driver.execute_script(checkbox_script)
    time.sleep(random_delay(3, 1))

    # Attempt to click the login button in the pop-up
    login_button_script = """
    let loginButtons = document.querySelectorAll("button[data-test-id='Button']");
    if (loginButtons.length > 0) {
        let popupLoginButton = loginButtons[loginButtons.length - 1];
        if (popupLoginButton) {
            let rect = popupLoginButton.getBoundingClientRect();
            let event = new MouseEvent("mousemove", {
                bubbles: true,
                cancelable: true,
                view: window,
                clientX: rect.left + (rect.width / 2),
                clientY: rect.top + (rect.height / 2)
            });
            popupLoginButton.dispatchEvent(event);
            popupLoginButton.focus();
            setTimeout(() => popupLoginButton.click(), Math.random() * (1500 - 800) + 800);
            return "clicked";
        }
    }
    return "not_found";
    """
    result = driver.execute_script(login_button_script)
    if result != "clicked":
        print("Pop-up login button not found.")
    time.sleep(random_delay(7, 3))

def open_account_and_history(driver):
    """
    Navigate to the account menu and open the betting history page.
    """
    wait = WebDriverWait(driver, 10)
    try:
        account_menu = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "div[data-gtm-id='super_nav_account']")))
        try:
            account_menu.click()
        except Exception:
            driver.execute_script("arguments[0].click();", account_menu)
    except Exception as e:
        print(f"Error opening Account Menu: {e}")

    try:
        my_account = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "My Account")))
        my_account.click()
        time.sleep(2)
    except Exception as e:
        print(f"Error clicking 'My Account': {e}")

    try:
        betting_history = wait.until(EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), 'Betting history')]")))
        betting_history.click()
        time.sleep(2)
    except Exception as e:
        print(f"Error opening Betting History: {e}")

def click_load_more(driver, max_attempts=3):
    """
    Click the 'Load More' button up to max_attempts times.
    """
    for attempt in range(max_attempts):
        time.sleep(3)
        buttons = driver.find_elements(By.XPATH, "//span[contains(text(), 'Load More')]")
        if not buttons:
            time.sleep(5)
            buttons = driver.find_elements(By.XPATH, "//span[contains(text(), 'Load More')]")
            if not buttons:
                break
        for button in buttons:
            try:
                button.click()
            except Exception:
                driver.execute_script("arguments[0].click();", button)
            time.sleep(5)

# -----------------------------------------------------------------------------
# CSV & BET-TRACKING FUNCTIONS
# -----------------------------------------------------------------------------
def read_existing_bet_ids(csv_file_path="Bet_Tracking.csv"):
    """
    Return a set of Bet ID#s that already exist in the CSV, to avoid duplicates.
    """
    existing_ids = set()
    if os.path.isfile(csv_file_path):
        with open(csv_file_path, newline="") as file:
            for row in csv.DictReader(file):
                bet_id = row.get("Bet ID#", "").strip()
                if bet_id:
                    existing_ids.add(bet_id)
    return existing_ids

def expand_unlogged_bets(driver, existing_ids):
    """
    Expand any bet cards that are not already logged in the CSV, to reveal details.
    """
    bet_cards = driver.find_elements(By.CSS_SELECTOR, "div[data-test-id='betCard']")
    for bet in bet_cards:
        try:
            bet_id_elem = bet.find_element(By.CSS_SELECTOR, ".betId-PSO7kpwKIQ > div.container-eyCI_sLCJ2")
            bet_id = bet_id_elem.text.strip().replace("#", "").replace(" ", "")
        except Exception:
            bet_id = None

        if bet_id and bet_id in existing_ids:
            continue

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", bet)
        driver.execute_script("arguments[0].click();", bet)
        time.sleep(random.uniform(2, 4))

# -----------------------------------------------------------------------------
# JAVASCRIPT EXTRACTION CODE
# -----------------------------------------------------------------------------
JS_EXTRACT_CODE = r"""
try {
  return (function() {
    function isTeamMatchup(str) {
      return /\s+vs\s+/i.test(str);
    }
    function detectPlayerProp(selection) {
      let normalized = selection.replace(/[+\/(),]/g, " ")
                                .replace(/\s+/g, " ")
                                .trim()
                                .toLowerCase();
      // Points + Rebounds + Assists combos
      if (normalized.includes("points rebs assists") ||
          normalized.includes("points rebounds assists") ||
          normalized.includes("pts rebs asts") ||
          normalized.includes("p r a") ||
          normalized.includes("pra")) {
        return "player_points_rebounds_assists";
      }
      // Other combos
      if (normalized.includes("points rebs") || normalized.includes("points rebounds")) {
        return "player_points_rebounds";
      }
      if (normalized.includes("points assists")) {
        return "player_points_assists";
      }
      if (normalized.includes("rebounds assists") || normalized.includes("rebs assists")) {
        return "player_rebounds_assists";
      }
      // Single categories
      if (normalized.includes("points")) {
        return "player_points";
      }
      if (normalized.includes("rebounds") || normalized.includes("rebs")) {
        return "player_rebounds";
      }
      if (normalized.includes("assists") || normalized.includes("asts")) {
        return "player_assists";
      }
      // 3-point FG
      if (normalized.includes("3 point") ||
          normalized.includes("3-point") ||
          normalized.includes("three point") ||
          normalized.includes("3pt") ||
          normalized.includes("3pt fg") ||
          normalized.includes("3 point field goals")) {
        return "player_threes";
      }
      return null;
    }
    function parseShortLeague(fullLeagueText) {
      let lower = fullLeagueText.toLowerCase();
      if (lower.includes("nba")) return "NBA";
      if (lower.includes("ncaa")) return "NCAA";
      if (lower.includes("mlb")) return "MLB";
      if (lower.includes("nhl")) return "NHL";
      if (lower.includes("nfl")) return "NFL";
      return "Unknown";
    }
    const betCards = document.querySelectorAll(".card-fHGTUKa_IT.row-rH355iHD4M");
    const extractedBets = [];

    betCards.forEach((betCard) => {
      // Bet ID
      let betIdElem = betCard.querySelector(".betId-PSO7kpwKIQ > div.container-eyCI_sLCJ2");
      let rawBetId = betIdElem ? betIdElem.innerText.trim() : "Unknown";
      let betId = rawBetId.replace(/[#\s]/g, "") || "Unknown";

      // Event date/time
      const eventDateElem = betCard.querySelector(".container-_la1MytHEJ span:nth-child(2)");
      let eventDateRaw = eventDateElem ? eventDateElem.innerText.trim() : "Unknown Date";
      let eventDate = "Unknown Date";
      let startTime = "Unknown Time";
      const dateParts = eventDateRaw.match(/^(\w{3}), ([A-Za-z]+) (\d{1,2}), (\d{4}), (\d{2}):(\d{2})$/);
      if (dateParts) {
        let monthName = dateParts[2];
        let day = dateParts[3].padStart(2,"0");
        let year = dateParts[4];
        let hour = dateParts[5];
        let minute = dateParts[6];

        const monthMap = {
          "jan": "01", "january": "01",
          "feb": "02", "february": "02",
          "mar": "03", "march": "03",
          "apr": "04", "april": "04",
          "may": "05",
          "jun": "06", "june": "06",
          "jul": "07", "july": "07",
          "aug": "08", "august": "08",
          "sep": "09", "sept": "09", "september": "09",
          "oct": "10", "october": "10",
          "nov": "11", "november": "11",
          "dec": "12", "december": "12"
        };
        let mm = monthMap[monthName.toLowerCase()] || "01";

        // FIXED: Use normal string concatenation instead of ${}
        eventDate = year + "-" + mm + "-" + day;
        startTime = hour + ":" + minute;
      }

      // Default bet selection
      const betSelectionElem = betCard.querySelector(".descriptionContainer-CuQLYa1d5n > div");
      const defaultBetSelection = betSelectionElem ? betSelectionElem.innerText.trim() : "Unknown Bet";

      // Odds, stake, payout
      const oddsElem = betCard.querySelector(".dataPoint-KuKWdXUdiS.odds-MLGLaEHCiw > div");
      const rawOdds = oddsElem ? oddsElem.innerText.trim().replace("@", "").replace(" ", "") : "Unknown Odds";
      const stakeElem = betCard.querySelector(".value-tmg2dXHs9V > span");
      const stakeAmount = stakeElem ? stakeElem.innerText.trim().replace("$", "").replace(",", "") : "0.00";
      const payoutElem = betCard.querySelectorAll(".value-tmg2dXHs9V > span")[1];
      const payoutAmount = payoutElem ? payoutElem.innerText.trim().replace("$", "").replace(",", "") : "0.00";

      // Market / league
      const marketLeagueElem = betCard.querySelector(".descLabel-fP9i5Ni0Ml.marketLeague-rnbqoNqLUs");
      let marketLeagueText = marketLeagueElem ? marketLeagueElem.innerText.trim() : "Unknown Market - Unknown League";
      let shortLeague = parseShortLeague(marketLeagueText);

      const lowerLeague = marketLeagueText.toLowerCase();
      const lowerSelection = defaultBetSelection.toLowerCase();

      // Period suffix
      let suffix = "";
      if (lowerLeague.includes("1st q") || lowerSelection.includes("1st q")) {
        suffix = "_q1";
      } else if (lowerLeague.includes("2nd q") || lowerSelection.includes("2nd q")) {
        suffix = "_q2";
      } else if (lowerLeague.includes("1st h") || lowerSelection.includes("1st h")) {
        suffix = "_h1";
      } else if (lowerLeague.includes("2nd h") || lowerSelection.includes("2nd h")) {
        suffix = "_h2";
      } else if (lowerLeague.includes("3rd q") || lowerSelection.includes("3rd q")) {
        suffix = "_q3";
      } else if (lowerLeague.includes("4th q") || lowerSelection.includes("4th q")) {
        suffix = "_q4";
      }

      // Player prop?
      const possiblePlayerProp = detectPlayerProp(defaultBetSelection);

      // Event match
      let eventMatch = "Unknown Match";
      if (possiblePlayerProp) {
        let playerMatchElem = betCard.querySelector(".gamePropMatchName-t8XBnfgvDJ");
        let candidateText = playerMatchElem ? playerMatchElem.innerText.trim() : "";
        if (!candidateText) {
          let normalMatchElem = betCard.querySelector(".matchName-j2KqtMUVKC");
          candidateText = normalMatchElem ? normalMatchElem.innerText.trim() : "";
        }
        if (candidateText && isTeamMatchup(candidateText)) {
          eventMatch = candidateText;
        } else {
          eventMatch = "Unknown PlayerProp Match";
        }
      } else {
        let normalMatchElem = betCard.querySelector(".matchName-j2KqtMUVKC");
        eventMatch = normalMatchElem ? normalMatchElem.innerText.trim() : "Unknown Match";
      }

      // Market
      let finalMarket = "Unknown";
      if (possiblePlayerProp) {
        finalMarket = possiblePlayerProp;
      } else {
        if (lowerLeague.includes("handicap")) {
          finalMarket = "spreads" + suffix;
        } else if (lowerLeague.includes("totals")) {
          finalMarket = "totals" + suffix;
        } else if (lowerLeague.includes("team total")) {
          finalMarket = "team_totals" + suffix;
        } else if (lowerSelection.includes("over") || lowerSelection.includes("under")) {
          finalMarket = "totals" + suffix;
        } else if (/[+\-]\d+/.test(lowerSelection)) {
          finalMarket = "spreads" + suffix;
        } else if (rawOdds.startsWith("+") || rawOdds.startsWith("-")) {
          finalMarket = "h2h" + suffix;
        } else {
          finalMarket = "player_points";
        }
      }

      // Derivative
      let derivative = lowerLeague.includes("game") ? "No" : "Yes";

      // Sport
      let finalSport = ((shortLeague === "NBA") || (shortLeague === "NCAA"))
                       ? "Basketball"
                       : "Unknown Sport";

      // Player prop bet selection refinement
      let finalBetSelection = defaultBetSelection;
      if (possiblePlayerProp) {
        let playerNameElem = betCard.querySelector("div.container-q3o3TofZKK > div");
        let rawPlayerName = playerNameElem ? playerNameElem.innerText.trim() : "";
        let playerName = rawPlayerName.replace(/\(.*?\)/, "").trim();

        let oddsDescriptionElem = betCard.querySelector("div.participantOdds-KJqsjY1e9j > div.descriptionContainer-CuQLYa1d5n > div");
        let rawOddsDesc = oddsDescriptionElem ? oddsDescriptionElem.innerText.trim() : "";
        let cleanedOddsDesc = rawOddsDesc.replace(/\s*@\s*[-+]\d+.*$/, "").trim();

        if (playerName && cleanedOddsDesc) {
          finalBetSelection = playerName + " " + cleanedOddsDesc;
        }
      }

      // Push final data
      extractedBets.push({
        betId: betId,
        betSelection: finalBetSelection,
        closingLine: "",
        clvPercent: "",
        derivative: derivative,
        eventDate: eventDate,
        eventMatch: eventMatch,
        leagueFull: marketLeagueText,
        league: shortLeague,
        market: finalMarket,
        notes: "",
        odds: rawOdds,
        payoutAmount: payoutAmount,
        profitLoss: "",
        sport: finalSport,
        stakeAmount: stakeAmount,
        startTime: startTime
      });
    });
    return extractedBets;
  })();
} catch(e) {
  console.error("JS Snippet Error:", e);
  return null;
}
"""

def extract_bet_data(driver):
    """
    Execute the JavaScript snippet in the browser to collect bet details.
    """
    bets = driver.execute_script(JS_EXTRACT_CODE)
    if not bets or not isinstance(bets, list):
        return []
    return bets

def update_csv(extracted_bets, csv_file_path="Bet_Tracking.csv"):
    """
    Append new bets to the CSV, avoiding duplicates by Bet ID#.
    """
    file_exists = os.path.isfile(csv_file_path)
    existing_ids = set()
    if file_exists:
        with open(csv_file_path, newline="") as file:
            for row in csv.DictReader(file):
                bet_id = row.get("Bet ID#", "").strip()
                if bet_id:
                    existing_ids.add(bet_id)

    fieldnames = [
        "Date", "Start Time", "Event ID", "Sport", "League", "Market", "Derivative",
        "Event/Match", "Bet", "Odds", "Stake", "Bookmaker", "Payout",
        "Closing Line", "CLV%", "Profit/Loss", "Notes/Comments", "Bet ID#", "Result"
    ]

    with open(csv_file_path, "a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for bet in extracted_bets:
            bet_id = bet.get("betId", "Unknown")
            if bet_id not in existing_ids:
                writer.writerow({
                    "Date": bet.get("eventDate", "").strip(),
                    "Start Time": bet.get("startTime", "Unknown Time"),
                    "Event ID": "",
                    "Sport": bet.get("sport", "Unknown Sport"),
                    "League": bet.get("league", "Unknown League"),
                    "Market": bet.get("market", "Unknown"),
                    "Derivative": bet.get("derivative", "No"),
                    "Event/Match": bet.get("eventMatch", "Unknown Match"),
                    "Bet": bet.get("betSelection", "Unknown Bet"),
                    "Odds": bet.get("odds", "Unknown Odds"),
                    "Stake": bet.get("stakeAmount", "0.00"),
                    "Bookmaker": "Pinnacle",
                    "Payout": bet.get("payoutAmount", "0.00"),
                    "Closing Line": bet.get("closingLine", ""),
                    "CLV%": bet.get("clvPercent", ""),
                    "Profit/Loss": bet.get("profitLoss", ""),
                    "Notes/Comments": bet.get("notes", ""),
                    "Bet ID#": bet_id,
                    "Result": "Pending"
                })

def grade_settled_bets(driver, csv_file_path="Bet_Tracking.csv"):
    """
    Check if any bets in the CSV have settled (Win/Loss/Refund) and update them.
    Also recalc CLV% and Profit/Loss where possible.
    """
    def american_to_probability(odds_str):
        try:
            val = float(odds_str.strip())
            return 100.0 / (val + 100.0) if val > 0 else -val / (-val + 100.0)
        except:
            return None

    if not os.path.isfile(csv_file_path):
        return

    with open(csv_file_path, newline="") as file:
        rows = list(csv.DictReader(file))

    for row in rows:
        if row["Result"].strip() == "Pending":
            bet_id = row["Bet ID#"].strip()
            js_snippet = """
            return (function(betId){
              let elems = document.querySelectorAll(".betId-PSO7kpwKIQ");
              for (let elem of elems) {
                  if(elem.innerText.includes(betId)){
                      let betCard = elem.closest(".card-fHGTUKa_IT");
                      if(betCard){
                          let text = betCard.innerText;
                          if(text.includes("WIN")) return "Win";
                          if(text.includes("LOSS")) return "Loss";
                          if(text.includes("REFUND")) return "Refund";
                      }
                  }
              }
              return "Pending";
            })(arguments[0]);
            """
            new_status = driver.execute_script(js_snippet, bet_id)
            if new_status != "Pending":
                row["Result"] = new_status

    for row in rows:
        try:
            stake = float(row["Stake"].strip())
        except:
            stake = 0.0
        closing_line = row["Closing Line"].strip()
        if closing_line:
            original_prob = american_to_probability(row["Odds"])
            closing_prob = american_to_probability(closing_line)
            if original_prob and closing_prob and original_prob > 0:
                row["CLV%"] = f"{((closing_prob / original_prob) - 1)*100:.2f}"
            else:
                row["CLV%"] = ""
        else:
            row["CLV%"] = ""

        result = row["Result"].strip().lower()
        if result == "pending" or stake <= 0:
            row["Profit/Loss"] = ""
        elif result == "refund":
            row["Profit/Loss"] = "0"
        else:
            # "win" or "loss"
            orig_prob = american_to_probability(row["Odds"])
            if orig_prob and orig_prob > 0:
                decimal_odds = 1.0 / orig_prob
            else:
                decimal_odds = 0.0
            if decimal_odds <= 1.0:
                row["Profit/Loss"] = ""
            else:
                row["Profit/Loss"] = (
                    f"{stake * (decimal_odds - 1):.2f}" if result == "win" else f"-{stake:.2f}"
                )

    # Rewrite CSV
    fieldnames = rows[0].keys()
    with open(csv_file_path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

# -----------------------------------------------------------------------------
# GOOGLE SHEETS: BUILD MATCHUP DICTIONARY & MERGE EVENT IDS
# -----------------------------------------------------------------------------
def build_matchup_dict_from_live_odds(spreadsheet_name="Live Odds", sheet_name="Live Odds"):
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).worksheet(sheet_name)
    except Exception as e:
        print(f"Google Sheets error: {e}")
        return {}

    data = sheet.get_all_values()
    if len(data) < 2:
        return {}

    header = data[0]
    try:
        event_id_idx = header.index("Event ID")
        matchup_idx = header.index("Event/Match")
    except ValueError:
        return {}

    matchup_dict = {}
    for row in data[1:]:
        if len(row) <= max(event_id_idx, matchup_idx):
            continue
        event_id = row[event_id_idx].strip()
        matchup_raw = row[matchup_idx].strip()
        # Canonicalize the matchup so the sheet & CSV align
        canonical = canonicalize_matchup(matchup_raw)
        matchup_dict[canonical] = event_id

    return matchup_dict

def merge_event_ids_into_csv(csv_file="Bet_Tracking.csv",
                             spreadsheet_name="Live Odds",
                             sheet_name="Live Odds"):
    """
    Match unknown (pending) Event IDs in CSV with those from the Google Sheet
    using the canonicalized matchup strings.
    """
    if not os.path.isfile(csv_file):
        return

    matchup_dict = build_matchup_dict_from_live_odds(spreadsheet_name, sheet_name)
    if not matchup_dict:
        return

    with open(csv_file, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return

    fieldnames = list(rows[0].keys())
    now = datetime.now()
    updated_count = 0

    for row in rows:
        current_event_id = row.get("Event ID", "").strip()
        if current_event_id.lower() in ["", "unknown"]:
            dt_str = f"{row.get('Date', '').strip()} {row.get('Start Time', '').strip()}"
            try:
                event_datetime = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                if event_datetime > now:
                    match_str = row.get("Event/Match", "").strip()
                    canonical = canonicalize_matchup(match_str)
                    new_event_id = matchup_dict.get(canonical, "Unknown")
                    if new_event_id != current_event_id:
                        row["Event ID"] = new_event_id
                        updated_count += 1
            except Exception:
                pass

    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {updated_count} rows in '{csv_file}' with Event IDs (only future events).")

# -----------------------------------------------------------------------------
# MAIN FUNCTION
# -----------------------------------------------------------------------------
def main():
    driver = init_driver()
    navigate_with_retry(driver, "https://www.pinnacle.ca/en/")
    time.sleep(random_delay(5, 2))

    if not is_logged_in(driver):
        perform_login(driver)

    open_account_and_history(driver)
    click_load_more(driver)

    existing_ids = read_existing_bet_ids("Bet_Tracking.csv")
    expand_unlogged_bets(driver, existing_ids)

    new_bets = extract_bet_data(driver)
    update_csv(new_bets, "Bet_Tracking.csv")

    grade_settled_bets(driver, "Bet_Tracking.csv")
    merge_event_ids_into_csv(
        csv_file="Bet_Tracking.csv",
        spreadsheet_name="Live Odds",
        sheet_name="Live Odds"
    )

    driver.quit()

if __name__ == "__main__":
    main()
