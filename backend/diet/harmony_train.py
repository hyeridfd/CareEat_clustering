# -*- coding: utf-8 -*-
"""조화 점수 학습 — 요양원 실제 식단표(국·주찬·부찬1·부찬2) = 좋은 조합, 칸을 섞은 한 끼 = 비교 대상

  실행:  python -m diet.harmony_train                       (data/harmony/*_menus.json 전부 = 여러 시설)
         python -m diet.harmony_train a_menus.json b_menus.json   (지정한 시설만)
  입력:  시설별 JSON (diet.harmony_parse 로 엑셀 → JSON)
         {facility, meals:[{date, meal, 밥, 국, 주찬, 부찬1, 부찬2, 김치}], menus:{메뉴: {food_id…}}, ingredients:{메뉴: {재료: {g, id}}}}
  출력:  data/harmony/harmony_model.json  (가중치 · 검증 결과 · 특징군 비교)

  · 음성 예시 2종 (실제 한 끼 1개당 각 3개)
      ① 네 칸 모두 무작위 (칸별 실제 출현 빈도대로) — 실제 식단에 있는 조합과 똑같으면 다시 뽑음
      ② 한 칸만 바꿈 — 원래 메뉴는 후보에서 제외
    → 칸별 인기도는 같고 '조합'만 다르므로, 모델은 조합 자체를 배운다
  · 데이터 분할 (날짜순): 학습 60% · 검증 20%(규제 강도 C 선택) · 시험 20%(최종 성능, 한 번만)
      C 선택 후 학습+검증으로 다시 학습 → 시험으로 평가.  서비스용 모델은 같은 C 로 전체 데이터 학습.
  · 지표: AUC (실제 vs 섞은 한 끼), Swap Top-1 = 빈칸 채우기(FITB) — 한 칸을 바꾼 후보 9개 + 실제 1개 중 실제가 1등인 비율
  · 특징군 비교 (A 조합 · B 한 끼 구성 · C 끼니 적합도 · D 전체) 를 같은 절차로 학습·평가해 함께 저장
  · 여러 시설: 음성 예시·빈칸 후보는 같은 시설 메뉴로만 만듦 (시설 차이를 '조합'으로 배우지 않게)
      분할은 시설마다 자기 날짜로 60/20/20 후 합침.
      시설 비교(facility_eval): 시설마다 ① 자기 시설만 학습 ② 모든 시설 학습 ③ 다른 시설만 학습(처음 보는 시설)
      → 그 시설 시험 구간(마지막 20%)으로 평가
"""
from __future__ import annotations

import glob
import json
import os
import random
import sys
from collections import Counter

import numpy as np

from .harmony import (DATA_DIR, FEATURE_SETS, HARMONY_SCHEMA, MODEL_JSON, build_canon, meal_features, menu_attrs,
                      set_canon)

NEG_RANDOM, NEG_SWAP = 3, 3
STYLE_KEYS = (("국", "soup"), ("주찬", "method"), ("주찬", "main"), ("부찬", "method"), ("부찬", "main"))
SEED = 7
C_GRID = (0.01, 0.02, 0.05, 0.1, 0.3)
FITB_CANDS = 9
DEPLOY_SET = "D_전체"


def load(paths):
    """시설 JSON 1개 또는 여러 개 → (시설 이름들, 끼니, 메뉴 속성 함수). 끼니마다 m["facility"]"""
    if isinstance(paths, str):
        paths = [paths]
    menus, ings, meals, facs = {}, {}, [], []
    for path in paths:
        d = json.load(open(path, encoding="utf-8"))
        fac = d.get("facility") or os.path.basename(path).split("_")[0]
        facs.append(fac)
        for k, v in (d.get("menus") or {}).items():
            menus.setdefault(k, v)                 # 같은 메뉴 이름은 먼저 읽은 시설 기준
        for k, v in (d.get("ingredients") or {}).items():
            ings.setdefault(k, v)
        meals += [dict(m, facility=fac) for m in d["meals"] if all(m.get(s) for s in ("국", "주찬", "부찬1", "부찬2"))]
    # 재료명 표준화 표: 식단표들의 재료코드 + 레시피 DB(recipes.csv)의 식품코드
    pairs = [(nm, (v or {}).get("id")) for d_ in ings.values() for nm, v in d_.items()]
    try:
        import pandas as pd
        r = pd.read_csv(os.path.join(DATA_DIR, "recipes.csv"), usecols=["원재료명", "식품코드"])
        pairs += list(zip(r["원재료명"].astype(str), r["식품코드"].astype(str)))
    except Exception:
        pass
    canon = build_canon(pairs)
    set_canon(canon)
    cache = {}

    def attr(n):
        if n not in cache:
            cache[n] = menu_attrs(n, (menus.get(n) or {}).get("food_id"),
                                  {k: (v or {}).get("g") for k, v in (ings.get(n) or {}).items()})
        return cache[n]
    meals.sort(key=lambda m: (m["facility"], m["date"], {"아침": 0, "점심": 1, "저녁": 2}[m["meal"]]))
    attr.canon = canon
    return facs, meals, attr


def _by_fac(meals):
    out = {}
    for m in meals:
        out.setdefault(m.get("facility", ""), []).append(m)
    return out


def split(meals, a=0.6, b=0.8):
    """시설마다 자기 날짜 순서로 학습 a · 검증 b−a · 시험 1−b 로 나눠 합침 → (tr, va, te, 시설별 구간)"""
    tr, va, te, info = [], [], [], {}
    for fac, ms in _by_fac(meals).items():
        dates = sorted({m["date"] for m in ms})
        c1, c2 = dates[int(len(dates) * a)], dates[int(len(dates) * b)]
        t_, v_, e_ = ([m for m in ms if m["date"] < c1], [m for m in ms if c1 <= m["date"] < c2],
                      [m for m in ms if m["date"] >= c2])
        tr += t_; va += v_; te += e_
        info[fac] = {"train": [dates[0], c1], "validation": [c1, c2], "test": [c2, dates[-1]],
                     "n": [len(t_), len(v_), len(e_)]}
    return tr, va, te, info


def _q(m):
    return (m["국"], m["주찬"], m["부찬1"], m["부찬2"])


def _pools(meals):
    return [[m["국"] for m in meals], [m["주찬"] for m in meals], [m["부찬1"] for m in meals] + [m["부찬2"] for m in meals]]


def _swap(q, k, pool, rng, real):
    """한 칸(k)을 바꾼 한 끼 — 원래 메뉴·실제 식단과 같은 조합은 제외. 만들 수 없으면 None"""
    cands = [x for x in pool if x != q[k]]
    for _ in range(20):
        if not cands:
            return None
        r = list(q)
        r[k] = rng.choice(cands)
        if tuple(r) not in real:
            return tuple(r)
    return None


def _random(pools, rng, real):
    for _ in range(20):
        r = (rng.choice(pools[0]), rng.choice(pools[1]), rng.choice(pools[2]), rng.choice(pools[2]))
        if r not in real:
            return r
    return None


def examples(meals, attr, rng, real, fs):
    """→ (특징 목록들, 정답). real = 실제 식단 조합 집합 (음성 예시에서 제외). 음성 예시는 같은 시설 메뉴로만"""
    X, y = [], []
    for ms in _by_fac(meals).values():
        X_, y_ = _examples_one(ms, attr, rng, real, fs)
        X += X_; y += y_
    return X, y


def _examples_one(meals, attr, rng, real, fs):
    pools = _pools(meals)
    X, y = [], []
    feat = lambda q, ml: meal_features(*[attr(x) for x in q], ml, **fs)
    for m in meals:
        q, ml = _q(m), m["meal"]
        X.append(feat(q, ml)); y.append(1)
        for _ in range(NEG_RANDOM):
            r = _random(pools, rng, real)
            if r:
                X.append(feat(r, ml)); y.append(0)
        for _ in range(NEG_SWAP):
            k = rng.randrange(4)
            r = _swap(q, k, pools[min(k, 2)], rng, real)
            if r:
                X.append(feat(r, ml)); y.append(0)
    return X, y


def fit(X, y, C):
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    dv = DictVectorizer()
    A = dv.fit_transform([dict.fromkeys(f, 1) for f in X])
    lr = LogisticRegression(C=C, max_iter=3000, class_weight="balanced")
    lr.fit(A, y)
    return dv, lr


def _proba(dv, lr, X):
    return lr.predict_proba(dv.transform([dict.fromkeys(f, 1) for f in X]))[:, 1]


def fitb(dv, lr, meals, attr, real, fs, seed):
    """빈칸 채우기: 끼니마다 네 칸 각각 → 실제 메뉴 1개 + 다른 메뉴 9개(서로 다름) 중 실제가 1등인 비율 (동점은 나눠 셈)"""
    rng = random.Random(seed)
    pools_by = {f: _pools(ms) for f, ms in _by_fac(meals).items()}    # 후보는 같은 시설 메뉴
    W = dict(zip(dv.get_feature_names_out(), lr.coef_[0]))
    score = lambda q, ml: sum(W.get(k, 0.0) for k in meal_features(*[attr(x) for x in q], ml, **fs))
    hit = tot = 0
    for m in meals:
        q, ml = _q(m), m["meal"]
        pools = pools_by[m.get("facility", "")]
        for k in range(4):
            # 후보: 원래 메뉴 제외 + 바꾼 조합이 실제 식단(다른 날)에 있는 조합이면 제외 (음성 예시와 같은 규칙)
            pool = sorted({x for x in pools[min(k, 2)] if x != q[k] and (q[:k] + (x,) + q[k + 1:]) not in real})
            if len(pool) < FITB_CANDS:
                continue
            others = rng.sample(pool, FITB_CANDS)
            cands = [q] + [q[:k] + (o,) + q[k + 1:] for o in others]
            s = [score(c, ml) for c in cands]
            top = max(s)
            if s[0] >= top:                                  # 동점이면 나눠서 (동점 k개 → 1/k), 정보가 없으면 우연 수준 0.1
                hit += 1 / sum(1 for v in s if v == top)
            tot += 1
    return round(hit / tot, 3) if tot else None


def run_set(name, fs, tr, va, te, attr, real):
    """특징군 하나: 학습으로 C 후보별 모델 → 검증 AUC 로 C 선택 → 학습+검증 재학습 → 시험 평가(한 번)"""
    from sklearn.metrics import roc_auc_score
    rng = random.Random(SEED)
    Xtr, ytr = examples(tr, attr, rng, real, fs)
    Xva, yva = examples(va, attr, rng, real, fs)
    by_c = {}
    for C in C_GRID:
        dv, lr = fit(Xtr, ytr, C)
        by_c[C] = roc_auc_score(yva, _proba(dv, lr, Xva))
    C = max(by_c, key=by_c.get)
    Xtv, ytv = examples(tr + va, attr, random.Random(SEED + 1), real, fs)
    Xte, yte = examples(te, attr, random.Random(SEED + 2), real, fs)
    dv, lr = fit(Xtv, ytv, C)
    auc = roc_auc_score(yte, _proba(dv, lr, Xte))
    return {"set": name, "C": C, "val_auc_by_C": {str(k): round(v, 3) for k, v in by_c.items()},
            "test_auc": round(auc, 3), "test_swap_top1": fitb(dv, lr, te, attr, real, fs, SEED + 3),
            "swap_chance": round(1 / (FITB_CANDS + 1), 3), "n_features": len(dv.vocabulary_)}


def _eval(tr, te, attr, real, fs, C, seed=SEED):
    from sklearn.metrics import roc_auc_score
    Xtr, ytr = examples(tr, attr, random.Random(seed + 1), real, fs)
    Xte, yte = examples(te, attr, random.Random(seed + 2), real, fs)
    dv, lr = fit(Xtr, ytr, C)
    return {"auc": round(roc_auc_score(yte, _proba(dv, lr, Xte)), 3),
            "swap_top1": fitb(dv, lr, te, attr, real, fs, seed + 3), "n_train": len(tr), "n_test": len(te)}


def facility_eval(tr, va, te, attr, real, fs, C):
    """시설마다 같은 시험 구간(그 시설 마지막 20%)으로: 자기 시설만 / 전체 시설 / 다른 시설만(처음 보는 시설) 학습"""
    out = {}
    trv = tr + va
    for fac, te_f in _by_fac(te).items():
        own = [m for m in trv if m["facility"] == fac]
        other = [m for m in trv + te if m["facility"] != fac]
        out[fac] = {"자기 시설만": _eval(own, te_f, attr, real, fs, C),
                    "전체 시설": _eval(trv, te_f, attr, real, fs, C)}
        if other:
            out[fac]["다른 시설만"] = _eval(other, te_f, attr, real, fs, C)
    return out


def _style(meals, attr):
    return {ml: {f"{role}.{key}": dict(Counter(str(attr(m[s_]).get(key)) for m in meals if m["meal"] == ml
                                              for s_ in ((role,) if role != "부찬" else ("부찬1", "부찬2"))))
                 for role, key in STYLE_KEYS} for ml in ("아침", "점심", "저녁")}


def main(paths, out=MODEL_JSON):
    facs, meals, attr = load(paths)
    tr, va, te, split_info = split(meals)
    real = {_q(m) for m in meals}
    dates = sorted({m["date"] for m in meals})
    print(f"시설 {len(facs)}곳: " + " · ".join(f"{f} {len(ms)}끼" for f, ms in _by_fac(meals).items()))

    ablation = [run_set(n, fs, tr, va, te, attr, real) for n, fs in FEATURE_SETS.items()]
    for r in ablation:
        print(f"{r['set']:8s} C={r['C']:<5} test AUC {r['test_auc']:.3f}  Swap Top-1 {r['test_swap_top1']}  ({r['n_features']}개 특징)")
    best = next(r for r in ablation if r["set"] == DEPLOY_SET)
    fac_eval = facility_eval(tr, va, te, attr, real, FEATURE_SETS[DEPLOY_SET], best["C"]) if len(facs) > 1 else {}
    for f, r in fac_eval.items():
        print(f"  [{f} 시험] " + " · ".join(f"{k}: AUC {v['auc']:.3f} Swap {v['swap_top1']}" for k, v in r.items()))

    # 서비스용: 같은 C 로 전체 데이터 학습
    fs = FEATURE_SETS[DEPLOY_SET]
    Xa, ya = examples(meals, attr, random.Random(SEED), real, fs)
    dv, lr = fit(Xa, ya, best["C"])
    W = {k: round(float(v), 4) for k, v in zip(dv.get_feature_names_out(), lr.coef_[0]) if abs(v) >= 0.01}
    bF = float(lr.intercept_[0])
    prob = lambda q, ml: 1 / (1 + np.exp(-(bF + sum(W.get(k, 0.0) for k in meal_features(*[attr(x) for x in q], ml, **fs)))))
    rr = random.Random(SEED + 9)
    real_mean = float(np.mean([prob(_q(m), m["meal"]) for m in meals]))
    rand = []
    for ms in _by_fac(meals).values():
        pools = _pools(ms)
        k = round(3000 * len(ms) / len(meals))
        rand += [prob(_random(pools, rr, real), rr.choice(["아침", "점심", "저녁"])) for _ in range(k)]
    rand_mean = float(np.mean(rand))
    top = sorted(W.items(), key=lambda t: -t[1])
    import datetime as _dt
    model = {
        "schema": HARMONY_SCHEMA, "trained_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": [os.path.abspath(p) for p in ([paths] if isinstance(paths, str) else paths)],
        "ingredient_canon": attr.canon,
        "facility": " · ".join(facs), "facilities": {f: len(ms) for f, ms in _by_fac(meals).items()},
        "n_meals": len(meals), "period": [dates[0], dates[-1]], "feature_set": DEPLOY_SET,
        "feature_flags": fs, "C": best["C"], "bias": round(bF, 4), "weights": W,
        "ref_real_mean": round(real_mean, 3), "ref_random_mean": round(rand_mean, 3),
        "split": {"by_facility": split_info, "n": [len(tr), len(va), len(te)]},
        "validation": {"auc": best["test_auc"], "swap_top1": best["test_swap_top1"], "swap_chance": best["swap_chance"],
                       "note": "시설마다 시험 구간(마지막 20%) 평가 · C 는 검증 구간에서 선택"},
        "ablation": ablation,
        "facility_eval": fac_eval,
        "top_positive": top[:25], "top_negative": top[-25:][::-1],
        # 시설 스타일 유사도 기준: 학습한 시설 전체를 합친 분포 (시설별 분포도 함께 저장)
        "style": _style(meals, attr),
        "style_by_facility": {f: _style(ms, attr) for f, ms in _by_fac(meals).items()},
        "attr_counts": {k: Counter(str(attr(m[s]).get(k)) for m in meals for s in ("국", "주찬", "부찬1", "부찬2")).most_common(20)
                        for k in ("method", "main", "season", "main_ingredient")},
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(model, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: {os.path.abspath(out)}  (스키마 {HARMONY_SCHEMA} · 재료 표준화 {len(attr.canon)}개 · 서비스 모델 {DEPLOY_SET})")
    # 서비스 코드가 읽는 경로와 같은지 확인
    from . import harmony as _h
    _h._MODEL = None
    chk = _h.load_model()
    print(f"서비스용 경로 확인: {chk.get('path')} · 학습 시각 {chk.get('trained_at')} · AUC {chk.get('validation', {}).get('auc')}")
    return model


if __name__ == "__main__":
    main(sys.argv[1:] or sorted(glob.glob(os.path.join(os.path.dirname(MODEL_JSON), "*_menus.json"))))
