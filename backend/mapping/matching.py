# -*- coding: utf-8 -*-
"""② ~ ⑤ 를 묶는다: 상품 표 → 후보 쌍 → 특징 → 판정 결과 행 (ingredient_product_map 형식)."""
from collections import defaultdict
from statistics import median

import pandas as pd

from . import config as C
from . import lexicon as L
from .candidates import Embedder, FormIndex, TextSim, candidate_pairs
from .features import pair_features
from .judge import Model, decide
from .normalize import Ingredient, parse_product
from .units import Converter, price_with_tax


class CategoryMap:
    """공급사 (대분류, 중분류) ↔ 식약처 식품대분류. 초기값 + category_map 테이블(검수로 보완)."""

    def __init__(self, rows: list[dict] | None = None):
        self.allow = {k: set(v) for k, v in L.CATEGORY_SEED.items()}
        self.deny = defaultdict(set)
        for r in rows or []:
            key = (r["lcls_nm"], r["mcls_nm"])
            if (r.get("n_approved") or 0) > 0 or r.get("source") == "seed":
                self.allow.setdefault(key, set()).add(r["food_group"])
            elif (r.get("n_rejected") or 0) >= 5:
                self.deny[key].add(r["food_group"])

    def check(self, lcls: str, mcls: str, food_group: str, auto: bool) -> str:
        """ok | conflict | neutral.  '미분류' 식재료와 사조 자동분류는 conflict 로 보지 않는다(중립)."""
        key = (lcls, mcls)
        if food_group in self.deny.get(key, set()):
            return "conflict"
        if food_group == "미분류" or key not in self.allow:
            return "neutral"
        if food_group in self.allow[key]:
            return "ok"
        return "neutral" if auto else "conflict"


def price_ok(gp: float, refs: list) -> bool:
    """g당 가격이 정상 범위인가. 기준(식재료 중앙값·식품대분류 중앙값) 중 하나라도 1/3–5배 안이면 정상.
    (영양부추·조선부추처럼 한 코드에 값이 크게 다른 품종이 섞이면 식재료 중앙값만으로는 정상 상품을 이상값으로 본다)"""
    return any(r * C.OUTLIER_LOW <= gp <= r * C.OUTLIER_HIGH for r in refs if r)


def judge(products: pd.DataFrame, ings: list[Ingredient], *, model: Model | None = None,
          catmap: CategoryMap | None = None, conv: Converter | None = None, model_version: str | None = None,
          llm=None, ref_prices: dict | None = None) -> list[dict]:
    """products: sources._finish 형식 DataFrame (이번에 판단할 상품만).  반환: 판정 행 목록.
    ref_prices: {식재료ID: 어제까지의 g당 가격} — 하루 신규분처럼 상품이 적을 때 가격 범위 기준으로 쓴다."""
    catmap, conv = catmap or CategoryMap(), conv or Converter()
    rows = products.to_dict("records")
    prods = [parse_product(r) for r in rows]
    fidx, tsim = FormIndex(ings), TextSim(ings)
    cands = candidate_pairs(prods, ings, fidx, tsim)

    # 상품마다 '이름 주인' 길이: 모든 식재료 중 가장 긴 exact/suffix 형태 (대표·같은코드 이름 모두)
    owner_len = defaultdict(int)
    for (pi, ki), c in cands.items():
        for rel, form, tier in c["hits"]:
            if rel in ("exact", "suffix") and (len(form) >= 2 or rel == "exact"):
                owner_len[pi] = max(owner_len[pi], len(form))

    # 특징 1차 + g당 가격
    feats = {}
    gprice = {}
    for (pi, ki), c in cands.items():
        p, ing = prods[pi], ings[ki]
        f = pair_features(p, ing, c, fidx, ki, owner_len[pi])
        f["item_nm"], f["core"] = p.item_nm, p.core
        f["spec"], f["unit"] = rows[pi].get("spec"), rows[pi].get("unit")
        f["dcls_brand_ok"] = (p.lcls, None) in L.DCLS_BRAND_OK or (p.lcls, p.mcls) in L.DCLS_BRAND_OK
        f["category"] = catmap.check(p.lcls, p.mcls, ing.food_group, p.category_auto)
        g, basis = conv.grams(rows[pi].get("spec"), rows[pi].get("unit"), [ing.rep_name] + ing.names[:5],
                              rows[pi].get("item_nm"))
        pt = price_with_tax(rows[pi])
        if g and pt:
            gprice[(pi, ki)] = pt / g
        f["pack_g"], f["pack_basis"] = (round(g, 1) if g else None), basis
        f["price_per_g"] = round(pt / g, 4) if (g and pt) else None
        feats[(pi, ki)] = f

    # g당 가격 정상 범위: 그 식재료의 '확실한' 후보 중앙값(3개 이상) → 없으면 같은 식품대분류 중앙값
    strong = defaultdict(list)
    for key, f in feats.items():
        if key in gprice and f.get("rel") in ("exact", "suffix", "meat") and not f.get("processed") and not f.get("owned_elsewhere") \
                and not f.get("outranked") and not f.get("leftover") and f.get("part_match", "primary") == "primary":
            strong[key[1]].append(gprice[key])
    group_vals = defaultdict(list)
    for ki, v in strong.items():
        if ings[ki].food_group != "미분류":
            group_vals[ings[ki].food_group].append(median(v))
    ref_ing = {ki: median(v) for ki, v in strong.items() if len(v) >= 3}
    for ki, ing in enumerate(ings):                          # 어제 가격이 있으면 그것을 우선
        if ref_prices and ref_prices.get(ing.ingredient_id):
            ref_ing[ki] = float(ref_prices[ing.ingredient_id])
            if ing.food_group != "미분류":
                group_vals[ing.food_group].append(float(ref_prices[ing.ingredient_id]))
    ref_grp = {g: median(v) for g, v in group_vals.items() if len(v) >= 10}   # 식재료 10개 이상일 때만 대분류 기준
    for key, f in feats.items():
        ki = key[1]
        refs = [r for r in (ref_ing.get(ki), ref_grp.get(ings[ki].food_group)) if r]
        if key not in gprice:
            f["price_range"] = "none"
        elif not refs:
            f["price_range"] = "ok"                          # 비교할 기준이 없으면 이상하다고 할 수 없다
            f["price_ref"] = None
        else:
            f["price_range"] = "ok" if price_ok(gprice[key], refs) else "out"
            f["price_ref"] = round(refs[0], 4)

    # 임베딩 (선택)
    emb = Embedder(ings)
    if emb.model is not None:
        keys = list(feats)
        for key, v in zip(keys, emb.sims(prods, keys)):
            feats[key]["embed"] = round(float(v), 3)

    out = []
    for (pi, ki), f in feats.items():
        status, score, method, reason = decide(f, model)
        out.append({
            "ingredient_id": ings[ki].ingredient_id, "supplier": prods[pi].supplier, "item_cd": prods[pi].item_cd,
            "score": round(score, 4), "method": method, "status": status, "reason": reason,
            "features": f, "model_version": model_version or (model.version if model else C.RULE_VERSION),
            "_item_nm": prods[pi].item_nm, "_core": prods[pi].core, "_rep": ings[ki].rep_name, "_rank": ings[ki].rank,
            "_usage": ings[ki].usage_g,
        })
    if llm is not None:
        llm.review(out, prods_by_key={(p.supplier, p.item_cd): (p, rows[i]) for i, p in enumerate(prods)},
                   ings_by_id={i.ingredient_id: i for i in ings})
    return out
