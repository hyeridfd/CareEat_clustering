# -*- coding: utf-8 -*-
"""식단 시스템이 가격을 읽는 함수 (diet/build_pool.py 의 load_prices · price_per_g 교체용).

    from mapping.client import load_price_table, purchase_cost
    prices = load_price_table()                # {식재료ID: 최적화용 g당 가격 — 기본은 오늘 최저가 (config.OPTIMIZE_PRICE)}
    cost = purchase_cost(prices, "Recipe_R106-132000001-0000", use_g=50, discard_pct=9)

값이 없으면 None → 앱은 '가격 없는 식재료'로 표시하고 0원으로 둔다 (중앙값 대체 없음).
"""
from typing import Optional


def load_price_table(sb=None, col: str | None = None) -> dict:
    """ingredient_price_latest 뷰에서 식재료별 최신 가격.
    col 기본값 = config.OPTIMIZE_COL ('price_per_g' 오늘 최저가 | 'price_per_g_28d' 28일 중앙값)."""
    from mapping import config as C
    col = col or C.OPTIMIZE_COL
    if sb is None:
        from dependencies import get_supabase
        sb = get_supabase()
    out, start = {}, 0
    while True:
        rows = (sb.table("ingredient_price_latest").select(f"ingredient_id,{col},price_date")
                .range(start, start + 999).execute().data or [])
        for r in rows:
            if r.get(col) is not None:
                out[r["ingredient_id"]] = float(r[col])
        if len(rows) < 1000:
            return out
        start += 1000


def purchase_cost(prices: dict, ingredient_id: str, use_g: float, discard_pct: float = 0.0) -> Optional[float]:
    """구매 비용 = 실사용량 ÷ (1 − 폐기율) × g당 가격"""
    p = prices.get(ingredient_id)
    if p is None:
        return None
    keep = 1 - min(max(discard_pct or 0, 0), 95) / 100
    return use_g / keep * p
