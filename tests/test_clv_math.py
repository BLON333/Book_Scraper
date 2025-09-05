from core.odds_labeling import build_label, base_market


def test_base_market_moneyline():
    assert base_market("moneyline") == "h2h"


def test_totals_label():
    assert build_label("totals", "under", "9Â½") == "Under 9½"


def test_spreads_label():
    assert build_label("spreads", "Yankees", "1.5") == "Yankees +1.5"

