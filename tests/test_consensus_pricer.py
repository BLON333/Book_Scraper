from core.consensus_pricer import (
    BetKey,
    compute_consensus,
    devig_two_way,
    pair_quotes_by_point,
)


def test_devig_two_way_even():
    p1, p2 = devig_two_way(-110, -110)
    assert round(p1, 5) == 0.5
    assert round(p2, 5) == 0.5


def test_devig_two_way_opposing():
    p1, p2 = devig_two_way(+110, -120)
    assert round(p1, 3) == 0.466
    assert round(p2, 3) == 0.534


def sample_event_moneyline():
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
                            {"name": "B", "price": -115},
                        ],
                    }
                ],
            },
        ]
    }


def test_compute_consensus_moneyline():
    event = sample_event_moneyline()
    results = compute_consensus(event, ["book1", "book2"])
    key_a = BetKey("h2h", "A")
    key_b = BetKey("h2h", "B")
    assert key_a in results and key_b in results
    res_a = results[key_a]
    assert set(res_a.books) == {"book1", "book2"}
    p1 = res_a.book_probabilities["book1"]
    p2 = res_a.book_probabilities["book2"]
    assert round(p1, 3) == 0.5
    assert 0 < p2 < 1
    expected = (p1 + p2) / 2
    assert round(res_a.consensus_probability, 6) == round(expected, 6)


def sample_event_totals():
    return {
        "bookmakers": [
            {
                "key": "book1",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 7.5},
                            {"name": "Under", "price": -110, "point": 7.5},
                        ],
                    }
                ],
            },
            {
                "key": "book2",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -105, "point": 7.5},
                            {"name": "Under", "price": -115, "point": 7.5},
                        ],
                    }
                ],
            },
        ]
    }


def test_pair_quotes_by_point_totals_grouping():
    quotes = {
        ("totals", 7.5): {
            "book1": {"Over 7.5": -110, "Under 7.5": -110},
            "book2": {"Over 7.5": -105, "Under 7.5": -115},
        },
        ("totals", 8.5): {
            "book1": {"Over 8.5": -105, "Under 8.5": -115},
        },
    }
    probs = pair_quotes_by_point(quotes)
    key_over75 = BetKey("totals", "Over 7.5")
    key_under75 = BetKey("totals", "Under 7.5")
    key_over85 = BetKey("totals", "Over 8.5")
    key_under85 = BetKey("totals", "Under 8.5")
    assert set(probs[key_over75]) == {"book1", "book2"}
    assert set(probs[key_under75]) == {"book1", "book2"}
    assert set(probs[key_over85]) == {"book1"}
    assert set(probs[key_under85]) == {"book1"}


def test_compute_consensus_totals():
    event = sample_event_totals()
    results = compute_consensus(event, ["book1", "book2"])
    key_over = BetKey("totals", "Over 7.5")
    key_under = BetKey("totals", "Under 7.5")
    assert key_over in results and key_under in results
    res_over = results[key_over]
    assert set(res_over.books) == {"book1", "book2"}
    p1, _ = devig_two_way(-110, -110)
    p2, _ = devig_two_way(-105, -115)
    expected = (p1 + p2) / 2
    assert round(res_over.consensus_probability, 6) == round(expected, 6)


def sample_event_spread():
    return {
        "bookmakers": [
            {
                "key": "book1",
                "markets": [
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "A", "price": -110, "point": -3.5},
                            {"name": "B", "price": -110, "point": 3.5},
                        ],
                    }
                ],
            }
        ]
    }


def test_spread_pairing():
    event = sample_event_spread()
    results = compute_consensus(event, ["book1"])
    key_a = BetKey("spreads", "A -3.5")
    key_b = BetKey("spreads", "B +3.5")
    assert key_a in results and key_b in results
    assert round(results[key_a].consensus_probability, 3) == 0.5
    assert round(results[key_b].consensus_probability, 3) == 0.5


def sample_event_totals_incomplete():
    return {
        "bookmakers": [
            {
                "key": "book1",
                "markets": [
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 7.5},
                        ],
                    }
                ],
            }
        ]
    }


def test_compute_consensus_missing_counterpart():
    event = sample_event_totals_incomplete()
    results = compute_consensus(event, ["book1"])
    assert results == {}
    key_over = BetKey("totals", "Over 7.5")
    assert results.get(key_over) is None
