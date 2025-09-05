from core.odds_labeling import build_label, base_market, clean_half

def test_half_fix():
    assert clean_half("9Â½") == "9½"

def test_totals_label():
    assert build_label("totals","over","9.5") == "Over 9.5"

def test_spreads_label():
    assert build_label("spreads","Yankees","1.5") == "Yankees +1.5"
