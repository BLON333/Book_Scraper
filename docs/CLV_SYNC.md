# Closing Line Value (CLV) Sync
**Goal:** Fill `Closing Line` and `CLV%` in Bet Tracking using odds from `Detailed Odds`.

**Linking key:** `Event ID`. Bets without `Event ID` are skipped.  
Use your scrapers’ event-ID merge (Pinnacle_Scraper/BetOnline_Scraper) or set manually.

**Computation:**
- Convert American odds → implied probability `p = 100/(v+100)` for positive, `p = -v/(-v+100)` for negative.
- `CLV% = (p_closing / p_entry - 1) × 100`.

**Matching rules:**
- First prefer the same **Bookmaker** as the bet; otherwise fall back to any book with matching `Market` + `Label`.
- Totals labels normalize to `Over/Under X.Y`; spreads keep `Team ±X.Y`; H2H keeps team.

**Runbook:**

set LIVE_ODDS_SHEET_ID in config.py

python clv_sync.py

or as part of: python hybrid_script.py

