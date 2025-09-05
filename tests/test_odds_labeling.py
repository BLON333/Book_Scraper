from core.odds_labeling import build_label, clean_half, base_market

def test_half():
    assert clean_half("9Â½")=="9½"

def test_totals():
    assert build_label("totals","over","9.5")=="Over 9.5"

def test_spreads():
    assert build_label("spreads","Blue Jays","1.5")=="Blue Jays +1.5"
