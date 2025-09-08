from core.normalize_odds import normalize_odds


def sample_event_partial_books():
    return {
        "bookmakers": [
            {
                "key": "book1",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "A", "price": -110},
                            {"name": "B", "price": -110},
                        ],
                    }
                ],
            },
            {
                "key": "book2",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "A", "price": -105},
                        ],
                    }
                ],
            },
        ]
    }


def test_price_probability_same_books():
    event = sample_event_partial_books()
    results = normalize_odds(event, ["book1", "book2"])
    res_a = results["A"]
    res_b = results["B"]

    # Only book1 has both sides, so only book1 should contribute
    assert res_a["books"] == ["book1"]
    assert res_b["books"] == ["book1"]

    # Price should come from the same set of books used for the probability
    assert set(res_a["books"]) == set(res_a["book_prices"].keys())
    assert set(res_b["books"]) == set(res_b["book_prices"].keys())

    # Best price for A should ignore book2's unmatched price
    assert res_a["best_price"] == -110
    assert res_b["best_price"] == -110
