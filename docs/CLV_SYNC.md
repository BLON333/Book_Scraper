# CLV Sync

`clv_sync.py` reads bets and odds from the same Google Sheet (`config.GOOGLE_SHEET_ID`).

- Uses the **Detailed Odds** tab to locate closing prices for each bet.
- Updates the Bet sheet with **Closing Line** and **CLV%** columns.

Inputs: Bet rows with Event ID, Market, Bet, Odds, and Bookmaker.
Outputs: each matching bet is populated with its closing line and calculated CLV%.
Run after `odds_sync.py` or as part of `hybrid_script.py`.
