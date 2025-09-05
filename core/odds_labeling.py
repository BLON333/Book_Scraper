import re


def clean_half(s: str) -> str:
    return (s or "").replace("Â½","½")


def build_label(api_market: str, name_norm: str, point: str) -> str:
    m = (api_market or "").lower().strip()
    if m.startswith("alternate_"): m = m.replace("alternate_","",1)
    nm = clean_half(name_norm or "").strip()
    pt = clean_half(point or "").strip()
    if m=="totals":
        return f"{nm.title()} {pt}".strip()
    elif m=="spreads":
        if pt and not pt.startswith(("+","-")): pt = f"+{pt}"
        return f"{nm} {pt}".strip()
    else:
        return nm  # h2h


def base_market(m: str) -> str:
    return (m or "").lower().strip().split("_")[0]
