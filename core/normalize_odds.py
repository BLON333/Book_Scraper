from __future__ import annotations

"""Utility helpers for deriving no-vig probabilities and best prices.

This module builds per-label no-vig probabilities from available book quotes
and tracks the book-specific prices used for those probabilities.  Best prices
are restricted to the same set of books contributing to the probability so that
price and probability are derived from identical sources.
"""

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .consensus_pricer import devig_two_way, extract_book_quotes


def normalize_odds(event: Dict[str, Any], allowed_books: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Return normalized odds information for each label in an event.

    Only books offering both sides of a two-way market are considered.  The
    returned mapping contains the no-vig probability, the best available price
    from those books, and the book-specific data used to derive them.
    """

    raw_quotes = extract_book_quotes(event, allowed_books)

    # Intermediate storage for probabilities and prices per label
    book_probs: Dict[str, Dict[str, float]] = defaultdict(dict)
    book_prices: Dict[str, Dict[str, int]] = defaultdict(dict)

    for (_market, _pair_key), book_data in raw_quotes.items():
        for book, label_price in book_data.items():
            # Only consider books that offer both sides of the market
            if len(label_price) < 2:
                continue
            items = list(label_price.items())[:2]
            (label1, price1), (label2, price2) = items
            p1, p2 = devig_two_way(price1, price2)
            book_probs[label1][book] = p1
            book_probs[label2][book] = p2
            book_prices[label1][book] = price1
            book_prices[label2][book] = price2

    results: Dict[str, Dict[str, Any]] = {}
    for label, probs in book_probs.items():
        books = sorted(probs.keys())
        if books:
            novig_prob = sum(probs[b] for b in books) / len(books)
            # Restrict best price to the same books used for novig probability
            prices_for_books = {b: book_prices[label][b] for b in books}
            best_price = max(prices_for_books.values())
        else:
            novig_prob = None
            prices_for_books = {}
            best_price = None
        results[label] = {
            "books": books,
            "book_probabilities": {b: probs[b] for b in books},
            "book_prices": prices_for_books,
            "novig_probability": novig_prob,
            "best_price": best_price,
        }

    return results


__all__ = ["normalize_odds"]
