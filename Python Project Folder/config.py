# Configuration values for the scraper tools

# Path to your Chrome user data directory used by undetected_chromedriver
CHROME_USER_DATA_DIR = r"C:\\Users\\jason\\AppData\\Local\\Google\\Chrome\\User Data"
CHROME_PROFILE_DIR   = "Default"   # EXACT from chrome://version
REQUIRE_PROFILE      = True        # if True, hard-fail when real profile can't be used
ATTACH_TO_RUNNING    = False       # if True, attach to a manually-started Chrome on 127.0.0.1:9222

# Google Sheet ID used for syncing data
GOOGLE_SHEET_ID = "10T1umWJko_HOvnEfMn_giLFYFk4O2zONAfdltA2FBv4"

# IDs and tab settings for CLV sync
LIVE_ODDS_SHEET_ID   = "<PUT_LIVE_ODDS_SHEET_ID_HERE>"   # the separate Live Odds spreadsheet
BET_SHEET_TAB        = "Sheet1"                          # Bet Tracking worksheet name
BET_HEADER_ROW       = 7                                 # header row index in Bet sheet
BET_FIRST_DATA_ROW   = 8                                 # first data row
LIVE_ODDS_TAB        = "Live Odds"                       # tab with one-row-per-event snapshot
DETAILED_ODDS_TAB    = "Detailed Odds"                   # tab with per-book odds rows
