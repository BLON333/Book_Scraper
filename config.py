"""Configuration values for the scraper tools."""

import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root where config.py lives
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)  # fallback to process/working-dir envs

CHROME_PROFILE_DIR = "Default"  # EXACT from chrome://version
REQUIRE_PROFILE = True  # if True, hard-fail when real profile can't be used

# Google Sheet ID used for syncing data
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")

# --- Tabs & header rows (single spreadsheet architecture) ---
BET_SHEET_TAB = os.environ.get("BET_SHEET_TAB", "Sheet1")
BET_HEADER_ROW = 7
BET_FIRST_DATA_ROW = 8
LIVE_ODDS_TAB = os.environ.get("LIVE_ODDS_TAB", "Live Odds")
DETAILED_ODDS_TAB = os.environ.get("DETAILED_ODDS_TAB", "Detailed Odds")

# --- Odds API (env-driven secret) ---
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
LEAGUES = os.environ.get(
    "LEAGUES",
    "baseball_mlb,americanfootball_nfl,americanfootball_ncaaf",
).split(",")
LEAGUES = [x.strip() for x in LEAGUES if x.strip()]
ALLOWED_BOOKS = ["pinnacle", "fanduel", "betonlineag", "draftkings"]
ODDS_REGIONS = "us"
ODDS_FORMAT = "american"

# --- BetOnline scraper gate ---
ENABLE_BETONLINE = False

# --- Debugging ---
DEBUG_LOG = True
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # INFO|DEBUG
# Non-default Chrome profile (prevents 'DevTools ... requires non-default data dir' + UC fallback)
CHROME_USER_DATA_DIR = os.getenv(
    "CHROME_USER_DATA_DIR", r"C:\\Users\\jason\\ChromeProfiles\\PinnacleBot"
)
ATTACH_TO_RUNNING = False
DEBUG_PORT = 9222
