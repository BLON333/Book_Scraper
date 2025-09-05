def base_market(api_market: str) -> str:
    k = (api_market or "").lower().strip()
    if k.startswith("alternate_"):
        k = k.replace("alternate_", "", 1)
    if k in ("ml", "moneyline"):
        return "h2h"
    if k in ("h2h", "spreads", "totals"):
        return k
    return k  # fallback


def _norm_name(s: str) -> str:
    return " ".join((s or "").replace("Â½", "½").split())


def _sign_point(point: str) -> str:
    p = (point or "").strip()
    if not p:
        return ""
    if p[0] in "+-":
        return p.replace("Â½", "½")
    return f"+{p.replace('Â½','½')}"


def build_label(api_market: str, outcome_name: str, outcome_point: str) -> str:
    bm = base_market(api_market)
    name = _norm_name(outcome_name)
    if bm == "totals":
        side = name.split()[0].title() if name else ""
        return f"{side} {(outcome_point or '').replace('Â½','½')}".strip()
    if bm == "spreads":
        return f"{name} {_sign_point(outcome_point)}".strip()
    return name  # h2h

