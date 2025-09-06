from core.consensus_pricer import (
    BetKey,
    compute_consensus,
    devig_two_way,
)


def test_devig_two_way_even():
    p1, p2 = devig_two_way(-110, -110)
    assert round(p1, 5) == 0.5
    assert round(p2, 5) == 0.5


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
