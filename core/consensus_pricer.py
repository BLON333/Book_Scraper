from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from collections import defaultdict

from . import odds_labeling


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BetKey:
    """Identifier for a single bet outcome."""

    market: str
    label: str


@dataclass
class BookQuote:
    """Quote offered by a particular book."""

    book: str
    price: int
    label: str
    market: str
    pair_key: Any


@dataclass
class DevigResult:
    """No-vig probability information for a particular bet."""

    book_probabilities: Dict[str, float]
    consensus_probability: Optional[float]
    consensus_odds: Optional[int]
    books: List[str]
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(point: Any) -> Optional[float]:
    if point is None or point == "":
        return None
    s = str(point).replace("Â½", ".5").replace("½", ".5")
    try:
        return float(s)
    except ValueError:
        return None


def _american_to_prob(odds: int) -> float:
    if odds is None:
        return 0.0
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def _prob_to_american(prob: float) -> int:
    if prob <= 0:
        return 0
    if prob >= 1:
        return -1000000000  # effectively infinity
    if prob > 0.5:
        return int(round(-prob * 100 / (1 - prob)))
    return int(round((1 - prob) * 100 / prob))


ALLOWED_MARKETS = {"h2h", "spreads", "totals", "team_totals"}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def normalize_market_and_label(api_market: str, outcome: Dict[str, Any]) -> Optional[Tuple[str, str, Any]]:
    """Return normalized market, label and pair key for an outcome.

    Pair key is used for pairing opposite sides of the same market. For spreads
    we pair by absolute point; for totals by point; for team totals by team and
    point.
    """

    base = odds_labeling.base_market(api_market)
    base = base or ""
    if base not in ALLOWED_MARKETS:
        return None

    name = outcome.get("name") or ""
    point_val = _to_float(outcome.get("point"))

    if base == "team_totals":
        team = outcome.get("team") or name.split()[0]
        side = name.title() if name else ""
        label = f"{team} {side} {outcome.get('point', '')}".strip()
        pair_key: Any = (team, point_val)
    elif base == "spreads":
        label = odds_labeling.build_label(api_market, name, str(outcome.get("point", "")))
        pair_key = abs(point_val) if point_val is not None else None
    elif base == "totals":
        label = odds_labeling.build_label(api_market, name, str(outcome.get("point", "")))
        pair_key = point_val
    else:  # h2h
        label = odds_labeling.build_label(api_market, name, str(outcome.get("point", "")))
        pair_key = "h2h"

    return base, label, pair_key


def extract_book_quotes(event: Dict[str, Any], allowed_books: Iterable[str]) -> Dict[Tuple[str, Any], Dict[str, Dict[str, int]]]:
    """Extract quotes indexed by pair key and book.

    Returns a mapping ``{(market, pair_key): {book: {label: price}}}``.
    """

    allowed = set(allowed_books or [])
    quotes: Dict[Tuple[str, Any], Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(dict))

    for bm in event.get("bookmakers", []):
        book = bm.get("key")
        if allowed and book not in allowed:
            continue
        for market in bm.get("markets", []):
            mkey = market.get("key")
            for outcome in market.get("outcomes", []):
                norm = normalize_market_and_label(mkey, outcome)
                if not norm:
                    continue
                market_name, label, pair_key = norm
                quotes[(market_name, pair_key)][book][label] = outcome.get("price")

    return quotes


def devig_two_way(odds1: int, odds2: int) -> Tuple[float, float]:
    """Return no-vig probabilities for a two-way market."""

    p1 = _american_to_prob(odds1)
    p2 = _american_to_prob(odds2)
    total = p1 + p2
    if total == 0:
        return 0.0, 0.0
    return p1 / total, p2 / total


def pair_quotes_by_point(quotes: Dict[Tuple[str, Any], Dict[str, Dict[str, int]]]) -> Dict[BetKey, Dict[str, float]]:
    """Pair opposite quotes and compute per-book probabilities."""

    probs: Dict[BetKey, Dict[str, float]] = defaultdict(dict)

    for (market, _pair_key), book_data in quotes.items():
        for book, label_price in book_data.items():
            if len(label_price) < 2:
                continue
            items = list(label_price.items())[:2]
            (label1, price1), (label2, price2) = items
            p1, p2 = devig_two_way(price1, price2)
            probs[BetKey(market, label1)][book] = p1
            probs[BetKey(market, label2)][book] = p2

    return probs


def compute_consensus(event: Dict[str, Any], allowed_books: Iterable[str]) -> Dict[BetKey, DevigResult]:
    """Compute consensus probabilities across allowed books."""

    raw_quotes = extract_book_quotes(event, allowed_books)
    per_book = pair_quotes_by_point(raw_quotes)
    results: Dict[BetKey, DevigResult] = {}

    for bet, book_probs in per_book.items():
        books = sorted(book_probs)
        notes: List[str] = []
        if books:
            consensus = sum(book_probs.values()) / len(book_probs)
            odds = _prob_to_american(consensus)
        else:
            consensus = None
            odds = None
            notes.append("no valid books")
        results[bet] = DevigResult(
            book_probabilities=book_probs,
            consensus_probability=consensus,
            consensus_odds=odds,
            books=books,
            notes=notes,
        )

    return results


__all__ = [
    "BetKey",
    "BookQuote",
    "DevigResult",
    "normalize_market_and_label",
    "extract_book_quotes",
    "devig_two_way",
    "pair_quotes_by_point",
    "compute_consensus",
]
