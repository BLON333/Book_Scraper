# Odds API → Google Sheets
This project reads **odds already exported to Google Sheets** by our Odds API service.

- Spreadsheet: **Live Odds** (`LIVE_ODDS_SHEET_ID` in `config.py`)
- Tabs:
  - **Live Odds** — one row per event (high-level snapshot)
  - **Detailed Odds** — multiple rows per event; one row per **book × market × label** (used for CLV)

**Columns expected in `Detailed Odds`** (case-insensitive):
- `Event ID` — canonical key we also store in Bet Tracking
- `Book` (or `Bookmaker` / `Sportsbook`)
- `Market` — e.g., `h2h`, `spreads`, `totals`, `team_totals` (+ optional `_q1`, `_h1`, etc.)
- `Label` — outcome label; examples:
  - Totals: `Over 9.5` / `Under 9.5`
  - Spreads: `Team +3.5`
  - H2H: `Team`
- `Odds` (or `American` / `Price`) — American odds for that outcome

If names differ, update `clv_sync.py`’s `pick_closing_line()` aliases.

