from core.odds_labeling import build_label, base_market


def test_base_market_ml():
    assert base_market("alternate_ml") == "h2h"


def test_totals():
    assert build_label("totals", "over", "9.5") == "Over 9.5"


def test_spreads():
    assert build_label("spreads", "Blue Jays", "1.5") == "Blue Jays +1.5"

