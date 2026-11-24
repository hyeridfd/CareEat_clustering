# -*- coding: utf-8 -*-
"""[진단] 돌봄 솔루션 다양성 — 규칙이 어르신마다 얼마나 다른 조치를 내는가

    python -m scripts.solution_diversity                          # 최신 평가 전체 (HS·MH 두 자리 ID)
    python -m scripts.solution_diversity --ids scripts\\heritage_complete34.txt
    python -m scripts.solution_diversity --ids "…\\results_n_complete\\analysis_tables.xlsx"   # 설문 분석 72명

  · Supabase care_assessments 의 어르신별 최신 평가를 읽어, 솔루션 생성과 똑같이 규칙 후보를 뽑는다 (LLM 호출 없음)
      후보 = care_rules.select(지표, 맥락)    규칙 초안 = solution.rules_solution(…)  ← 조치 6개, 지침·관찰 5개
  · 지표
      규칙별 발동률 · 규칙 초안(상위 6칸)에 들어간 비율 · 후보에 있었지만 6칸에서 밀려난 비율
      서로 다른 후보 조합 수 / 규칙 초안 조합 수 · 가장 큰 '똑같은 초안' 묶음
      어르신 쌍 유사도: 후보 집합 Jaccard, 초안 조치 집합 Jaccard, 초안 문장(글자 2-gram) 유사도
      초안 6칸이 몇 개 분류에 걸쳐 있는가
  · 출력: scripts/solution_diversity_result.xlsx  (식별번호만, 이름 없음)
"""
from __future__ import annotations

import argparse
import itertools
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
ID_RE = re.compile(r"^(HS|MH)\d{2}$")


def read_ids(spec: str | None) -> set | None:
    if not spec:
        return None
    p = Path(spec)
    if p.is_file() and p.suffix.lower() in (".xlsx", ".xls", ".csv"):
        if p.suffix.lower() == ".csv":
            df = pd.read_csv(p)
        else:
            xl = pd.ExcelFile(p)
            df = pd.read_excel(p, sheet_name="대상선정" if "대상선정" in xl.sheet_names else 0)
        if "판정" in df.columns:
            df = df[df["판정"] == "분석 포함"]
        col = next((c for c in ("식별번호", "ID", "id", "elderly_id") if c in df.columns), df.columns[0])
        vals = df[col].astype(str)
    elif p.is_file() and p.suffix.lower() == ".json":        # folder_ids.json (영양조사 폴더 목록)
        import json
        d = json.loads(p.read_text(encoding="utf-8"))
        vals = [i for fac in (d.get("facilities") or {}).values() for i in fac.get("ids") or []] if isinstance(d, dict) else d
    elif p.is_file():
        vals = re.split(r"[\s,]+", p.read_text(encoding="utf-8"))
    else:
        vals = spec.split(",")
    return {v.strip().upper() for v in vals if ID_RE.match(v.strip().upper())}


def load_assessments(ids: set | None) -> list[dict]:
    try:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env")
    except Exception:
        pass
    from dependencies import get_supabase
    from care.data import fetch_all
    rows = fetch_all(get_supabase(), "care_assessments",
                     "elderly_id,created_at,type_code,type_name,priority_score,priority_level,priority_factors,"
                     "is_borderline,features", order="created_at", desc=True)
    latest = {}
    for r in rows:
        e = str(r["elderly_id"]).strip().upper()
        if e in latest or not ID_RE.match(e) or (ids and e not in ids):
            continue
        latest[e] = r
    return [latest[k] for k in sorted(latest)]


def run_rules(a: dict) -> dict:
    from care import care_rules
    from care import solution as S
    f = a.get("features") or {}
    factors = a.get("priority_factors") or []
    pri = {"score": float(a.get("priority_score") or 0), "level": a.get("priority_level") or "low", "factors": factors}
    _n, npct, low_meal = S.nutrition_summary(f)
    ctx = {"factor_codes": {x.get("code") for x in factors}, "is_borderline": bool(a.get("is_borderline")),
           "priority_level": pri["level"], "nutrition_pct": npct, "low_meal": low_meal,
           "low_components": S.low_components(f)}
    cands = care_rules.select(f, ctx)
    tinfo = {"name": a.get("type_name") or a.get("type_code"), "guardian_label": a.get("type_name")}
    fb = S.rules_solution(tinfo, pri, cands)
    return {"id": str(a["elderly_id"]).upper(), "type": a.get("type_code"), "level": pri["level"],
            "score": pri["score"], "cands": [c["id"] for c in cands], "cat": {c["id"]: c["category"] for c in cands},
            "top6": [x["rule_id"] for x in fb["staff_actions"]], "fb": fb}


def jacc(a, b) -> float:
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def text_of(fb: dict) -> str:
    return " ".join([x["action"] for x in fb["staff_actions"]] + fb["meal_guidance"] + fb["monitoring"])


def grams(s: str) -> set:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def analyze(res: list[dict]):
    n = len(res)
    from care import care_rules
    order = [r["id"] for r in care_rules.RULES]
    cat = {r["id"]: r["category"] for r in care_rules.RULES}
    fire = Counter(x for r in res for x in r["cands"])
    top = Counter(x for r in res for x in r["top6"])
    rule_tab = pd.DataFrame([{
        "규칙": rid, "분류": cat[rid], "목록 순서": i + 1,
        "발동 (명)": fire[rid], "발동률(%)": round(100 * fire[rid] / n, 1),
        "초안 6칸 포함 (명)": top[rid], "밀려남 (명)": fire[rid] - top[rid],
        "밀려난 비율(%)": round(100 * (fire[rid] - top[rid]) / fire[rid], 1) if fire[rid] else np.nan,
    } for i, rid in enumerate(order)])

    per = pd.DataFrame([{
        "식별번호": r["id"], "유형": r["type"], "우선순위": r["level"], "점수": r["score"],
        "후보 수": len(r["cands"]), "초안 6칸": ", ".join(r["top6"]),
        "밀려난 후보": ", ".join(x for x in r["cands"] if x not in r["top6"]),
        "6칸 분류 수": len({cat[x] for x in r["top6"]}),
    } for r in res])

    cset = Counter(tuple(sorted(r["cands"])) for r in res)
    tset = Counter(tuple(r["top6"]) for r in res)
    pairs = list(itertools.combinations(range(n), 2))
    g = [grams(text_of(r["fb"])) for r in res]
    jc = np.array([jacc(res[i]["cands"], res[j]["cands"]) for i, j in pairs]) if pairs else np.array([np.nan])
    jt = np.array([jacc(res[i]["top6"], res[j]["top6"]) for i, j in pairs]) if pairs else np.array([np.nan])
    js = np.array([jacc(g[i], g[j]) for i, j in pairs]) if pairs else np.array([np.nan])

    summ = pd.DataFrame([
        ("어르신 수", n),
        ("평균 후보 수 (범위)", f"{per['후보 수'].mean():.1f} ({per['후보 수'].min()}–{per['후보 수'].max()})"),
        ("후보가 6개 넘는 어르신", f"{int((per['후보 수'] > 6).sum())}명 ({100 * (per['후보 수'] > 6).mean():.0f}%)"),
        ("서로 다른 후보 조합", f"{len(cset)}가지"),
        ("서로 다른 규칙 초안(6칸) 조합", f"{len(tset)}가지"),
        ("가장 큰 '똑같은 초안' 묶음", f"{max(tset.values())}명"),
        ("후보 집합 유사도 (Jaccard) 평균 / 중앙값", f"{np.nanmean(jc):.2f} / {np.nanmedian(jc):.2f}"),
        ("초안 조치 유사도 (Jaccard) 평균 / 중앙값", f"{np.nanmean(jt):.2f} / {np.nanmedian(jt):.2f}"),
        ("초안 조치가 80% 이상 겹치는 쌍", f"{100 * np.mean(jt >= 0.8):.1f}%"),
        ("초안 문장 유사도 (글자 2-gram) 평균", f"{np.nanmean(js):.2f}"),
        ("6칸이 걸친 분류 수 평균", f"{per['6칸 분류 수'].mean():.1f}"),
    ], columns=["지표", "값"])
    combos = pd.DataFrame([{"규칙 초안(6칸)": ", ".join(k), "어르신 수": v} for k, v in tset.most_common(15)])
    sim = pd.DataFrame({"후보 Jaccard": jc, "초안 Jaccard": jt, "문장 유사도": js})
    return summ, rule_tab, per, combos, sim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="식별번호 목록 (txt/csv/xlsx, analysis_tables.xlsx 의 '분석 포함')")
    ap.add_argument("--out", default=str(BACKEND / "scripts" / "solution_diversity_result.xlsx"))
    ap.add_argument("--mock", help=argparse.SUPPRESS)        # 개발용: 평가 행 JSON
    a = ap.parse_args()
    if a.mock:
        import json
        rows = json.loads(Path(a.mock).read_text(encoding="utf-8"))
    else:
        rows = load_assessments(read_ids(a.ids))
    res = [run_rules(r) for r in rows]
    summ, rule_tab, per, combos, sim = analyze(res)
    pd.set_option("display.width", 200)
    print(summ.to_string(index=False))
    print("\n=== 발동률 상위 규칙 ===")
    print(rule_tab.sort_values("발동률(%)", ascending=False).head(15).to_string(index=False))
    print("\n=== 자주 나오는 규칙 초안 조합 ===")
    print(combos.head(5).to_string(index=False))
    with pd.ExcelWriter(a.out) as w:
        summ.to_excel(w, sheet_name="요약", index=False)
        rule_tab.to_excel(w, sheet_name="규칙별", index=False)
        per.to_excel(w, sheet_name="어르신별", index=False)
        combos.to_excel(w, sheet_name="초안_조합", index=False)
        sim.describe().round(3).to_excel(w, sheet_name="쌍_유사도_분포")
    print("\n결과:", a.out)


if __name__ == "__main__":
    main()
