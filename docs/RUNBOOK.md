# RUNBOOK
1) Scrape Pinnacle → Bet_Tracking.csv
2) python google_sheets_sync.py
3) python odds_sync.py
4) python clv_sync.py  # from repo root
(or: python hybrid_script.py to run all)

Troubleshooting:
- Auth: regenerate credentials.json, share sheet with service account email.
- Headers: Bets header row=7, data row=8 (configurable). Detailed/Live headers on row 1.
- CLV: needs Event ID, Market, Bet, Odds, Bookmaker.
