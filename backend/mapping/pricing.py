# -*- coding: utf-8 -*-
"""⑥ 오늘 가격 결정 (식재료별).

1. 대상: 승인된 상품(auto_approved·approved) 중 오늘 판매 중인 것
   = 공급사별 최신 단가표에 있는 상품 (그 단가표가 기준일로부터 3일 이내일 때. 크롤링이 늦은 공급사도 가격이 비지 않게)
2. g당 가격 = 세금 포함 단가 ÷ 포장 중량(g)  (부피는 밀도, 개수는 개당 중량으로 환산. 환산 불가면 제외)
3. 이상값 제외: 기준 중앙값의 1/3 미만 또는 5배 초과 → 빼고 검수로 (규격 해석 오류일 가능성)
   기준 = 그 식재료의 오늘 승인 상품 중앙값(3개 이상일 때) → 아니면 같은 식품대분류 중앙값('미분류' 제외)
4. 두 공급사를 통틀어 g당 가격이 가장 싼 상품 = 오늘 가격 (공급사·상품 함께 저장)
5. 최적화용 가격 = 최근 28일 오늘 가격의 중앙값
6. 승인 상품이 없거나 오늘 판매 중인 게 없으면 비운다 (중앙값 대체 없음)
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

import pandas as pd

from . import config as C
from .normalize import Ingredient
from .units import Converter, price_with_tax

APPROVED = {"auto_approved", "approved"}


def decide(day: date, mapping: pd.DataFrame, products: pd.DataFrame, ings: list[Ingredient],
           history: pd.DataFrame | None = None, conv: Converter | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """→ (ingredient_price_daily 행, 이상값으로 뺀 상품 목록, 오늘 판매 중인 승인 상품별 g당 가격)"""
    conv = conv or Converter()
    by_id = {i.ingredient_id: i for i in ings}
    m = mapping[mapping["status"].isin(APPROVED)][["ingredient_id", "supplier", "item_cd", "status"]]
    # 공급사마다 자기 최신 단가표를 쓴다 (한 공급사 크롤링이 늦거나 실패한 날에도 다른 공급사 가격이 비지 않게).
    # 단, 기준일보다 STALE_DAYS 이상 오래된 단가표는 쓰지 않는다.
    parts = []
    for sup, g in products.groupby("supplier"):
        sday = g["last_seen"].max()
        if sday is not None and sday <= day and (day - sday).days < C.STALE_DAYS:
            parts.append(g[g["last_seen"] == sday])
    today = pd.concat(parts) if parts else products.iloc[0:0]
    j = m.merge(today, on=["supplier", "item_cd"], how="inner")

    offers = defaultdict(list)                     # ingredient_id → [(g당 가격, row)]
    for r in j.to_dict("records"):
        ing = by_id.get(r["ingredient_id"])
        if ing is None:
            continue
        g, basis = conv.grams(r.get("spec"), r.get("unit"), [ing.rep_name] + ing.names[:5], r.get("item_nm"))
        pt = price_with_tax(r)
        if not g or not pt:
            continue
        offers[ing.ingredient_id].append((pt / g, {**r, "pack_g": g, "pack_basis": basis, "price_tax": pt}))

    group_vals = defaultdict(list)
    for iid, lst in offers.items():
        fg = by_id[iid].food_group
        if fg != "미분류":
            group_vals[fg].append(median(v for v, _ in lst))
    group_ref = {g: median(v) for g, v in group_vals.items() if len(v) >= 3}

    hist = defaultdict(list)                       # 지난 가격 (28일 중앙값용)
    if history is not None and len(history):
        since = day - timedelta(days=C.MEDIAN_WINDOW_DAYS - 1)
        h = history[(history["price_date"] >= since) & (history["price_date"] < day)]
        for r in h.dropna(subset=["price_per_g"]).to_dict("records"):
            hist[r["ingredient_id"]].append(float(r["price_per_g"]))

    daily, outliers, offers_out = [], [], []
    for ing in ings:
        lst = offers.get(ing.ingredient_id, [])
        from .matching import price_ok
        refs = [x for x in ((median(v for v, _ in lst) if len(lst) >= 3 else None), group_ref.get(ing.food_group)) if x]
        ref = refs[0] if refs else None
        keep = []
        for v, r in lst:
            if refs and not price_ok(v, refs):
                outliers.append({"ingredient_id": ing.ingredient_id, "supplier": r["supplier"], "item_cd": r["item_cd"],
                                 "item_nm": r.get("item_nm"), "price_per_g": round(v, 4), "ref": round(ref, 4),
                                 "status": r["status"], "spec": r.get("spec"), "unit": r.get("unit")})
            else:
                keep.append((v, r))
        row = {"ingredient_id": ing.ingredient_id, "price_date": day, "price_per_g": None, "supplier": None,
               "item_cd": None, "item_nm": None, "n_candidates": len(keep), "price_per_g_28d": None}
        for sup in C.SUPPLIERS:
            row.update({f"{sup}_min": None, f"{sup}_item_cd": None, f"{sup}_item_nm": None, f"{sup}_n": 0})
        if keep:
            v, r = min(keep, key=lambda x: x[0])
            row.update(price_per_g=round(v, 5), supplier=r["supplier"], item_cd=r["item_cd"], item_nm=r.get("item_nm"))
            for sup in C.SUPPLIERS:                # 공급사별 최저가 상품 (그래프·구매 안내용)
                vs = [(x, rr) for x, rr in keep if rr["supplier"] == sup]
                if vs:
                    x, rr = min(vs, key=lambda t: t[0])
                    row.update({f"{sup}_min": round(x, 5), f"{sup}_item_cd": rr["item_cd"],
                                f"{sup}_item_nm": rr.get("item_nm"), f"{sup}_n": len(vs)})
        kept_keys = {(rr["supplier"], rr["item_cd"]) for _, rr in keep}
        for v, r in lst:
            offers_out.append({"ingredient_id": ing.ingredient_id, "supplier": r["supplier"], "item_cd": r["item_cd"],
                               "item_nm": r.get("item_nm"), "spec": r.get("spec"), "unit": r.get("unit"),
                               "pack_g": round(r["pack_g"], 1), "unit_price_tax": r["price_tax"],
                               "price_per_g": round(v, 5), "used": (r["supplier"], r["item_cd"]) in kept_keys})
        series = hist.get(ing.ingredient_id, []) + ([row["price_per_g"]] if row["price_per_g"] is not None else [])
        row["price_per_g_28d"] = round(median(series), 5) if series else None
        if not ing.not_product:
            daily.append(row)                      # 빈 가격도 남긴다 → 앱이 '가격 없는 식재료'로 보여 줌
    return daily, outliers, offers_out


def coverage(daily: list[dict], ings: list[Ingredient], col: str = C.OPTIMIZE_COL) -> dict:
    """사용 중량 기준 가격 연결률 (상품 아님 재료는 분모에서 뺀다)."""
    has = {r["ingredient_id"] for r in daily if r.get(col) is not None}
    tot = sum(i.usage_g for i in ings if not i.not_product)
    got = sum(i.usage_g for i in ings if i.ingredient_id in has)
    top300 = [i for i in ings if not i.not_product and i.rank <= 300]
    return {"weight_pct": round(100 * got / tot, 1) if tot else 0.0, "n_priced": len(has),
            "n_ingredients": sum(not i.not_product for i in ings),
            "top300_weight_pct": round(100 * sum(i.usage_g for i in top300 if i.ingredient_id in has)
                                       / max(sum(i.usage_g for i in top300), 1), 1)}
