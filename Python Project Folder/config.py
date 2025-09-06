"""Configuration values for the scraper tools."""

import os
from dotenv import load_dotenv

# Force load from repo root .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

# Path to your Chrome user data directory used by undetected_chromedriver
CHROME_USER_DATA_DIR = r"C:\\Users\\<you>\\AppData\\Local\\Google\\Chrome\\User Data"
CHROME_PROFILE_DIR = "Default"  # EXACT from chrome://version
REQUIRE_PROFILE = True  # if True, hard-fail when real profile can't be used
ATTACH_TO_RUNNING = False  # if True, attach to a manually-started Chrome on 127.0.0.1:9222

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
LEAGUES = ["baseball_mlb", "americanfootball_nfl"]
ALLOWED_BOOKS = ["pinnacle", "fanduel", "betonlineag", "draftkings"]
ODDS_REGIONS = "us"
ODDS_FORMAT = "american"

# --- BetOnline scraper gate ---
ENABLE_BETONLINE = False

