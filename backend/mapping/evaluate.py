# -*- coding: utf-8 -*-
"""평가 스크립트.

    python -m mapping.evaluate --labels mapping/eval/평가세트_라벨링.xlsx --store local
    python -m mapping.evaluate --labels … --tune        # 자동 승인 정밀도 98% 기준 점수 찾기
    python -m mapping.evaluate --reviews                # 평가 세트 대신 사람 검수 결과(approved/rejected)로 평가

지표 (인계서 7장)
  후보 찾기   : 정답 상품이 식재료 후보에 들어 있는 비율 (라벨 O + '누락' 시트 기준)   목표 95% 이상
  판정        : 자동 승인 정밀도 (목표 98% 이상), 자동 승인 비율 (정답 중 자동 승인된 비율)
  결과        : 사용 중량 기준 가격 연결률 (목표 90% 이상), 공급사·상품 선택이 맞는 비율 (정답 중 가장 싼 것을 골랐는지)
  운영        : 하루 신규 상품 수, 검수 대기열, LLM 호출 수 — mapping/_reports/*.json 에서
결과는 mapping/eval/평가결과_<날짜>.md 로 저장한다.
"""
import argparse
import glob
import json
import os
from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from .judge import rule_score
from .sources import load_ingredients
from .store import open_store

APPROVED = {"auto_approved", "approved"}


def load_labels(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    lab = pd.read_excel(path, sheet_name="라벨", dtype={"단품코드": str})
    lab["정답"] = lab["정답(O/X)"].astype(str).str.strip().str.upper().map({"O": 1, "X": 0, "0": 1, "1": 1})
    lab.loc[lab["정답(O/X)"].astype(str).str.strip().str.upper() == "X", "정답"] = 0
    lab = lab.dropna(subset=["정답"])
    try:
        miss = pd.read_excel(path, sheet_name="누락", dtype={"단품코드": str}).dropna(subset=["단품코드"])
    except ValueError:
        miss = pd.DataFrame(columns=["식재료ID", "공급사", "단품코드"])
    return lab, miss


def evaluate(lab: pd.DataFrame, miss: pd.DataFrame, mp: pd.DataFrame, daily: pd.DataFrame, ings) -> dict:
    key = ["식재료ID", "공급사", "단품코드"]
    m = mp.rename(columns={"ingredient_id": "식재료ID", "supplier": "공급사", "item_cd": "단품코드"})
    m["단품코드"] = m["단품코드"].astype(str)
    d = lab.merge(m[key + ["status", "score", "features"]], on=key, how="left")
    pos, neg = d[d["정답"] == 1], d[d["정답"] == 0]
    res = {"labeled_pairs": int(len(d)), "positives": int(len(pos)), "negatives": int(len(neg)),
           "ingredients": int(d["식재료ID"].nunique())}

    # 후보 찾기: 정답 중 후보로 판단된(=매핑 표에 있는) 비율. 누락 시트의 상품은 후보에 없던 정답.
    found = int(pos["status"].notna().sum())
    res["candidate_recall"] = round(found / max(found + len(miss), 1), 4)

    # 판정
    auto = d[d["status"] == "auto_approved"]
    res["auto_approved"] = int(len(auto))
    res["auto_precision"] = round(float(auto["정답"].mean()), 4) if len(auto) else None
    res["auto_approve_share_of_positives"] = round(float((pos["status"] == "auto_approved").mean()), 4) if len(pos) else None
    rej = d[d["status"] == "auto_rejected"]
    res["auto_reject_npv"] = round(float(1 - rej["정답"].mean()), 4) if len(rej) else None
    res["pending_share"] = round(float((d["status"] == "pending").mean()), 4) if len(d) else None
    wrong = auto[auto["정답"] == 0]
    res["false_auto_approvals"] = [
        {"식재료": r.get("대표 원재료명"), "상품": r.get("상품명"), "근거": (r.get("features") or {}).get("rel")}
        for r in wrong.head(30).to_dict("records")]

    # 결과: 가격 연결률 (사용 중량)
    from .pricing import coverage
    last_day = daily["price_date"].max() if len(daily) else None
    if last_day is not None:
        res["price_date"] = str(last_day)
        res["coverage"] = coverage(daily[daily["price_date"] == last_day].to_dict("records"), ings)
        # 선택 정확도: 라벨 O 상품 중 가장 싼 것 vs 시스템 선택
        today = daily[daily["price_date"] == last_day].set_index("ingredient_id")
        ok = tot = 0
        for iid, g in pos.groupby("식재료ID"):
            g = g.dropna(subset=["원/kg"])
            if g.empty or iid not in today.index or pd.isna(today.loc[iid, "price_per_g"]):
                continue
            tot += 1
            best = g["원/kg"].min()
            chosen = float(today.loc[iid, "price_per_g"]) * 1000
            ok += int(chosen <= best * 1.01 and str(today.loc[iid, "item_cd"]) in set(g["단품코드"].astype(str)))
        res["selection_accuracy"] = round(ok / tot, 4) if tot else None
        res["selection_checked"] = tot

    # 함정 사례
    if "함정" in d.columns:
        t = d[d["함정"].astype(str) == "Y"]
        res["trap_pairs"] = int(len(t))
        res["trap_errors"] = int(((t["status"] == "auto_approved") & (t["정답"] == 0)).sum())
    return res


def tune(d: pd.DataFrame, target: float = C.TARGET_PRECISION) -> dict:
    """규칙 점수 기준을 바꿔 가며 자동 승인 정밀도·비율을 본다 (확정 조건은 그대로)."""
    from .judge import gates, hard_reject
    rows = []
    feats = d["features"].map(lambda f: f if isinstance(f, dict) else {})
    sc = feats.map(rule_score)
    elig = feats.map(lambda f: not hard_reject(f) and not gates(f))
    for t in np.arange(0.70, 0.99, 0.01):
        sel = elig & (sc >= t)
        if sel.sum() == 0:
            continue
        rows.append({"threshold": round(float(t), 2), "n": int(sel.sum()), "precision": round(float(d.loc[sel, "정답"].mean()), 4),
                     "share_of_pos": round(float(d.loc[sel, "정답"].sum() / max(d["정답"].sum(), 1)), 4)})
    ok = [r for r in rows if r["precision"] >= target]
    return {"curve": rows, "recommended": min(ok, key=lambda r: r["threshold"]) if ok else None}


def ops_summary() -> dict:
    reps = [json.load(open(p, encoding="utf-8")) for p in sorted(glob.glob(os.path.join(C.HERE, "_reports", "*.json")))]
    if not reps:
        return {}
    last = reps[-7:]
    return {"days": len(reps), "avg_new_products_7d": round(np.mean([r["new_products"] for r in last]), 1),
            "queue_latest": last[-1]["queue"], "llm_calls_7d": int(sum(r.get("llm_calls", 0) for r in last))}


def to_markdown(res: dict, tuned: dict | None, ops: dict) -> str:
    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"
    cov = res.get("coverage") or {}
    L = [f"# 공급사 매핑 평가 결과 ({date.today()})", "",
         f"라벨 {res['labeled_pairs']:,}쌍 (정답 {res['positives']:,} / 오답 {res['negatives']:,}), 식재료 {res['ingredients']}개", "",
         "| 지표 | 값 | 목표 |", "|---|---|---|",
         f"| 후보 찾기 재현율 | {pct(res['candidate_recall'])} | 95% 이상 |",
         f"| 자동 승인 정밀도 | {pct(res['auto_precision'])} ({res['auto_approved']}쌍) | 98% 이상 |",
         f"| 자동 승인 비율 (정답 중) | {pct(res['auto_approve_share_of_positives'])} | 높을수록 좋음 |",
         f"| 자동 거절 정확도 | {pct(res['auto_reject_npv'])} | |",
         f"| 사용 중량 기준 가격 연결률 | {cov.get('weight_pct', '—')}% (상위 300: {cov.get('top300_weight_pct', '—')}%) | 90% 이상 |",
         f"| 상품 선택 정확도 (가장 싼 정답) | {pct(res.get('selection_accuracy'))} ({res.get('selection_checked', 0)}개) | |",
         f"| 함정 사례 오승인 | {res.get('trap_errors', '—')} / {res.get('trap_pairs', '—')} | 0 |", ""]
    if ops:
        L += [f"운영: 최근 7일 평균 신규 상품 {ops['avg_new_products_7d']}개, 대기열 {ops['queue_latest']:,}쌍, LLM 호출 {ops['llm_calls_7d']}회", ""]
    if res["false_auto_approvals"]:
        L += ["## 잘못 자동 승인된 쌍", "", "| 식재료 | 상품 | 근거 |", "|---|---|---|"]
        L += [f"| {r['식재료']} | {r['상품']} | {r['근거']} |" for r in res["false_auto_approvals"]]
        L += [""]
    if tuned and tuned.get("recommended"):
        r = tuned["recommended"]
        L += [f"## 기준 조정", "", f"정밀도 98% 이상이 되는 가장 낮은 규칙 점수 기준: **{r['threshold']}** "
              f"(자동 승인 {r['n']}쌍, 정밀도 {pct(r['precision'])}, 정답의 {pct(r['share_of_pos'])}) → config.AUTO_APPROVE", ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=os.path.join(C.HERE, "eval", "평가세트_라벨링.xlsx"))
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--reviews", action="store_true", help="사람 검수 결과로 평가")
    ap.add_argument("--tune", action="store_true")
    a = ap.parse_args(argv)
    store = open_store(a.store)
    ings = load_ingredients()
    mp = store.load_map()
    daily = store.load_daily()
    if a.reviews:
        h = mp[mp["status"].isin(["approved", "rejected"])]
        names = {i.ingredient_id: i.rep_name for i in ings}
        lab = pd.DataFrame({"식재료ID": h["ingredient_id"], "공급사": h["supplier"], "단품코드": h["item_cd"].astype(str),
                            "대표 원재료명": h["ingredient_id"].map(names),
                            "상품명": h["features"].map(lambda f: (f or {}).get("item_nm")),
                            "원/kg": h["features"].map(lambda f: ((f or {}).get("price_per_g") or np.nan) * 1000),
                            "정답": (h["status"] == "approved").astype(int)})
        # 사람이 본 쌍은 상태가 바뀌었으므로 판정 당시 상태를 알 수 없다 → 규칙 점수 기준으로만 조정
        mp = mp.assign(status=mp["status"].where(~mp["status"].isin(["approved", "rejected"]), "pending"))
        miss = pd.DataFrame(columns=["식재료ID", "공급사", "단품코드"])
    else:
        lab, miss = load_labels(a.labels)
    res = evaluate(lab, miss, mp, daily, ings)
    tuned = None
    if a.tune:
        key = ["식재료ID", "공급사", "단품코드"]
        m = mp.rename(columns={"ingredient_id": "식재료ID", "supplier": "공급사", "item_cd": "단품코드"})
        m["단품코드"] = m["단품코드"].astype(str)
        tuned = tune(lab.merge(m[key + ["features"]], on=key, how="inner"))
    md = to_markdown(res, tuned, ops_summary())
    out = os.path.join(C.HERE, "eval", f"평가결과_{date.today()}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(md)
    print(md)
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
