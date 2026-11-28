# -*- coding: utf-8 -*-
"""판정 모델 학습 (사람이 확인한 O/X → 로지스틱 회귀).

    python -m mapping.train                       # 학습세트·평가세트 엑셀의 O/X + 검수 화면 승인·거절
    python -m mapping.train --with-llm 0.3        # LLM 판정도 가중치 0.3 으로 섞기 (사람 라벨이 적을 때)
    python -m mapping.train --dry-run             # 성능만 보고 저장하지 않음

· 특징: judge.vectorize (이름 관계·유사도·가공품·상태·분류·가격·부위 … 22개). 매핑 표(features)에 저장된 값을 그대로 쓴다.
· 평가: 식재료 단위로 나눈 5겹 교차검증 (같은 식재료가 학습·검증에 동시에 들어가지 않게).
· 기준: 교차검증 확률로 자동 승인 정밀도 98% 이상이 되는 가장 낮은 확률을 찾는다.
· 저장: 같은 라벨에서 규칙보다 자동 승인을 더 많이 하면서 정밀도 98%를 지킬 때만 models/judge_latest.json 저장
        → 다음 실행부터 run 이 자동으로 모델을 쓴다 (확정 불일치 규칙은 그대로).
"""
import argparse
import json
import os
from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from .judge import FEATURE_ORDER, gates, hard_reject, rule_score, vectorize
from .store import open_store

import glob as _glob
LABEL_FILES = ([os.path.join(C.HERE, "eval", "학습세트_라벨링.xlsx"), os.path.join(C.HERE, "eval", "평가세트_라벨링.xlsx")]
               + sorted(_glob.glob(os.path.join(C.HERE, "eval", "가격상품확인_*.xlsx"))))
KEY = ["ingredient_id", "supplier", "item_cd"]
SUP = {"현대그린푸드": "hgreenfood", "사조푸디스트": "sajo", "hgreenfood": "hgreenfood", "sajo": "sajo"}


def read_labels(paths) -> pd.DataFrame:
    frames = []
    for p in paths:
        if not os.path.exists(p):
            continue
        d = pd.read_excel(p, sheet_name="라벨", dtype={"단품코드": str})
        sup_col = "supplier" if "supplier" in d.columns else "공급사"
        lab = d["정답(O/X)"].astype(str).str.strip().str.upper()
        d = d.assign(y=lab.map({"O": 1, "X": 0}), ingredient_id=d["식재료ID"], supplier=d[sup_col].map(SUP),
                     item_cd=d["단품코드"].astype(str), source=os.path.basename(p), weight=1.0)
        frames.append(d.dropna(subset=["y"])[KEY + ["y", "source", "weight"]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=KEY + ["y", "source", "weight"])


def collect(store, with_llm: float = 0.0) -> pd.DataFrame:
    mp = store.load_map()
    mp["item_cd"] = mp["item_cd"].astype(str)
    lab = read_labels(LABEL_FILES)
    human = mp[mp["status"].isin(["approved", "rejected"])]
    lab = pd.concat([lab, pd.DataFrame({**{k: human[k] for k in KEY}, "y": (human["status"] == "approved").astype(int),
                                        "source": "검수화면", "weight": 1.0})], ignore_index=True)
    if with_llm > 0:
        llm = mp[(mp["method"] == "llm") & mp["status"].isin(["auto_approved", "auto_rejected"])]
        lab = pd.concat([lab, pd.DataFrame({**{k: llm[k] for k in KEY}, "y": (llm["status"] == "auto_approved").astype(int),
                                            "source": "LLM", "weight": with_llm})], ignore_index=True)
    lab["y"] = lab["y"].astype(int)
    # 같은 쌍이 여러 곳에 있으면 사람 라벨 우선 (가중치 큰 것), 마지막 것
    lab = lab.sort_values("weight").drop_duplicates(KEY, keep="last")
    d = lab.merge(mp[KEY + ["features", "status"]], on=KEY, how="inner")
    d["features"] = d["features"].map(lambda f: f if isinstance(f, dict) else json.loads(f or "{}"))
    return d


def rule_baseline(d: pd.DataFrame) -> dict:
    """같은 라벨에서 지금 규칙의 자동 승인 성능."""
    auto = d["features"].map(lambda f: not hard_reject(f) and not gates(f) and rule_score(f) >= C.AUTO_APPROVE)
    n = int(auto.sum())
    return {"auto_n": n, "precision": round(float(d.loc[auto, "y"].mean()), 4) if n else None,
            "share_of_pos": round(float(d.loc[auto, "y"].sum() / max(d["y"].sum(), 1)), 4)}


def fit(d: pd.DataFrame, target: float = C.TARGET_PRECISION) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    X = np.array([vectorize(f) for f in d["features"]], float)
    y = d["y"].to_numpy(int)
    w = d["weight"].to_numpy(float)
    groups = d["ingredient_id"].to_numpy()
    eligible = d["features"].map(lambda f: not hard_reject(f)).to_numpy()   # 확정 불일치는 모델이 있어도 거절
    k = min(5, len(set(groups)))
    p = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        clf = LogisticRegression(max_iter=3000, C=1.0, class_weight="balanced")
        clf.fit(X[tr], y[tr], sample_weight=w[tr])
        p[te] = clf.predict_proba(X[te])[:, 1]
    human = d["source"].ne("LLM").to_numpy()           # 성능은 사람 라벨로만 잰다
    auc = roc_auc_score(y[human], p[human]) if len(set(y[human])) > 1 else None
    curve, best = [], None
    for t in np.arange(0.50, 0.995, 0.005):
        sel = human & eligible & (p >= t)
        if sel.sum() < 10:
            continue
        prec = float(y[sel].mean())
        share = float(y[sel].sum() / max(y[human].sum(), 1))
        curve.append((round(float(t), 3), int(sel.sum()), round(prec, 4), round(share, 4)))
        if prec >= target and (best is None or share > best["share_of_pos"]):
            best = {"approve_at": round(float(t), 3), "auto_n": int(sel.sum()), "precision": round(prec, 4),
                    "share_of_pos": round(share, 4)}
    reject_below = 0.10
    for t in np.arange(0.05, 0.5, 0.01):
        sel = human & (p < t)
        if sel.sum() >= 10 and (1 - y[sel].mean()) >= target:
            reject_below = round(float(t), 2)
    clf = LogisticRegression(max_iter=3000, C=1.0, class_weight="balanced").fit(X, y, sample_weight=w)
    coef = dict(sorted(((k, float(v)) for k, v in zip(FEATURE_ORDER, clf.coef_[0].round(3))), key=lambda x: -abs(x[1])))
    return {"auc_cv": round(float(auc), 4) if auc else None, "best": best, "reject_below": reject_below,
            "coef": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0]), "top_features": dict(list(coef.items())[:8]),
            "curve": curve}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--with-llm", type=float, default=0.0, help="LLM 판정을 이 가중치로 섞음 (0 = 안 씀)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    d = collect(open_store(a.store), a.with_llm)
    hum = d[d["source"] != "LLM"]
    print(f"라벨 {len(d):,}쌍 (사람 {len(hum):,} = O {int(hum['y'].sum()):,} / X {int((1 - hum['y']).sum()):,}, "
          f"식재료 {d['ingredient_id'].nunique()}개) · 출처 {d['source'].value_counts().to_dict()}")
    if len(hum) < C.MIN_LABELS_FOR_MODEL or hum["y"].nunique() < 2:
        print(f"아직 학습하지 않음: 사람 라벨이 {C.MIN_LABELS_FOR_MODEL}쌍 이상, O·X 둘 다 있어야 합니다.")
        return 1
    base = rule_baseline(hum)
    res = fit(d)
    best = res["best"]
    print(f"\n[지금 규칙]  자동 승인 {base['auto_n']}쌍, 정밀도 {base['precision']}, 정답 중 자동 승인 {base['share_of_pos']}")
    if best:
        print(f"[학습 모델]  확률 {best['approve_at']} 이상 자동 승인 → {best['auto_n']}쌍, 정밀도 {best['precision']}, "
              f"정답 중 자동 승인 {best['share_of_pos']}  (식재료 단위 교차검증, AUC {res['auc_cv']})")
    else:
        print(f"[학습 모델]  정밀도 {C.TARGET_PRECISION} 를 만족하는 기준이 없음 (AUC {res['auc_cv']}) — 라벨을 더 모아 주세요.")
    print("영향 큰 특징:", res["top_features"])

    rule_ok = base["precision"] is not None and base["precision"] >= C.TARGET_PRECISION
    better = best is not None and (not rule_ok or best["share_of_pos"] > base["share_of_pos"])
    report = {"date": str(date.today()), "labels": int(len(d)), "human": int(len(hum)), "rule": base,
              "model": {k: v for k, v in res.items() if k not in ("coef", "intercept")}, "saved": False}
    if better and not a.dry_run:
        version = f"lr-{date.today():%Y%m%d}-{len(hum)}"
        m = {"version": version, "coef": res["coef"], "intercept": res["intercept"],
             "approve_at": best["approve_at"], "reject_below": res["reject_below"]}
        os.makedirs(C.MODEL_DIR, exist_ok=True)
        for name in (f"judge_{version}.json", "judge_latest.json"):
            json.dump(m, open(os.path.join(C.MODEL_DIR, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        report["saved"] = version
        print(f"\n저장: models/judge_latest.json ({version}) — 다음 실행부터 사용. "
              f"이미 판정한 상품에 적용하려면: python -m mapping.run --full --no-llm --graph (사람·LLM 판정은 유지)")
    elif not better:
        print("\n규칙보다 낫지 않아 저장하지 않았습니다 (규칙을 그대로 씁니다).")
    os.makedirs(os.path.join(C.HERE, "eval"), exist_ok=True)
    json.dump(report, open(os.path.join(C.HERE, "eval", f"학습결과_{date.today()}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
