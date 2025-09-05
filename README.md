# MLB Odds Tracker 📊

A hybrid betting automation tool for scraping, grading, and syncing Pinnacle and BetOnline wagers to Google Sheets.

### 🔧 Features
- ✅ Auto-scrapes Pinnacle and BetOnline bet history
- ✅ Extracts key metrics like EV%, CLV%, and Profit/Loss
- ✅ Syncs to Google Sheets dynamically
- ✅ Structured for future Discord/Telegram alert integration

### 📦 Setup

This project requires **Python 3.12** (3.11 is also supported). Create and activate a
virtual environment, then install the dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### ⚙️ Configuration

Update `Python Project Folder/config.py` with your local paths and Google Sheet ID:

```python
CHROME_USER_DATA_DIR = r"C:\\Users\\<you>\\AppData\\Local\\Google\\Chrome\\User Data"
GOOGLE_SHEET_ID = "<your-sheet-id>"
```

### 🚀 To Run

```bash
python hybrid_script.py
```

## CLV sync (Live Odds → Bet Tracking)
1. Put your Odds API Google Sheet ID into `config.LIVE_ODDS_SHEET_ID`.
2. Ensure Bet Tracking has `Event ID`, `Odds`, `Bookmaker`, `Market`, `Bet` columns.
3. Run:

```bash
python clv_sync.py
```

This writes **Closing Line** and **CLV%** back to the Bet Tracking tab.

