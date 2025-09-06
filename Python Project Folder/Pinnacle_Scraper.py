import os, sys, importlib.util
from datetime import datetime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

_cfg_path = os.path.join(REPO_ROOT, "config.py")
_spec = importlib.util.spec_from_file_location("config", _cfg_path)
config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config)

RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        print(f"[{_ts()}][RUN {RUN_ID}] {msg}")
    except Exception:
        try:
            print((f"[{_ts()}][RUN {RUN_ID}] {str(msg)}").encode("ascii","replace").decode())
        except Exception:
            print(repr(msg))


def _looks_like_sheet_id(value: str) -> bool:
    """Return True if ``value`` resembles a Google Sheet ID."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if len(v) < 25:
        return False
    return all(c.isalnum() or c in "-_" for c in v)


def _resolve_sheet_id_and_tab(spreadsheet_id=None, sheet_name=None):
    """Resolve spreadsheet ID and tab name using args or config defaults."""
    if spreadsheet_id and _looks_like_sheet_id(spreadsheet_id):
        sid = spreadsheet_id.strip()
        tab = sheet_name or getattr(config, "LIVE_ODDS_TAB", "Live Odds")
    else:
        sid = getattr(config, "GOOGLE_SHEET_ID", "").strip()
        tab = sheet_name or spreadsheet_id or getattr(config, "LIVE_ODDS_TAB", "Live Odds")
    log(f"[Sheets] Using spreadsheet_id='{sid}', sheet_name='{tab}'")
    return sid, tab


log(f"REPO_ROOT={REPO_ROOT}")
log(f"sys.path[0..3]={sys.path[:4]}")
log(f"Config module: {getattr(config,'__file__','<unknown>')}")
log(
    "Config: ATTACH_TO_RUNNING=%s, CHROME_USER_DATA_DIR='%s', CHROME_PROFILE_DIR='%s', DEBUG_PORT=%s"
    % (
        getattr(config, 'ATTACH_TO_RUNNING', None),
        getattr(config, 'CHROME_USER_DATA_DIR', None),
        getattr(config, 'CHROME_PROFILE_DIR', 'Default'),
        getattr(config, 'DEBUG_PORT', None),
    )
)

import time
import csv
import random
import re
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from urllib.parse import urlparse
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    SessionNotCreatedException,
    WebDriverException,
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)
from google.oauth2.service_account import Credentials as SA_Credentials
import gspread, json, traceback
from gspread.exceptions import WorksheetNotFound


def repo_path(*parts):
    return os.path.join(REPO_ROOT, *parts)


def csv_path(name="Bet_Tracking.csv"):
    return repo_path(name)


def creds_path():
    return repo_path("credentials.json")

SHEETS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


def _gs_client():
    keyfile = creds_path()
    log(f"[Sheets] Using credentials at: {keyfile}")
    if not os.path.isfile(keyfile):
        log(f"[Sheets][ERR] credentials.json not found at {keyfile}")
        return None
    try:
        with open(keyfile, "r", encoding="utf-8") as fh:
            info = json.load(fh)
        sa_email = info.get("client_email", "<unknown>")
        log(f"[Sheets] Service account: {sa_email}")
        creds = SA_Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        log(f"[Sheets][ERR] {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return None

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
    if getattr(config, "ATTACH_TO_RUNNING", False):
        port = getattr(config, "DEBUG_PORT", 9222)
        profile_dir = getattr(config, "CHROME_PROFILE_DIR", "Default")
        user_data_dir = getattr(config, "CHROME_USER_DATA_DIR", "")
        log(f"[Driver] ATTACH mode -> 127.0.0.1:{port} | profile_dir={profile_dir} | user_data_dir={user_data_dir}")
        opts = Options()
        opts.debugger_address = f"127.0.0.1:{port}"
        opts.add_argument("--start-maximized")
        opts.add_argument("--remote-allow-origins=*")
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            resp = requests.get(url, timeout=2.0)
            if resp.status_code != 200:
                log(f"[FATAL] DevTools not reachable at {url}")
                raise RuntimeError("DevTools not reachable")
        except Exception:
            log(f"[FATAL] DevTools not reachable at {url}")
            raise RuntimeError("DevTools not reachable")
        try:
            driver = webdriver.Chrome(options=opts)
        except Exception as e:
            log(f"[FATAL] Failed to attach to running Chrome: {e}")
            raise
        log("[Driver] ✅ Attached to running Chrome with your profile.")
        return driver

    try:
        opts = Options()
        user_data_dir = getattr(config, "CHROME_USER_DATA_DIR", "").strip()
        profile_dir = getattr(config, "CHROME_PROFILE_DIR", "Default")
        if not user_data_dir:
            msg = "[FATAL] CHROME_USER_DATA_DIR is empty"
            log(msg)
            raise RuntimeError(msg)
        abs_user_data_dir = os.path.abspath(user_data_dir)
        default_dirs = [
            os.path.join(os.path.expanduser("~"), "AppData", "Local", "Google", "Chrome", "User Data"),
            os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Google", "Chrome"),
            os.path.join(os.path.expanduser("~"), ".config", "google-chrome"),
        ]
        for d in default_dirs:
            if abs_user_data_dir == os.path.abspath(d):
                msg = f"[FATAL] CHROME_USER_DATA_DIR points to default Chrome directory: {abs_user_data_dir}"
                log(msg)
                raise RuntimeError(msg)
        if not os.path.isdir(abs_user_data_dir):
            os.makedirs(abs_user_data_dir, exist_ok=True)

        opts.add_argument(f"--user-data-dir={abs_user_data_dir}")
        opts.add_argument(f"--profile-directory={profile_dir}")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        for arg in [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--start-maximized",
        ]:
            opts.add_argument(arg)
        opts.add_argument("--remote-allow-origins=*")
        log(
            f"[Driver] Selenium launch with profile -> user_data_dir='{abs_user_data_dir}', profile_dir='{profile_dir}'"
        )
        driver = webdriver.Chrome(options=opts)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})",
            },
        )
        log("[Driver] OK: Selenium driver launched with your profile.")
        return driver
    except (SessionNotCreatedException, WebDriverException) as e:
        log(f"[FATAL] Selenium launch failed: {e}")
        raise


def navigate_with_retry(driver, url, max_attempts=3, timeout=20):
    """
    Navigate reliably to `url`. Tries:
      1) driver.get(url)
      2) JS: window.location.href = url
      3) (optional) CDP: Page.navigate
    Verifies readyState and host using a subdomain-tolerant check.
    """
    target_host = urlparse(url).netloc.lower()

    def _loaded_on_target():
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            pass
        try:
            cur = driver.current_url or ""
            cur_host = urlparse(cur).netloc.lower()
            # tolerant both ways: foo.bar endswith bar OR bar endswith foo
            return cur_host.endswith(target_host) or target_host.endswith(cur_host)
        except Exception:
            return False

    for attempt in range(1, max_attempts + 1):
        # A) normal get()
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
        except Exception:
            pass
        if _loaded_on_target():
            log(f"[Nav] Arrived at {driver.current_url}")
            return True

        # B) force via JS
        try:
            driver.execute_script("window.location.href = arguments[0];", url)
        except WebDriverException:
            pass
        if _loaded_on_target():
            log(f"[Nav] Arrived at {driver.current_url}")
            return True

        # C) (optional) CDP fallback — keep if you already have CDP elsewhere
        try:
            driver.execute_cdp_cmd("Page.enable", {})
            driver.execute_cdp_cmd("Page.navigate", {"url": url})
        except Exception:
            pass
        if _loaded_on_target():
            log(f"[Nav] Arrived at {driver.current_url}")
            return True

    return False


def dismiss_cookie_banner(driver, timeout=8):
    try:
        wait = WebDriverWait(driver, timeout)
        for sel in [
            (By.XPATH, "//button[contains(., 'Accept')]") ,
            (By.XPATH, "//button[contains(., 'I agree')]") ,
            (By.CSS_SELECTOR, "#onetrust-accept-btn-handler, button#onetrust-accept-btn-handler"),
        ]:
            try:
                btn = wait.until(EC.element_to_be_clickable(sel))
                driver.execute_script("arguments[0].click();", btn)
                return True
            except Exception:
                continue
    except Exception:
        pass
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

def login_handshake(driver, max_wait_secs=120):
    """
    Ensure we're logged in. If not, guide the user to log in manually and poll for success.
    """
    if is_logged_in(driver):
        return True

    log("[LOGIN] Not logged in. Please log in in the opened Chrome window.")

    # Try to expose a login UI without navigating away.
    try:
        for sel in [
            (By.XPATH, "//a[contains(translate(., 'LOGIN', 'login'),'login')]") ,
            (By.CSS_SELECTOR, "a[href*='login']"),
            (By.CSS_SELECTOR, "button[data-test-id='Button']"),
        ]:
            log(f"[Login] Trying selector {sel}")
            elems = driver.find_elements(*sel)
            if elems:
                try:
                    driver.execute_script("arguments[0].click();", elems[0])
                    break
                except Exception:
                    continue
    except Exception:
        pass

    # Poll for login success up to max_wait_secs
    import sys, time
    deadline = time.time() + max_wait_secs
    last_print = -1
    while True:
        if is_logged_in(driver):
            log("[Login] Login detected. Continuing.")
            return True

        remaining = int(deadline - time.time())
        if remaining < 0:
            log("[Login] Timed out waiting for login.")
            return False

        if remaining != last_print:
            last_print = remaining
            sys.stdout.write(f"\r[LOGIN] {remaining:3d}s remaining...")
            sys.stdout.flush()
        time.sleep(1)

def open_account_and_history(driver, timeout=15):
    wait = WebDriverWait(driver, timeout)
    try:
        if "pinnacle" not in (driver.current_url or "").lower():
            driver.get("https://www.pinnacle.ca/en/")
            log("[Nav] Forced homepage load before account menu.")
    except Exception as e:
        log(f"[Nav][WARN] Could not force homepage: {e}")
    try:
        dismiss_cookie_banner(driver)
        log("[Nav] Cookie banner dismissed (if present).")
    except Exception:
        pass

    account_triggers = [
        (By.CSS_SELECTOR, "div[data-gtm-id='super_nav_account']"),
        (By.CSS_SELECTOR, "button[data-test-id='account-menu']"),
        (By.XPATH, "//button[contains(., 'Account') or contains(., 'My Account')]")
    ]
    opened_menu = False
    for by, sel in account_triggers:
        try:
            elem = wait.until(EC.element_to_be_clickable((by, sel)))
            try:
                elem.click()
            except Exception:
                driver.execute_script("arguments[0].click();", elem)
            log(f"[Nav] Clicked account trigger: {sel}")
            log(f"[Nav] Post-account-click URL: {driver.current_url}")
            opened_menu = True
            break
        except Exception as e:
            log(f"[Nav] Account trigger not clickable: {sel} | {e}")
            continue
    if not opened_menu:
        log("[Nav][ERR] Could not open Account menu (no trigger clickable).")
        return
    # Locate account-menu container
    container = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, "div[data-gtm-id='super_nav_account']")
        try:
            container = container.find_element(By.XPATH, "..")
        except Exception:
            pass
    except Exception:
        pass
    if not container:
        try:
            container = driver.find_element(By.TAG_NAME, "body")
        except Exception:
            log("[Nav][ERR] Could not locate account menu container.")
            return

    # Scan for history link within the account menu
    keywords = [
        "betting history",
        "history",
        "transactions",
        "bets",
        "account history",
        "settled",
        "wagers",
    ]
    candidates = []
    try:
        candidates = container.find_elements(By.CSS_SELECTOR, "a, button, label, span, div[role='button']")
    except Exception:
        pass
    clicked_history = False
    for item in candidates:
        try:
            text = item.text or ""
            norm = (
                text.replace("\u00a0", " ")
                .replace("\u200b", "")
                .strip()
                .lower()
            )
            if any(k in norm for k in keywords):
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                except Exception:
                    pass
                try:
                    item.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", item)
                log(f"[Nav] Matched history item text='{norm}' tag={item.tag_name}")
                log(f"[Nav] Post-history-click URL: {driver.current_url}")
                clicked_history = True
                break
        except StaleElementReferenceException:
            continue
    if not clicked_history:
        try:
            menu_text = container.text or ""
            menu_text = menu_text.replace("\u00a0", " ").replace("\u200b", "")
            log(f"[Nav][DBG] Account menu text (first 400 chars): {menu_text[:400]}")
        except Exception:
            log("[Nav][DBG] Account menu text unavailable.")
        return

    try:
        wait.until(
            lambda d: (
                "account" in (d.current_url or "").lower()
                or "history" in (d.current_url or "").lower()
                or d.find_elements(By.CSS_SELECTOR, "div[data-test-id='betCard']")
                or d.find_elements(By.XPATH, "//*[contains(., 'Bet ID') or contains(., 'Wager')]")
            )
        )
        log("[Nav] Betting history detected.")
    except TimeoutException:
        log("[Nav][ERR] Betting history page did not load within timeout.")

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
def read_existing_bet_ids(csv_file_path=None):
    """Return a set of Bet ID#s that already exist in the CSV, to avoid duplicates."""
    csv_file_path = csv_file_path or csv_path("Bet_Tracking.csv")
    existing_ids = set()
    if os.path.isfile(csv_file_path):
        with open(csv_file_path, newline="") as file:
            for row in csv.DictReader(file):
                bet_id = row.get("Bet ID#", "").strip()
                if bet_id:
                    existing_ids.add(bet_id)
    return existing_ids

def expand_unlogged_bets(driver, existing_ids, max_passes=3):
    wait = WebDriverWait(driver, 10)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-test-id='betCard']")))
    except TimeoutException:
        log("[Expand] No bet cards detected; nothing to expand.")
        return
    seen_ids, passes, expanded = set(), 0, 0
    while passes < max_passes:
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, "div[data-test-id='betCard']")
        except Exception:
            cards = []
        log(f"[Expand] Pass {passes+1}: found {len(cards)} cards.")
        if not cards:
            break
        for idx in range(len(cards)):
            try:
                card_list = driver.find_elements(By.CSS_SELECTOR, "div[data-test-id='betCard']")
                if idx >= len(card_list):
                    continue
                card = card_list[idx]
                bet_id = None
                try:
                    bid_elem = card.find_element(By.CSS_SELECTOR, ".betId-PSO7kpwKIQ > div.container-eyCI_sLCJ2")
                    bet_id = (bid_elem.text or "").strip().replace("#", "").replace(" ", "")
                except Exception:
                    pass
                if bet_id and (bet_id in existing_ids or bet_id in seen_ids):
                    continue
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                except StaleElementReferenceException:
                    continue
                try:
                    driver.execute_script("arguments[0].click();", card)
                except Exception:
                    try:
                        card.click()
                    except Exception:
                        pass
                time.sleep(random.uniform(1.3, 2.6))
                if bet_id:
                    seen_ids.add(bet_id)
                expanded += 1
            except StaleElementReferenceException:
                continue
            except Exception as e:
                log(f"[Expand][WARN] Error expanding card idx={idx}: {e}")
                continue
        passes += 1
    log(f"[Expand] Expanded ~{expanded} cards across {passes} pass(es).")

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

def update_csv(extracted_bets, csv_file_path=None):
    """Append new bets to the CSV, avoiding duplicates by Bet ID#."""
    csv_file_path = csv_file_path or csv_path("Bet_Tracking.csv")
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

def grade_settled_bets(driver, csv_file_path=None):
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

    csv_file_path = csv_file_path or csv_path("Bet_Tracking.csv")
    if not os.path.isfile(csv_file_path):
        return

    with open(csv_file_path, newline="") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        log(f"[Grade] '{csv_file_path}' has 0 data rows; skipping grade_settled_bets.")
        return

    updated_count = 0
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
                updated_count += 1

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
    fieldnames = rows[0].keys() if rows else []
    with open(csv_file_path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log(f"[Grade] Updated statuses for {updated_count} bets.")

# -----------------------------------------------------------------------------
# GOOGLE SHEETS: BUILD MATCHUP DICTIONARY & MERGE EVENT IDS
# -----------------------------------------------------------------------------
def build_matchup_dict_from_live_odds(spreadsheet_id=None, sheet_name=None):
    sid, tab = _resolve_sheet_id_and_tab(spreadsheet_id, sheet_name)
    client = _gs_client()
    if not client or not sid:
        return {}
    try:
        log(f"[Sheets] Opening spreadsheet '{sid}'")
        sh = client.open_by_key(sid)
        try:
            sheet = sh.worksheet(tab)
        except WorksheetNotFound:
            log(f"[Sheets][ERR] Worksheet '{tab}' not found")
            return {}
        data = sheet.get_all_values()
    except Exception as e:
        log(f"[Sheets][ERR] {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return {}

    if len(data) < 2:
        log("[Sheets][WARN] No data found in sheet")
        return {}

    header = data[0]
    try:
        event_id_idx = header.index("Event ID")
        matchup_idx = header.index("Event/Match")
    except ValueError:
        log("[Sheets][ERR] Required columns 'Event ID' and 'Event/Match' not found")
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

def merge_event_ids_into_csv(csv_file=None,
                             spreadsheet_id="Live Odds",
                             sheet_name="Live Odds"):
    """
    Match unknown (pending) Event IDs in CSV with those from the Google Sheet
    using the canonicalized matchup strings.
    """
    csv_file = csv_file or csv_path("Bet_Tracking.csv")
    if not os.path.isfile(csv_file):
        return

    matchup_dict = build_matchup_dict_from_live_odds(spreadsheet_id, sheet_name)
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

    log(f"[Merge] Updated {updated_count} rows in '{csv_file}' with Event IDs (future events only).")

# -----------------------------------------------------------------------------
# MAIN FUNCTION
# -----------------------------------------------------------------------------
def main():
    log("==== Pinnacle_Scraper starting ====")
    try:
        import config
        log(f"Config module: {getattr(config,'__file__','<unknown>')}")
        log(
            f"Config values: ATTACH_TO_RUNNING={getattr(config,'ATTACH_TO_RUNNING',None)}, "
            f"CHROME_USER_DATA_DIR='{getattr(config,'CHROME_USER_DATA_DIR',None)}', "
            f"CHROME_PROFILE_DIR='{getattr(config,'CHROME_PROFILE_DIR','Default')}', "
            f"DEBUG_PORT={getattr(config,'DEBUG_PORT',None)}"
        )
    except Exception as e:
        log(f"[WARN] Could not import/print config details: {e}")
    driver = init_driver()
    driver.get("about:blank")
    navigate_with_retry(
        driver,
        "https://www.pinnacle.ca/en/",
        max_attempts=3,
        timeout=20,
    )
    if not driver.current_url.startswith("https://www.pinnacle"):
        driver.execute_script(
            "window.location.href = arguments[0];",
            "https://www.pinnacle.ca/en/",
        )
        log(f"[Nav] After script redirect: {driver.current_url}")
    if not driver.current_url.startswith("https://www.pinnacle"):
        log("[FATAL] Could not reach Pinnacle after retries. Exiting.")
        driver.quit()
        return
    dismiss_cookie_banner(driver)
    log("[Nav] dismiss_cookie_banner() called")
    time.sleep(random_delay(5, 2))
    # Ensure login before navigating to account/history
    log("[Login] login_handshake(): started")
    if not login_handshake(driver, max_wait_secs=120):
        driver.quit()
        return

    open_account_and_history(driver)
    click_load_more(driver)

    existing_ids = read_existing_bet_ids(csv_path("Bet_Tracking.csv"))
    expand_unlogged_bets(driver, existing_ids)

    new_bets = extract_bet_data(driver)
    update_csv(new_bets, csv_path("Bet_Tracking.csv"))

    grade_settled_bets(driver, csv_path("Bet_Tracking.csv"))
    merge_event_ids_into_csv(
        csv_file=csv_path("Bet_Tracking.csv"),
        spreadsheet_id=None,  # use config.GOOGLE_SHEET_ID via resolver
        sheet_name=getattr(config, "LIVE_ODDS_TAB", "Live Odds")
    )

    driver.quit()

if __name__ == "__main__":
    main()
