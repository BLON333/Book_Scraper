# Odds API Sync

`odds_sync.py` pulls markets from [The Odds API](https://the-odds-api.com/) and writes them to the Google Sheet defined by `config.GOOGLE_SHEET_ID`.

- **Live Odds** tab: league, event id, matchup, start time, and bookmaker count (one row per event).
- **Detailed Odds** tab: one row per bookmaker × market × outcome for bets listed in the Bet sheet.

Inputs: `ODDS_API_KEY`, `LEAGUES`, `ALLOWED_BOOKS`, and bet rows with Event ID / Market / Bet.
Outputs: refreshed odds data used later by `clv_sync.py` to compute Closing Line and CLV%.
