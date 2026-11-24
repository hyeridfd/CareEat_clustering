# -*- coding: utf-8 -*-
"""[검증] 전문가 판정 일치율 — 시스템 vs 전문가 (Cohen's κ) · 전문가끼리 (Fleiss' κ) · 시스템 결과 적절성

    python -m scripts.expert_agreement --system scripts/validate_scenarios_result.xlsx \\
        --experts 평가지_전문가1.xlsx 평가지_전문가2.xlsx 평가지_전문가3.xlsx

  입력  --system   validate_scenarios.py 결과 (시트 '시스템_판정')
        --experts  전문가가 작성한 expert_form.xlsx (시트 '1_독립판정', '2_시스템결과')
  항목
    문제:○○        해당 1 / 아님 0                         → 범주(문제)마다 일치율·κ, 전체(모든 범주 합쳐서) 일치율·κ
    권장 식사형태    밥/일반찬 · 밥/다진찬 · 죽/일반찬 · 죽/다진찬 · 죽/갈찬
    충돌:○○        A(시스템 규칙 방향) / B / 빈칸(충돌 없음)
    적절성          적절 / 부분 적절 / 부적절                → 비율
  출력: scripts/expert_agreement_result.xlsx
  해석 기준 (Landis & Koch 1977): κ < 0.20 낮음 · 0.21–0.40 약함 · 0.41–0.60 보통 · 0.61–0.80 상당 · 0.81 이상 거의 완전
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent


def norm(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace(" ", "").replace("일반밥", "밥").upper()


def cohen(a: list, b: list) -> tuple[float, float, int]:
    """(일치율, κ, n) — 빈칸도 하나의 범주(충돌 없음 등)로 본다"""
    n = len(a)
    if n == 0:
        return np.nan, np.nan, 0
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    k = (po - pe) / (1 - pe) if pe < 1 else (1.0 if po == 1 else np.nan)
    return po, k, n


def fleiss(rows: list[list[str]]) -> float:
    """rows = 대상마다 평가자들의 판정 목록 (평가자 수 같아야 함)"""
    rows = [r for r in rows if len(r) >= 2]
    if not rows:
        return np.nan
    m = len(rows[0])
    cats = sorted({c for r in rows for c in r})
    P, tot = [], Counter()
    for r in rows:
        c = Counter(r)
        tot.update(c)
        P.append((sum(v * v for v in c.values()) - m) / (m * (m - 1)))
    pbar = float(np.mean(P))
    pe = sum((tot[k] / (len(rows) * m)) ** 2 for k in cats)
    return (pbar - pe) / (1 - pe) if pe < 1 else (1.0 if pbar == 1 else np.nan)


def label(k) -> str:
    if k is None or np.isnan(k):
        return "-"
    return "낮음" if k <= 0.20 else "약함" if k <= 0.40 else "보통" if k <= 0.60 else "상당" if k <= 0.80 else "거의 완전"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default=str(BACKEND / "scripts" / "validate_scenarios_result.xlsx"))
    ap.add_argument("--experts", nargs="+", required=True)
    ap.add_argument("--out", default=str(BACKEND / "scripts" / "expert_agreement_result.xlsx"))
    a = ap.parse_args()

    sysd = pd.read_excel(a.system, sheet_name="시스템_판정").set_index("시나리오")
    ex = {Path(p).stem: pd.read_excel(p, sheet_name="1_독립판정").set_index("시나리오") for p in a.experts}
    items = [c for c in sysd.columns if c.startswith(("문제:", "충돌:")) or c == "권장 식사형태"]

    rows, pooled = [], {e: ([], []) for e in ex}
    for it in items:
        groups = {"문제:": "문제", "충돌:": "충돌"}
        kind = next((v for k, v in groups.items() if it.startswith(k)), "식사형태")
        r = {"항목": it, "구분": kind}
        common = sorted(set(sysd.index).intersection(*[set(d.index) for d in ex.values()]))
        for e, d in ex.items():
            if it not in d.columns:
                continue
            s_vals = [norm(sysd.at[i, it]) for i in common]
            e_vals = [norm(d.at[i, it]) for i in common]
            keep = [(x, y) for x, y in zip(s_vals, e_vals) if kind != "식사형태" or y]   # 식사형태는 빈칸이면 미응답
            po, k, n = cohen([x for x, _ in keep], [y for _, y in keep])
            r[f"{e} 일치율(%)"] = round(100 * po, 1) if n else np.nan
            r[f"{e} κ"] = round(k, 3) if n else np.nan
            if kind == "문제":
                pooled[e][0].extend(x for x, _ in keep)
                pooled[e][1].extend(y for _, y in keep)
        if len(ex) >= 2 and all(it in d.columns for d in ex.values()):
            r["전문가 간 Fleiss κ"] = round(fleiss([[norm(d.at[i, it]) for d in ex.values()] for i in common]), 3)
        rows.append(r)
    tab = pd.DataFrame(rows)

    summ = []
    for e, (s_, e_) in pooled.items():
        po, k, n = cohen(s_, e_)
        summ.append({"비교": f"시스템 vs {e} — 문제 범주 전체", "판정 수": n, "일치율(%)": round(100 * po, 1),
                     "κ": round(k, 3), "해석": label(k)})
    for kind in ("식사형태", "충돌"):
        sub = tab[tab["구분"] == kind]
        for e in ex:
            col = f"{e} κ"
            if col in sub:
                summ.append({"비교": f"시스템 vs {e} — {kind}", "판정 수": "", "일치율(%)": round(sub[f"{e} 일치율(%)"].mean(), 1),
                             "κ": round(sub[col].mean(), 3), "해석": label(sub[col].mean())})
    if "전문가 간 Fleiss κ" in tab:
        for kind in ("문제", "식사형태", "충돌"):
            v = tab.loc[tab["구분"] == kind, "전문가 간 Fleiss κ"].mean()
            summ.append({"비교": f"전문가 간 ({len(ex)}명) — {kind}", "판정 수": "", "일치율(%)": "", "κ": round(v, 3), "해석": label(v)})
    summ = pd.DataFrame(summ)

    # 시스템 결과 적절성
    apt = []
    for e, p in zip(ex, a.experts):
        d = pd.read_excel(p, sheet_name="2_시스템결과")
        col = next((c for c in d.columns if str(c).startswith("적절성")), None)
        if col is None:
            continue
        v = d[col].astype(str).str.replace(" ", "")
        n = int(v.isin(["적절", "부분적절", "부적절"]).sum())
        apt.append({"전문가": e, "응답": n, "적절(%)": round(100 * (v == "적절").sum() / max(n, 1), 1),
                    "부분 적절(%)": round(100 * (v == "부분적절").sum() / max(n, 1), 1),
                    "부적절(%)": round(100 * (v == "부적절").sum() / max(n, 1), 1)})
    apt = pd.DataFrame(apt)

    print(summ.to_string(index=False))
    if len(apt):
        print("\n=== 시스템 결과 적절성 ===")
        print(apt.to_string(index=False))
    with pd.ExcelWriter(a.out) as w:
        summ.to_excel(w, sheet_name="요약", index=False)
        tab.to_excel(w, sheet_name="항목별", index=False)
        apt.to_excel(w, sheet_name="적절성", index=False)
    print("\n결과:", a.out)


if __name__ == "__main__":
    main()
