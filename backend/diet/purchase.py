# -*- coding: utf-8 -*-
"""주간 발주 계획 — 개인별 배식량 → 1주 단위 식재료·고령친화식품 구매량과 예상 금액

  식재료 필요량 = Σ(어르신 · 끼니 · 칸) 레시피 원재료 실사용량 × (실제 배식 g ÷ 레시피 1인분 g)
    · 국·주찬·부찬 양념(소금·간장·된장 …)은 저염 조리 감량률(sodium_config.SEASONING_REDUCTION) 반영
    · 죽식 흰죽·영양죽, 백김치는 추가 레시피 재료로 계산
    · 고령친화식품으로 대체된 칸은 식재료에서 빼고 제품 발주로 계산
    · 물·정제수는 제외
  재고 차감 = 주차 순서대로, 그 주 첫날까지 유통기한이 남은 재고를 먼저 사용
  가격      = data/ingredient_prices.json (Neo4j 상품 매핑 · g당 최저가 상품) — 없으면 미등록으로 표시
              고령친화식품은 products.json 의 포장 단위(5인분) 가격 (부가세 별도)
  발주 시스템 연계 시 price_lookup() 만 바꾸면 된다.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from collections import defaultdict

from .sodium_config import SEASONING_REDUCTION, SEASONING_KEYWORDS

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PRICE_JSON = os.path.join(DATA_DIR, "ingredient_prices.json")
WEEK_DAYS = 7
EXCLUDE = {"물", "정제수", "얼음", "끓는물", "찬물"}
SLOT_CAT = {"밥": "밥", "국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "김치": "김치"}
_PRICES = None


def _prices() -> dict:
    global _PRICES
    if _PRICES is None:
        try:
            _PRICES = json.load(open(PRICE_JSON, encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            _PRICES = {}
    return _PRICES


def _base_name(name: str) -> str:
    return re.sub(r"\(.*?\)", "", name).strip()


def price_lookup(ingredient: str) -> dict | None:
    """식재료 → {상품명, 규격(g), 단가(원/개), g당 가격} — g당 최저가 상품. (발주 시스템 연계 지점)"""
    P = _prices()
    cand = P.get(ingredient) or P.get(_base_name(ingredient))
    if not cand:
        return None
    p = cand[0]
    name = next((p.get(k) for k in ("name", "title", "product_name", "goods_name", "상품명") if p.get(k)), None)
    try:
        unit_g, price = float(p.get("unit_g")), float(p.get("price_today"))
    except (TypeError, ValueError):
        return None
    return {"상품명": name or ingredient, "규격(g)": unit_g, "단가": price, "g당": price / unit_g,
            "출처": p.get("source") or p.get("mall") or p.get("site")}


def _is_seasoning(name: str) -> bool:
    return any(k in name for k in SEASONING_KEYWORDS)


def _menu_index(pool: dict, recipe_map: dict, extra: dict) -> dict:
    """메뉴명 → (분류, 1인분 g, {원재료: 실사용 g})"""
    idx = {}
    for src in (pool, extra):
        for cat, ms in (src or {}).items():
            for m in ms:
                ings = m.get("ingredients") or recipe_map.get(m["menu_name"]) or {}
                w = float((m.get("_raw") or {}).get("weight") or m.get("weight") or 0)
                if ings and w > 0:
                    idx.setdefault(m["menu_name"], (cat, w, ings))
    return idx


def _week_label(w: int, start: dt.date | None) -> dict:
    d1, d2 = (w - 1) * WEEK_DAYS + 1, w * WEEK_DAYS
    out = {"주차": w, "일차": f"{d1}~{d2}일차"}
    if start:
        a, b = start + dt.timedelta(days=d1 - 1), start + dt.timedelta(days=d2 - 1)
        out["기간"] = f"{a:%m.%d}~{b:%m.%d}"
        out["입고일"] = f"{a - dt.timedelta(days=1):%Y-%m-%d}"
    return out


def weekly_purchase(servings: dict, pool: dict, subs: list, products: list,
                    inventory: dict | None, n_days: int = 28) -> dict:
    from .inventory import recipe_ingredients, _match
    from .extra_recipes import load_extra_recipes

    idx = _menu_index(pool, recipe_ingredients(), load_extra_recipes())
    n_weeks = math.ceil(n_days / WEEK_DAYS)
    need = [defaultdict(float) for _ in range(n_weeks)]          # 주차별 식재료 g
    menus_of = [defaultdict(set) for _ in range(n_weeks)]
    missing = set()

    for eid, rows in (servings or {}).items():
        for x in rows:
            day = int(re.sub(r"\D", "", str(x["일차"])) or 1)
            w = min(n_weeks, (day - 1) // WEEK_DAYS + 1) - 1
            skip = set(x.get("대체") or [])                         # 고령친화식품 칸
            for slot, cat in SLOT_CAT.items():
                g = x.get(slot) or 0
                name = (x.get("메뉴") or {}).get(slot)
                if slot in skip or not g or not name or str(name).startswith("-"):
                    continue
                info = idx.get(name)
                if not info:
                    missing.add(name); continue
                mcat, mw, ings = info
                k = g / mw
                red = SEASONING_REDUCTION.get(SLOT_CAT.get(slot, mcat), 0.0)
                for ing, raw in ings.items():
                    if ing in EXCLUDE or not raw:
                        continue
                    q = raw * k * ((1 - red) if _is_seasoning(ing) else 1.0)
                    need[w][ing] += q
                    menus_of[w][ing].add(name)

    # 재고: 주차 순서대로 사용
    stock = []
    start = None
    if inventory:
        start = inventory.get("start")
        it = inventory["items"]
        stock = [{"name": r["식재료명"], "left": float(r["재고량(g)"]), "days": int(r["남은일수"])} for _, r in it.iterrows()]

    prod = {p["name"]: p for p in products or []}
    weeks = []
    for w in range(n_weeks):
        first_day = w * WEEK_DAYS + 1
        rows = []
        for ing, q in sorted(need[w].items(), key=lambda t: -t[1]):
            used = 0.0
            for s in stock:
                if s["left"] > 0 and s["days"] >= first_day and _match(s["name"], ing):
                    u = min(s["left"], q - used)
                    s["left"] -= u; used += u
                    if used >= q:
                        break
            buy = max(0.0, q - used)
            pr = price_lookup(ing)
            row = {"식재료명": ing, "필요량(g)": round(q), "재고사용(g)": round(used), "구매량(g)": round(buy),
                   "메뉴수": len(menus_of[w][ing])}
            if pr and buy > 0:
                n = math.ceil(buy / pr["규격(g)"] - 1e-9)
                row.update({"상품명": pr["상품명"], "규격(g)": pr["규격(g)"], "수량": n, "단가": round(pr["단가"]),
                            "금액": round(n * pr["단가"]), "g당": round(pr["g당"], 3), "출처": pr.get("출처")})
            elif pr:
                row.update({"상품명": pr["상품명"], "규격(g)": pr["규격(g)"], "수량": 0, "단가": round(pr["단가"]), "금액": 0})
            rows.append(row)

        # 고령친화식품 (포장 = 5인분)
        cnt = defaultdict(lambda: {"인분": 0, "g": 0.0})
        for s in subs or []:
            day = int(re.sub(r"\D", "", str(s["day"])) or 1)
            if min(n_weeks, (day - 1) // WEEK_DAYS + 1) - 1 != w:
                continue
            c = cnt[s["product"]]; c["인분"] += 1; c["g"] += s.get("grams") or 0
        prows = []
        for name, c in sorted(cnt.items(), key=lambda t: -t[1]["인분"]):
            p = prod.get(name, {})
            pack_g = p.get("pack_g")
            n = math.ceil(c["g"] / pack_g - 1e-9) if pack_g else None
            price = p.get("pack_price")
            prows.append({"제품": name, "업체": p.get("maker"), "인분": c["인분"], "필요량(g)": round(c["g"]),
                          "포장(g)": pack_g, "수량": n, "단가": price,
                          "금액": (n * price) if (n is not None and price) else None, "비고": p.get("price_note")})

        priced = [r for r in rows if r["구매량(g)"] > 0 and r.get("단가") is not None]
        unpriced = [r for r in rows if r["구매량(g)"] > 0 and r.get("단가") is None]
        weeks.append({**_week_label(w + 1, start),
                      "식재료": rows, "제품": prows,
                      "합계": {"식재료_품목": sum(1 for r in rows if r["구매량(g)"] > 0),
                               "식재료_금액": sum(r["금액"] for r in priced),
                               "단가미등록_품목": len(unpriced),
                               "단가미등록_구매량(kg)": round(sum(r["구매량(g)"] for r in unpriced) / 1000, 1),
                               "제품_금액": sum(r["금액"] or 0 for r in prows),
                               "제품_팩": sum(r["수량"] or 0 for r in prows),
                               "재고사용(kg)": round(sum(r["재고사용(g)"] for r in rows) / 1000, 1)}})
    return {"weeks": weeks, "price_source": "Neo4j 상품 매핑 (g당 최저가)" if _prices() else None,
            "price_count": len(_prices()), "missing_recipes": sorted(missing)[:30],
            "note": "식재료 금액은 부가세 포함 여부가 상품마다 다를 수 있음 · 고령친화식품은 부가세 별도"}
