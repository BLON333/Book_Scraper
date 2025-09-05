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

## Odds & CLV sync
1. Fill `ODDS_API_KEY` and `GOOGLE_SHEET_ID` in `config.py`.
2. Ensure Bet Tracking has `Event ID`, `Odds`, `Bookmaker`, `Market`, `Bet` columns.
3. Update odds and CLV with:

```bash
python odds_sync.py
python clv_sync.py
```

or run the full pipeline via `python hybrid_script.py`.
This writes **Live/Detailed Odds** tabs and fills **Closing Line** / **CLV%** in the Bet sheet.

# Bet Tracking Automation (Pipeline)
- Python-only pipeline; single Google Sheet for Bets + Live Odds + Detailed Odds
- Configure IDs in config.py; set ODDS_API_KEY via environment
- Run: python hybrid_script.py

Quick check

```powershell
python -m pytest -q tests 2>$null
```

