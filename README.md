# MLB Odds Tracker 📊

A hybrid betting automation tool for scraping, grading, and syncing Pinnacle and BetOnline wagers to Google Sheets.

### 🔧 Features
- ✅ Auto-scrapes Pinnacle and BetOnline bet history
- ✅ Extracts key metrics like EV%, CLV%, and Profit/Loss
- ✅ Syncs to Google Sheets dynamically
- ✅ Structured for future Discord/Telegram alert integration

### 📦 Setup

Install the Python dependencies:

```bash
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

