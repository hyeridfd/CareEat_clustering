# -*- coding: utf-8 -*-
"""
build_pool.py  ─  recipes.csv × 식품영양성분 DB(식품코드) → 후보 메뉴 풀(pool.json 형식)
==========================================================================================
메뉴 영양소 = Σ 원재료 [ 100g당 영양소 × 원재료 중량(영양성분 계산용) / 100 ]
  · 기존 pool.json(에이전트 스냅샷)과 같은 계산식 (예: 쌀밥 = 백미 90g × 366kcal/100g = 329.4kcal)
  · weight           = Σ 원재료 중량(영양성분 계산용)
  · sodium_seasoning = 양념 재료(sodium_config.SEASONING_KEYWORDS)에서 나온 나트륨
  · cost             = Σ 실사용량 × g당 가격(ingredient_prices.json, purchase.price_lookup 과 같은 규칙)
  · caution_ingredients = ingredient_policy.CAUTION_INGREDIENTS 에 해당하는 재료
  · ingredients      = {원재료명: 실사용 g}  (purchase.py 가 그대로 사용)

영양 DB 파일
  · data/nutrient.csv(원재료성 R) + data/nutrients/*.csv, *.csv.gz(통합: 가공식품 P·음식 D) 를 모두 읽어 식품코드로 합친다 (cp949/utf-8 자동 판별)
  · 가공식품(P…)·음식(D…) DB 파일을 data/nutrients/ 에 넣고 다시 실행하면 자동으로 매칭이 늘어난다
  · 100ml 기준 항목은 1ml ≈ 1g 으로 본다
  · 원재료명에 '절임용'이 들어간 재료(김치 절임 소금)는 영양 계산에서 뺀다 (기존 pool.json 과 동일)

완전성 규칙 (기본)
  · 레시피의 모든 원재료(계산용 중량 > 0, 물 제외)가 DB에 매칭된 메뉴만 풀에 넣는다
    → 간장·고추장 같은 양념이 빠지면 나트륨이 크게 과소평가되므로, 일부만 매칭된 메뉴는 넣지 않는다
  · 기존 recipes_v0.csv 에 있던 메뉴는 그 '구분'을 따른다 (기존 식단 구조 유지)
  · 영양 DB에 없는 코드 중 같은 식품이 확실한 것은 CODE_ALIAS 로 연결 (재래간장, 실파)
  · 간식은 그대로 둔다 (영양만 계산, 제외·구분 조정 없음) → pool["간식"]
  · 장류(양념장·소스)와 요양원 급식에 맞지 않는 메뉴(UNSUITABLE_RULES)는 뺀다 → pool_coverage.csv '제외사유'
  · 만두(A0313)는 부찬, 떡국·만두국(A0314)은 국 (CAT_BY_CLASS)
  · policy_auto: 한 그릇 음식·다진찬 적합도 자동 분류 (meal_policy_auto.py, 영양사 판정이 없는 메뉴에 쓰임)
  · 식품코드가 'DB 없음'인 재료(육수 등)는 0 으로 계산하고 missing 으로 기록한다 (--strict-nodb 로 제외 가능)

사용
  cd backend
  python -m diet.build_pool        # recipes_v1.csv(새 레시피) + recipes.csv(기존 구분) → data/pool.json
  ※ 파이프라인(pipeline.ensure_pool)이 입력 파일이 바뀐 것을 감지하면 자동으로 다시 만든다
  ※ 기존 에이전트 스냅샷은 data/pool_v0.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

try:
    from .sodium_config import SEASONING_KEYWORDS
    from .ingredient_policy import CAUTION_INGREDIENTS
    from . import meal_policy_auto
except ImportError:  # 단독 실행
    import sys
    sys.path.insert(0, HERE)
    from sodium_config import SEASONING_KEYWORDS
    from ingredient_policy import CAUTION_INGREDIENTS
    import meal_policy_auto

# pool.json 키 ← 영양 DB 열
NUTRIENT_COLS = {
    "energy": "에너지(kcal)", "protein": "단백질(g)", "fat": "지방(g)", "sugar": "당류(g)",
    "fiber": "식이섬유(g)", "sodium": "나트륨(mg)", "carb": "탄수화물(g)", "sat_fat": "포화지방산(g)",
    "potassium": "칼륨(mg)", "vit_d": "비타민 D(μg)",
}
POOL_CATS = ("밥", "국", "주찬", "부찬", "김치", "간식")
# 간식은 레시피 DB 그대로 유지 (급식 부적합 규칙·구분 조정 적용 안 함). 식단 칸(DAILY_SLOTS)에는 쓰이지 않는다.
SNACK = "간식"
# 밥 칸에는 '밥 한 공기' 성격의 메뉴만 (덮밥·볶음밥·면·죽·빵은 한 끼 구조가 달라 기본 제외)
RICE_METHODS = {"쌀밥", "혼합영양밥", "채소밥"}
WATER = {"물", "정제수", "얼음", "끓는물", "찬물"}
NO_DB = {"DB 없음", "DB없음", "", "nan"}
# 영양 DB에 없는 식품코드 → 같은 식품의 다른 코드 (recipes_v0.csv 가 쓰던 코드)
#   (레시피 식품코드 → 영양 DB에 있는 같은/가장 비슷한 식품 코드) — 2026-11-25 정리
CODE_ALIAS = {
    "P112-003000300-0006": "R118-001030000-0000",   # 재래간장 → 간장_재래
    "R106-191020001-0000": "R106-191040001-0000",   # 실파 → 파 (v0 '파(실파)' 코드)
    "P123-304030200-0003": "P123-304030200-0026",   # 만두피·춘권피 → 생만두피
    "P116-708070200-0060": "P124-200020000-0150",   # 핫케이크가루 → 핫케이크믹스
    "P101-405000400-2512": "P101-405000400-5322",   # 햄버거빵 → 햄버거빵
    "P101-103000400-0963": "P101-103000100-5209",   # 아이비(과자)·비스킷 → 아이비
    "P117-202020200-0007": "P117-100010300-0419",   # 페퍼로니햄 → 페퍼로니
    "P108-001000100-0013": "P108-001000100-0172",   # 라멘(생면) → 생라면 사리
    "P123-302030100-0054": "P123-302030100-1909",   # 새우만두 → 통새우만두
    "P123-302030100-0056": "P123-302030100-0057",   # 주꾸미만두 → 개성왕주꾸미만두
    "P123-201020300-1187": "P123-201020300-4469",   # 곤약밥 → 현미흑미곤약밥
    "P112-013001300-0105": "P113-206020400-1838",   # 약고추장 → 약고추장
    "P119-202040200-0033": "P113-205020400-0058",   # 그릭요거트드레싱 → 플레인요거트드레싱
    "P109-302030200-1118": "P109-303030300-1186",   # 도라지배즙 → 황금배도라지즙
    "P101-405000400-1789": "P101-429000400-0066",   # 미니와플(시판) → 미니와플
    "P101-103000400-0452": "P101-103000400-2639",   # 마가렛트 → 촉촉한 마가렛쿠키
    "P116-708070200-0128": "P124-200020000-0075",   # 브라우니믹스 → 브라우니믹스
    "P102-101010100-0548": "P102-101010100-0551",   # 초코아이스크림 → 초코아이스크림
    "R106-113007601-0000": "R106-113007101-0000",   # 순무 → 순무_전체_생것
    "R106-113007819-0000": "P114-103010200-0243",   # 순무김치 → 순무김치(가공)
    "R112-845035101-1200": "R112-845033901-0000",   # 청각(생것) → 청각_전체_생것_대표
    "R211-667114008-0000": "R211-667014801-0000",   # 오징어(냉동) → 오징어_몸통_생것_대표
    "R211-217134008-0000": "R211-217054001-0649",   # 장어(손질_냉동) → 뱀장어_육_생것
    "R211-065034001-5272": "R211-065032801-0000",   # 오보로(대구살) → 대구_육_생것_대표
    "R211-065034301-6793": "R211-065034301-0000",   # 새꼬리민태 알 → 대구_알_생것_대표
}

# ── 요양원 급식에 맞지 않아 후보에서 빼는 메뉴 (음식명 정규식) ─────────────────────
UNSUITABLE_RULES = [
    ("손으로 집어 먹는 밥(김밥·주먹밥·초밥·쌈밥)", r"김밥|주먹밥|오니기리|초밥|스시|쌈밥|마끼"),
    ("날것(회·육회·게장·장 절임) — 고령자 식중독 위험",
     r"(?<![숙강초])회$|회무침|육회|물회|사시미|타다키|카르파치오|세비체|탕탕이|생굴.*무침|생굴$|연어회|"
     r"게장$|새우장$|연어장$|전복장$|간장새우$"),
    ("분식·서양 핑거푸드(버거·샌드위치·피자·타코 등)",
     r"(?<!햄)버거|샌드위치|피자$|핫도그|타코|카나페|토스트|또띠아|브리또|부리또|퀘사디아|나초|스프링롤|라이스페이퍼롤"),
]
UNSUITABLE_KEEP = {"함초밥"}     # 이름이 걸리지만 급식에 맞는 메뉴 (함초+밥)

# ── 구분 조정 ─────────────────────────────────────────────────────────────
#   만두(A0313 만두류)는 기존 시스템처럼 부찬, 떡국·만두국(A0314)은 국
CAT_BY_CLASS = {"A0313": "부찬", "A0314": "국"}

R_COL = {"name": "음식명", "cat": "구분", "mid": "중분류", "method": "조리법 유형", "code": "음식 코드",
         "ing": "원재료명", "w_use": "원재료 중량 (실사용량)", "w_nut": "원재료 중량 (영양성분 계산용)",
         "fcode": "식품코드", "major": "대분류", "cls": "음식 분류코드"}


def read_csv_any(path: str, **kw) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"인코딩을 알 수 없음: {path}")


def load_nutrient_db(paths: list[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        want = {"식품코드", "식품명", *NUTRIENT_COLS.values()}
        d = read_csv_any(p, dtype={"식품코드": str}, usecols=lambda c: c in want, low_memory=False)
        missing = [c for c in ["식품코드", *NUTRIENT_COLS.values()] if c not in d.columns]
        if missing:
            raise ValueError(f"{p}: 열 없음 {missing}")
        frames.append(d[["식품코드", "식품명", *NUTRIENT_COLS.values()]])
        print(f"  영양 DB {os.path.basename(p)}: {len(d):,}건")
    db = pd.concat(frames, ignore_index=True)
    db["식품코드"] = db["식품코드"].astype(str).str.strip()
    db = db.drop_duplicates("식품코드", keep="first").set_index("식품코드")
    for c in NUTRIENT_COLS.values():
        db[c] = pd.to_numeric(db[c], errors="coerce").fillna(0.0)
    return db


def load_prices(path: str) -> dict:
    try:
        return json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def price_per_g(prices: dict, ing: str) -> float | None:
    cand = prices.get(ing) or prices.get(re.sub(r"\(.*?\)", "", ing).strip())
    if not cand:
        return None
    try:
        return float(cand[0]["price_today"]) / float(cand[0]["unit_g"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def is_seasoning(ing: str) -> bool:
    return any(k in ing for k in SEASONING_KEYWORDS)


def build(recipes_path: str, nutrient_paths: list[str], price_path: str,
          strict_nodb: bool = False, one_bowl: bool = False, partial: bool = False,
          category_from: str | None = None):
    r = read_csv_any(recipes_path, dtype={R_COL["fcode"]: str, R_COL["code"]: str})
    r[R_COL["fcode"]] = r[R_COL["fcode"]].astype(str).str.strip().replace(CODE_ALIAS)
    # 기존 시스템에 있던 메뉴는 기존 '구분'을 그대로 쓴다 (예: 만두=부찬, 김밥=주찬, 수제비=국)
    keep_cat = {}
    if category_from and os.path.exists(category_from):
        v0 = read_csv_any(category_from, usecols=[R_COL["name"], R_COL["cat"]]).drop_duplicates(R_COL["name"])
        keep_cat = dict(zip(v0[R_COL["name"]].astype(str), v0[R_COL["cat"]].astype(str)))
    r[R_COL["ing"]] = r[R_COL["ing"]].astype(str).str.strip()
    for c in (R_COL["w_use"], R_COL["w_nut"]):
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(0.0)
    db = load_nutrient_db(nutrient_paths)
    prices = load_prices(price_path)

    pool = {c: [] for c in POOL_CATS}
    report, miss_rows, miss_menus, miss_names = [], Counter(), {}, {}
    for code, g in r.groupby(R_COL["code"], sort=False):
        first = g.iloc[0]
        name, cat = str(first[R_COL["name"]]), str(first[R_COL["cat"]])
        cls, major = str(first[R_COL["cls"]]), str(first[R_COL["major"]])
        legacy = name in keep_cat
        cat = keep_cat.get(name, cat)
        if cls in CAT_BY_CLASS or (cls == "A0316" and name.endswith("만두")):
            cat, legacy = CAT_BY_CLASS.get(cls, "부찬"), True
            if re.search(r"(국|(?<!맛)탕|전골|찌개|짜글이)$", re.sub(r"\(.*?\)", "", name).strip()):      # 만두국·완탕 등 국물 요리는 국
                cat = "국"
        drop = ""
        if major == "장류" or cls.startswith("D"):
            drop = "장류(양념장·소스)"
        elif cat != SNACK and name not in UNSUITABLE_KEEP:
            drop = next((why for why, pat in UNSUITABLE_RULES if re.search(pat, name)), "")
        tot = {k: 0.0 for k in NUTRIENT_COLS}
        na_season, cost, priced_all = 0.0, 0.0, True
        weight, missing, nodb, ings, ids = 0.0, [], [], {}, {}
        for _, row in g.iterrows():
            ing, fc, wn, wu = row[R_COL["ing"]], row[R_COL["fcode"]], row[R_COL["w_nut"]], row[R_COL["w_use"]]
            if ing in WATER:
                continue
            if wu > 0:
                ings[ing] = ings.get(ing, 0.0) + float(wu)
                # 식재료ID — 지식그래프(scripts/load_graph.py)·공급사 매핑(mapping/)과 같은 규칙: 식품코드 단위, 없으면 원재료명
                ids.setdefault(ing, f"Recipe_{fc}" if (fc not in NO_DB and fc in db.index) else f"Recipe_NAME:{ing}")
                ppg = price_per_g(prices, ing)
                if ppg is None:
                    priced_all = False
                else:
                    cost += wu * ppg
            if "절임용" in ing:          # 절임 후 헹궈 버리는 소금 — 기존 pool.json 과 같이 영양 계산에서 제외
                continue
            weight += wn
            if wn <= 0:
                continue
            if fc in NO_DB:
                nodb.append(ing)
                continue
            if fc not in db.index:
                missing.append(ing)
                miss_rows[fc] += 1
                miss_menus.setdefault(fc, set()).add(code)
                miss_names.setdefault(fc, Counter())[ing] += 1
                continue
            v = db.loc[fc]
            for k, col in NUTRIENT_COLS.items():
                tot[k] += float(v[col]) * wn / 100.0
            if is_seasoning(ing):
                na_season += float(v["나트륨(mg)"]) * wn / 100.0

        complete = not missing and not (strict_nodb and nodb)
        in_slot = not drop and cat in POOL_CATS and (
            cat != "밥" or one_bowl or legacy
            or (first[R_COL["mid"]] == "밥류" and first[R_COL["method"]] in RICE_METHODS))
        report.append({"음식 코드": code, "음식명": name, "구분": cat, "기존구분유지": legacy, "제외사유": drop, "완전매칭": complete,
                       "풀포함": bool(in_slot and (complete or partial)),
                       "미매칭재료": ", ".join(missing), "DB없음재료": ", ".join(nodb)})
        if not in_slot or not (complete or partial):
            continue
        vals = {k: round(x, 2) for k, x in tot.items()}
        vals.update(cost=round(cost), weight=round(weight, 1), sodium_seasoning=round(na_season, 2))
        pool[cat].append({
            "category": cat, "menu_name": name, "menu_code": code, **vals,
            "caution_ingredients": sorted({i for i in ings if i in CAUTION_INGREDIENTS}),
            "_raw": dict(vals), "sodium_raw": vals["sodium"], "portion": 1.0,
            "ingredients": {k: round(x, 2) for k, x in ings.items()},
            "ingredient_ids": ids,
            "cost_complete": priced_all,
            # 한 그릇 음식·다진찬 적합도 자동 분류 (meal_policy.json 영양사 판정이 있으면 그쪽이 우선)
            "policy_auto": meal_policy_auto.classify(cat, name, first[R_COL["method"]], first[R_COL["mid"]]),
            **({"missing_ingredients": missing + nodb} if (missing or nodb) else {}),
        })

    # 같은 음식명이 여러 코드로 있으면 첫 번째만 (기존 시스템은 음식명을 키로 씀)
    for cat in pool:
        seen, uniq = set(), []
        for m in pool[cat]:
            if m["menu_name"] not in seen:
                seen.add(m["menu_name"])
                uniq.append(m)
        pool[cat] = uniq

    rep = pd.DataFrame(report)
    miss = pd.DataFrame([{"식품코드": fc,
                          "DB 구분": {"P": "가공식품", "D": "음식", "R": "원재료성"}.get(fc[:1], "기타"),
                          "원재료명(예)": ", ".join(k for k, _ in miss_names[fc].most_common(3)),
                          "레시피 행 수": n, "영향 메뉴 수": len(miss_menus[fc])}
                         for fc, n in miss_rows.most_common()])
    return pool, rep, miss


def default_paths(recipes: str | None = None, category_from: str | None = None,
                  nutrients: list[str] | None = None) -> dict:
    """기본 입력 파일 위치 — 파이프라인(ensure_pool)과 명령줄이 같은 규칙을 쓴다"""
    _d = lambda f: os.path.join(DATA_DIR, f)
    if recipes is None:
        recipes = _d("recipes_v1.csv") if os.path.exists(_d("recipes_v1.csv")) else _d("recipes.csv")
    if category_from is None:
        cand = [f for f in (_d("recipes_v0.csv"), _d("recipes.csv"))
                if os.path.exists(f) and os.path.abspath(f) != os.path.abspath(recipes)]
        category_from = cand[0] if cand else ""
    if not nutrients:
        nutrients = ([p for p in [_d("nutrient.csv")] if os.path.exists(p)]
                     + sorted(glob.glob(_d(os.path.join("nutrients", "*.csv")))
                              + glob.glob(_d(os.path.join("nutrients", "*.csv.gz")))))
    return {"recipes": recipes, "category_from": category_from, "nutrients": nutrients,
            "prices": _d("ingredient_prices.json")}


def _sources(paths: dict) -> list[str]:
    return [p for p in [paths["recipes"], paths["category_from"], paths["prices"], os.path.abspath(__file__),
                        os.path.join(HERE, "meal_policy_auto.py"), *paths["nutrients"]] if p and os.path.exists(p)]


_MD5_CACHE: dict = {}


def _md5(path: str) -> str:
    import hashlib
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key not in _MD5_CACHE:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _MD5_CACHE[key] = h.hexdigest()
    return _MD5_CACHE[key]


def source_signature(paths: dict) -> dict:
    """입력 파일 내용 서명 {파일명: md5} — git clone 처럼 수정 시각만 바뀐 경우에는 다시 만들지 않기 위함"""
    return {os.path.basename(p): _md5(p) for p in _sources(paths)}


def _sig_path(out: str) -> str:
    return out + ".sig"


def is_stale(out: str, paths: dict) -> bool:
    """out(pool.json)이 없거나, 입력 파일(레시피·영양 DB·가격·이 스크립트·자동 분류 규칙) 내용이 바뀌었으면 True.
    서명 파일(pool.json.sig)이 없으면 수정 시각으로 판단한다."""
    if not os.path.exists(out):
        return True
    sig = _sig_path(out)
    if os.path.exists(sig):
        try:
            return json.load(open(sig, encoding="utf-8")) != source_signature(paths)
        except (ValueError, OSError):
            pass
    t = os.path.getmtime(out)
    return any(os.path.getmtime(p) > t for p in _sources(paths))


def write_signature(out: str, paths: dict) -> None:
    json.dump(source_signature(paths), open(_sig_path(out), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def rebuild(out: str = os.path.join(DATA_DIR, "pool.json"), paths: dict | None = None,
            report: str = os.path.join(DATA_DIR, "pool_coverage.csv"), verbose: bool = True,
            strict_nodb: bool = False, one_bowl: bool = False, partial: bool = False) -> dict:
    paths = paths or default_paths()
    if not paths["nutrients"]:
        raise FileNotFoundError("영양 DB 파일이 없습니다: data/nutrient.csv 또는 data/nutrients/*.csv(.gz)")
    if verbose:
        print(f"레시피: {os.path.basename(paths['recipes'])} / 기존 구분 참조: "
              f"{os.path.basename(paths['category_from']) or '없음'}")
    pool, rep, miss = build(paths["recipes"], paths["nutrients"], paths["prices"], strict_nodb, one_bowl,
                            partial, paths["category_from"] or None)
    tmp = out + ".tmp"
    json.dump(pool, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, out)                                   # 쓰는 도중 읽히지 않도록 한 번에 교체
    write_signature(out, paths)
    rep.to_csv(report, index=False, encoding="utf-8-sig")
    miss_path = os.path.splitext(report)[0] + "_missing_codes.csv"
    miss.to_csv(miss_path, index=False, encoding="utf-8-sig")
    if verbose:
        print(f"\n음식 {len(rep):,}개 중 완전 매칭 {int(rep['완전매칭'].sum()):,}개")
        ex = rep[rep["제외사유"] != ""]
        if len(ex):
            print("급식 부적합·장류 제외:", ex["제외사유"].value_counts().to_dict())
        print("풀 메뉴 수:", {c: len(v) for c, v in pool.items()})
        print(f"→ {out}\n→ {report}\n→ {miss_path} (미매칭 식품코드 {len(miss):,}개, 많이 쓰이는 순)")
        if len(miss):
            print("미매칭 식품코드 DB 구분:", miss["DB 구분"].value_counts().to_dict())
    return pool


def main():
    ap = argparse.ArgumentParser(description="레시피 DB × 영양 DB → pool.json (식단 설계 후보 풀)")
    ap.add_argument("--recipes", default=None,
                    help="레시피 DB (기본: data/recipes_v1.csv, 없으면 data/recipes.csv)")
    ap.add_argument("--nutrients", nargs="*", default=None,
                    help="영양 DB CSV (기본: data/nutrient.csv + data/nutrients/*.csv(.gz))")
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "pool.json"))
    ap.add_argument("--report", default=os.path.join(DATA_DIR, "pool_coverage.csv"))
    ap.add_argument("--category-from", default=None,
                    help="이 파일에 있는 메뉴는 그 파일의 '구분'을 따른다 "
                         "(기본: 기존 레시피 data/recipes_v0.csv, 없으면 data/recipes.csv; 끄려면 '')")
    ap.add_argument("--strict-nodb", action="store_true", help="식품코드 'DB 없음' 재료가 있는 메뉴도 제외")
    ap.add_argument("--one-bowl", action="store_true", help="밥 칸에 덮밥·볶음밥·면·죽·빵도 포함")
    ap.add_argument("--partial", action="store_true", help="일부 재료만 매칭된 메뉴도 포함 (영양 과소평가 주의)")
    a = ap.parse_args()
    paths = default_paths(a.recipes, a.category_from, a.nutrients)
    rebuild(a.out, paths, a.report, True, a.strict_nodb, a.one_bowl, a.partial)


if __name__ == "__main__":
    main()
