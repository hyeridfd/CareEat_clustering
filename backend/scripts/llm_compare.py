# -*- coding: utf-8 -*-
"""LLM 모델 비교 — 같은 합성 샘플로 AI 영양사 3단계(선택 · 검토 · 개인 종합 판단)를 모델별로 돌려 나란히 비교

  실행 (backend 폴더에서):
    venv-win\\Scripts\\python -m scripts.llm_compare
    venv-win\\Scripts\\python -m scripts.llm_compare gpt-4.1 gpt-6.1-terra gpt-6.1-sol --effort low --repeat 2

  · 입력: tests/llm_select_sample.json · llm_review_sample.json · llm_refine_sample.json (합성 데이터, 개인정보 없음)
  · 필요: backend/.env 의 OPENAI_API_KEY, DIET_LLM_PROVIDER=openai
  · 출력: 화면 표 + scripts/llm_compare_result.json (모델별 상세 결과)
  · --repeat N: 같은 입력을 N번 돌려 답이 얼마나 같은지(재현성) 확인

  비교 지표
    선택  — 고른 후보, 경고 수(입력에 없는 숫자 등), 다시 물은 횟수
    검토  — 제안 수, 코드 검증 통과(반영)·거절 수, 거절 사유, f 변화
    종합  — 어르신 3명: 기준 조정 수 · 허용 범위 밖이라 잘린 수 · 우선순위 조정 수 · 경고 수 · 실패(규칙 대체) 수
    공통  — 호출 수, 입력/출력 토큰, 응답 시간, 추정 비용
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import time
from collections import Counter
from pathlib import Path

# 1M 토큰당 달러 (입력, 출력) — 추정 비용 계산용. 실제 가격은 OpenAI 가격표로 확인하고 고쳐 쓰세요.
PRICE = {
    "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6), "gpt-4o-mini": (0.15, 0.6),
    "gpt-6-sol": (2.0, 10.0), "gpt-6.1-sol": (2.0, 10.0), "gpt-6.1-terra": (1.0, 5.0), "gpt-6-luna": (0.10, 0.50),
}
TESTS = Path(__file__).resolve().parent.parent / "tests"


def _usage_since(LS, n0):
    u = LS.USAGE[n0:]
    return {"calls": len(u), "in": sum(x["in"] for x in u), "out": sum(x["out"] for x in u),
            "sec": round(sum(x["sec"] for x in u), 1)}


def run_select(LS):
    src = json.load(open(TESTS / "llm_select_sample.json", encoding="utf-8"))
    payload = LS.build_payload(src["시설_상황"], src["후보"])
    ids = [c["id"] for c in payload["후보"]]
    n0 = len(LS.USAGE)
    try:
        res, warn, model = LS.ask(payload, ids)
        return {"ok": True, "choice": res.get("choice") or res.get("selected") or res.get("id"),
                "warnings": warn, "retried": any("다시 답함" in w for w in warn),
                "summary": res.get("summary"), "usage": _usage_since(LS, n0)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "usage": _usage_since(LS, n0)}


def run_review(LS):
    from diet import llm_review as LR
    from diet.base_standard import BaseStandard
    from diet.pipeline import BUDGET_PER_MEAL, harmony_table, load_pool, records_to_chrom
    from diet.problem import MealPlanProblem
    src = json.load(open(TESTS / "llm_review_sample.json", encoding="utf-8"))
    pool = load_pool()
    prob = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, harmony=harmony_table(pool))
    ch = records_to_chrom(prob, src["menu"])
    n0 = len(LS.USAGE)
    with contextlib.redirect_stdout(io.StringIO()):
        _, rec = LR.review_menu(prob, ch, src["context"], progress=lambda *_: None)
    rej = rec.get("rejected") or []
    return {"ok": rec.get("mode") == "llm",
            "suggested": rec.get("n_suggested"), "accepted": len(rec.get("accepted") or []), "rejected": len(rej),
            "reject_reasons": dict(Counter(str(r.get("reason"))[:30] for r in rej).most_common(5)),
            "f_before": rec.get("f_before"), "f_after": rec.get("f_after"), "note": rec.get("note"),
            "accepted_list": [f"{a['day']}일 {a['meal']} {a['slot']}: {a['current']} → {a['replace_with']}"
                              for a in rec.get("accepted") or []],
            "usage": _usage_since(LS, n0)}


def run_refine(LS):
    from diet.agents import refine as RF
    from diet.agents.manager import assess_residents
    RF._CACHE.clear()
    ctxs = json.load(open(TESTS / "llm_refine_sample.json", encoding="utf-8"))
    res = assess_residents(ctxs)
    n0 = len(LS.USAGE)
    out = {"residents": {}, "adjust": 0, "clamped": 0, "rescore": 0, "warnings": 0, "failed": 0}
    for eid, ctx in ctxs.items():
        r = RF.refine_one(ctx, res[eid])
        if r.get("mode") != "llm":
            out["failed"] += 1
            out["residents"][eid] = {"mode": r.get("mode"), "note": r.get("note")}
            continue
        adj = r.get("adjustments") or []
        out["adjust"] += len(adj)
        out["clamped"] += sum(1 for a in adj if a.get("clamped")) + (1 if (r.get("target_energy") or {}).get("clamped") else 0)
        out["rescore"] += len(r.get("rescore") or [])
        out["warnings"] += len(r.get("warnings") or [])
        out["residents"][eid] = {"summary": r.get("summary"),
                                 "adjustments": [f"{a['label']} {a['before']}→{a['after']}" for a in adj],
                                 "rescore": [f"{x['title']} {x['before']['priority']}→{x['after']['priority']}"
                                             for x in r.get("rescore") or []],
                                 "warnings": r.get("warnings")}
    out["usage"] = _usage_since(LS, n0)
    return out


def cost(model, u):
    p = PRICE.get(model)
    return round((u["in"] * p[0] + u["out"] * p[1]) / 1e6, 4) if p else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=["gpt-4.1", "gpt-6.1-terra", "gpt-6.1-sol"])
    ap.add_argument("--effort", default="low", help="추론형 모델의 추론 강도 (none|low|medium|high)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--skip", default="", help="건너뛸 단계: select,review,refine")
    a = ap.parse_args()
    skip = set(x for x in a.skip.split(",") if x)

    from diet import llm_select as LS
    os.environ.setdefault("DIET_LLM_PROVIDER", LS.provider() if LS.provider() != "none" else "openai")
    os.environ["DIET_LLM_EFFORT"] = a.effort
    print("제공자:", LS.provider(), "· 추론 강도(추론형 모델만):", a.effort)

    results = {}
    for m in a.models:
        os.environ["DIET_LLM_MODEL"] = m
        runs = []
        for k in range(a.repeat):
            print(f"\n=== {m} ({k + 1}/{a.repeat}) ===")
            t0 = time.time()
            r = {}
            if "select" not in skip:
                r["select"] = run_select(LS); print("  선택:", r["select"].get("choice"), "· 경고", r["select"].get("warnings") or r["select"].get("error"))
            if "review" not in skip:
                r["review"] = run_review(LS); print(f"  검토: 제안 {r['review']['suggested']} → 반영 {r['review']['accepted']} · 거절 {r['review']['rejected']}")
            if "refine" not in skip:
                r["refine"] = run_refine(LS); print(f"  종합: 조정 {r['refine']['adjust']} · 잘림 {r['refine']['clamped']} · 우선순위 {r['refine']['rescore']} · 경고 {r['refine']['warnings']} · 실패 {r['refine']['failed']}")
            r["wall_sec"] = round(time.time() - t0, 1)
            runs.append(r)
        results[m] = runs

    # ── 요약 표 ──
    print("\n" + "=" * 100)
    head = f"{'모델':<16}{'선택':>6}{'선택경고':>8}{'검토 제안→반영/거절':>20}{'종합 조정/잘림/경고/실패':>26}{'호출':>6}{'토큰(입/출)':>16}{'시간(초)':>9}{'비용($)':>9}"
    print(head)
    for m, runs in results.items():
        for r in runs:
            s, v, f = r.get("select", {}), r.get("review", {}), r.get("refine", {})
            us = [x.get("usage") for x in (s, v, f) if x.get("usage")]
            u = {"calls": sum(x["calls"] for x in us), "in": sum(x["in"] for x in us), "out": sum(x["out"] for x in us)}
            c = cost(m, u)
            print(f"{m:<16}{str(s.get('choice', '–')):>6}{len(s.get('warnings') or []):>8}"
                  f"{str(v.get('suggested', '–')) + '→' + str(v.get('accepted', '–')) + '/' + str(v.get('rejected', '–')):>20}"
                  f"{'/'.join(str(f.get(k, '–')) for k in ('adjust', 'clamped', 'warnings', 'failed')):>26}"
                  f"{u['calls']:>6}{str(u['in']) + '/' + str(u['out']):>16}{r['wall_sec']:>9}{(c if c is not None else '–'):>9}")
    if any(len(r) > 1 for r in results.values()):
        print("\n재현성 (같은 입력 반복 시 같은 후보를 고른 비율):")
        for m, runs in results.items():
            ch = [r.get("select", {}).get("choice") for r in runs]
            top = Counter(ch).most_common(1)[0][1] if ch else 0
            print(f"  {m}: {ch} → {top}/{len(ch)}")
    out = Path(__file__).resolve().parent / "llm_compare_result.json"
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\n상세 결과:", out)
    print("※ 비용은 PRICE 표 기준 추정치입니다. 모델별 실제 가격은 OpenAI 가격표로 확인하세요.")


if __name__ == "__main__":
    main()
