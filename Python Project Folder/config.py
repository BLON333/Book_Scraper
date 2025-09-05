# Configuration values for the scraper tools

# Path to your Chrome user data directory used by undetected_chromedriver
CHROME_USER_DATA_DIR = r"C:\\Users\\jason\\AppData\\Local\\Google\\Chrome\\User Data"
CHROME_PROFILE_DIR   = "Default"   # EXACT from chrome://version
REQUIRE_PROFILE      = True        # if True, hard-fail when real profile can't be used
ATTACH_TO_RUNNING    = False       # if True, attach to a manually-started Chrome on 127.0.0.1:9222

# Google Sheet ID used for syncing data
try:
    GOOGLE_SHEET_ID
except NameError:
    GOOGLE_SHEET_ID = "PUT_YOUR_BET_TRACKING_SPREADSHEET_ID_HERE"

import os

# --- Tabs & header rows (single spreadsheet architecture) ---
BET_SHEET_TAB       = "Sheet1"     # rename later if desired (e.g., "Bets")
BET_HEADER_ROW      = 7
BET_FIRST_DATA_ROW  = 8
LIVE_ODDS_TAB       = "Live Odds"
DETAILED_ODDS_TAB   = "Detailed Odds"

# --- Odds API (env-driven secret) ---
ODDS_API_KEY  = os.getenv("ODDS_API_KEY", "")   # set at runtime; avoid hardcoding in git
LEAGUES       = ["basketball_nba", "basketball_ncaab", "baseball_mlb"]
ALLOWED_BOOKS = ["pinnacle", "fanduel", "betonlineag", "draftkings"]
ODDS_REGIONS  = "us,eu"
ODDS_FORMAT   = "american"

# --- BetOnline scraper gate ---
ENABLE_BETONLINE = False

