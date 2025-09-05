# RUNBOOK
- 1) Scrape Pinnacle → Bet_Tracking.csv
- 2) python google_sheets_sync.py
- 3) python odds_sync.py
- 4) python clv_sync.py

Troubleshooting:
- Auth: regenerate credentials.json, share sheet with service account.
- Headers: ensure header row indices in config.py and column names match docs/DATA_SCHEMA.md.
