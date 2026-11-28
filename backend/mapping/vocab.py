# -*- coding: utf-8 -*-
"""월별 단가표 이력으로 상품명 어휘를 배운다 → mapping/data/learned_vocab.json

    python -m mapping.vocab                     # 크롤러 CSV 스냅샷 전부(1월~오늘)로 다시 배우기
    python -m mapping.vocab --min-foods 3       # 브랜드로 볼 최소 식재료 수

배우는 것
  · 제조사(makers): 사조 상품명 끝에 띄어 붙는 회사명 ('오뚜기', '씨제이제일제당', '풀잎새(주)')
      → 여러 상품의 마지막 낱말로 반복해서 나오고, 그 자체가 식재료 이름이 아닌 말
  · 브랜드·제품군(brand_prefixes): 식재료 이름 앞에 붙는 말 중 '여러 식재료'에 두루 붙는 말
      '옛날'국수소면 · '옛날'참기름 · '옛날'메밀국수 → 브랜드 (식재료 3개 이상)
      '검은참깨'두유 · '시바'새우살 → 한 식재료에만 → 품종일 수 있으니 배우지 않음 (검수로)
      앞말 자체가 식재료 이름으로 끝나면(도라지꿀배의 '도라지꿀') 다른 식품이 섞인 것이므로 제외
판정은 이 사전을 '앞에 붙어도 되는 말'로만 쓴다. 품종 표시(lexicon.VARIETY_MARKERS) 검사는 그대로 먼저 한다.
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict

import pandas as pd

from . import config as C
from . import lexicon as L

PATH = os.path.join(C.HERE, "data", "learned_vocab.json")
_COMPANY = re.compile(r"(식품|유업|제당|제일제당|푸드|산업|상사|\(주\)|주식회사|F&B|코리아|컴퍼니|농산|수산|유통)$")


def load() -> dict:
    try:
        return json.load(open(PATH, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"makers": [], "brand_prefixes": {}}


def all_snapshot_names(root: str = C.CRAWLER_DATA) -> pd.DataFrame:
    from .sources import CSV_COLS, csv_snapshot_days, csv_snapshot_path
    frames = []
    for sup in C.SUPPLIERS:
        for d in csv_snapshot_days(sup, root):
            p = csv_snapshot_path(sup, d, root)
            x = pd.read_csv(p, dtype=str, encoding="utf-8-sig", usecols=lambda c: c in ("단품명", "중분류"))
            x = x.rename(columns=CSV_COLS)
            x["supplier"] = sup
            frames.append(x)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["supplier", "item_nm"])
    return df[~df["mcls_nm"].fillna("").isin(C.NON_FOOD_MCLS)]


def learn(names: list[str], ings, min_foods: int = 3) -> dict:
    from .candidates import FormIndex
    from .features import explain
    from .normalize import nfkc, product_core
    fidx = FormIndex(ings)
    pforms = {f for f, ks in fidx.p_owners.items() if ks and len(f) >= 2}
    is_food = lambda w: any(w.endswith(f) for f in pforms)          # noqa: E731

    # 1) 제조사: 괄호 앞 머리말이 띄어 쓰였을 때 마지막 낱말, 또는 맨 끝 괄호 뒤 낱말
    last = Counter()
    for n in names:
        s = nfkc(n)
        head = re.split(r"[(\[/_]", s)[0].strip()
        toks = head.split()
        if len(toks) >= 2:
            last[toks[-1]] += 1
        m = re.search(r"\)\s+([^\s()]+)\s*$", s)
        if m:
            last[m.group(1)] += 1
    paren = Counter()
    for n in names:
        for m in re.findall(r"\(([^()]+)\)", nfkc(n)):
            for t in re.split(r"[,/_\s]", m):
                if t:
                    paren[t] += 1
    # 회사명 꼴이거나, 다른 상품명 괄호 안에 제조사로 나온 적이 있는 말만 (끝 낱말이 '가라아게' 같은 음식 이름일 수 있으므로)
    allforms = {f for f in fidx.idx if len(f) >= 2}
    statew = {x for ws in L.STATE_WORDS.values() for x in ws}
    def foodish(w):                                     # 식재료 이름이 들어 있거나 상태·맛·품종 표시인 말
        return (any(f in w for f in allforms) or w in statew or w.endswith("맛")
                or any(m in w for m in L.VARIETY_MARKERS + L.FLAVOR_MARKERS))
    makers = sorted(w for w, c in last.items()
                    if (_COMPANY.search(w) or paren[w] >= 2 or w in L.BRANDS) and not re.search(r"\d", w)
                    and re.search(r"[가-힣A-Za-z]", w) and not foodish(w) and len(w) >= 2
                    and w not in ("주식회사", "중국제조", "벌크", "필렛", "할복", "원두", "생지", "브라질넛", "다크", "레드",
                                  "밀크", "플레인", "화이트"))

    # 2) 브랜드·제품군 앞말
    seen = defaultdict(set)
    from .normalize import set_learned
    set_learned(makers, {})
    dummy = ings[0]
    for n in names:
        core, _ = product_core(n)
        for i in range(1, len(core) - 1):
            f = core[i:]
            if f not in pforms:
                continue
            lead = explain(core[:i], dummy, "front")["leftover"]
            if len(lead) >= 2 and not is_food(lead) and not any(t in lead for t in L.PROCESSED_TOKENS):
                seen[lead].add(f)
            break                                           # 가장 긴 끝맺음 형태 하나만
    def risky(w):                                       # 품종·맛 표시, 식재료 이름이 든 말, 식재료 이름의 앞부분('청양' ⊂ 청양고추)
        return foodish(w) or any(f.startswith(w) for f in fidx.idx)
    brands = {w: len(fs) for w, fs in seen.items() if len(fs) >= min_foods and not risky(w)}
    return {"makers": makers, "brand_prefixes": dict(sorted(brands.items(), key=lambda x: -x[1])),
            "n_names": len(names), "min_foods": min_foods}


def main(argv=None):
    from .sources import load_ingredients
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-foods", type=int, default=3)
    a = ap.parse_args(argv)
    df = all_snapshot_names()
    v = learn(df["item_nm"].dropna().tolist(), load_ingredients(), a.min_foods)
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(v, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"상품명 {v['n_names']:,}개 → 제조사 {len(v['makers'])}개, 브랜드·제품군 {len(v['brand_prefixes'])}개 → {PATH}")
    print("브랜드 예:", ", ".join(list(v["brand_prefixes"])[:40]))
    print("제조사 예:", ", ".join(v["makers"][:40]))


if __name__ == "__main__":
    main()
