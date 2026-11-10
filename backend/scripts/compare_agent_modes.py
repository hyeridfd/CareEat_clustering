# -*- coding: utf-8 -*-
"""Stage 1 비교: 규칙 선별만 vs AI 영역 전문가(근거 검색 RAG + LLM 판단) + 3단계 종합(충돌별 질환 전문가)

    python -m scripts.compare_agent_modes                 # 합성 어르신 4명
    python -m scripts.compare_agent_modes --local         # 근거를 Supabase 대신 docs/*.md 에서 (적재 전 시험)

  필요: backend/.env 의 OPENAI_API_KEY · DIET_LLM_PROVIDER=openai · DIET_LLM_MODEL (예: gpt-6.1-terra)
  입력: 합성 어르신 (식별정보 없음) — 저체중·당뇨·고혈압·치매·연하곤란·약물·신장질환이 섞인 6명
  보는 것 (논문 단계별 비교용)
    · 문제별 규칙 S → AI S, 안전성 점수 유지 여부, 우선순위 순서 변화
    · 판단 근거 인용 수, 인용 없는 판단, 걸러진 경고(범위 밖 점수·없는 숫자·없는 문제)
    · 우려(근거와 다른 규칙)·추가 확인 정보
    · 영역별 호출 시간, 토큰
  결과 전체: scripts/compare_agent_modes_result.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from dotenv import load_dotenv                                  # noqa: E402
load_dotenv(BACKEND / ".env")

BASE = dict(height_cm=155, weight_kg=50, kmbi_max=100, med_records=[], allergy_records=[], slot_rates={}, avg_day={})
SAMPLES = {
    "S1 저체중·당뇨·연하곤란": {**BASE, "age": 86, "female": 1, "weight_kg": 40, "bmi": 16.6, "mna_risk": 2, "kmbi_score": 30,
                           "diseases": ["당뇨병", "치매"], "medications": ["당뇨병약"], "intake_rate": 0.52, "mmse": 15,
                           "swallowing_difficulty": True, "meal_form": "죽/다진찬", "avg_day": {"energy": 850, "protein": 28}},
    "S2 비만·고혈압·와파린": {**BASE, "age": 78, "female": 0, "weight_kg": 82, "bmi": 30.5, "diseases": ["고혈압"],
                          "sbp": 162, "dbp": 96, "medications": ["항혈전제", "혈압약"], "med_records": [{"name": "와파린정 2mg"}],
                          "na_day": 3100, "k_day": 1700, "meal_form": "밥/일반찬"},
    "S3 치매·우울·저작곤란": {**BASE, "age": 90, "female": 1, "bmi": 20.4, "diseases": ["치매"], "mmse": 18, "gds": 10,
                          "eating_dependence": 2, "chewing_difficulty": True, "meal_form": "밥/다진찬", "intake_rate": 0.66,
                          "slot_rates": {"국": 0.45, "부찬": 0.4}, "allergy_records": [{"allergen": "새우", "severity": "moderate"}]},
    "S4 혈압 기준 고혈압·일반의약품": {**BASE, "age": 72, "female": 1, "bmi": 24.0, "sbp": 136, "dbp": 92,
                                "med_records": [{"name": "펙소딘정60밀리그램"}, {"name": "훼로바-유서방정"}],
                                "medications": ["철분제"], "meal_form": "밥/일반찬"},
}
# [2026-11-10] 3단계 충돌 확인용
SAMPLES["S5 비만·근감소·신장질환·칼륨보존이뇨제"] = {**SAMPLES["S2 비만·고혈압·와파린"], "diseases": ["고혈압", "만성신장질환"], "kmbi_score": 40,
                                         "med_records": [{"name": "알닥톤필름코팅정25mg"}], "k_day": 1500}
SAMPLES["S6 당뇨약·섭취저하·고혈압·저체중"] = {**SAMPLES["S1 저체중·당뇨·연하곤란"], "diseases": ["당뇨병", "고혈압"],
                                       "intake_rate": 0.4, "sbp": 150, "dbp": 85}


def stage3(llm: dict):
    """3단계: 종합·안전성 검증 (충돌별 질환 전문가 LLM 켬) — 단계별 기록과 전문가 판단 출력"""
    from diet import llm_select as LS
    from diet.agents.synthesis import finalize
    n0, t0 = len(LS.USAGE), time.time()
    out, summ = {}, {"conflicts": 0, "specialist_calls": 0, "cited": 0, "adjust": 0, "rescore": 0, "warnings": 0, "overrides": 0}
    for sid, v in llm.items():
        syn = finalize(v["synth"], SAMPLES[sid], None, v["agents"], use_specialists=True)
        out[sid] = syn
        sy = syn["synthesis"]
        print(f"\n{'=' * 90}\n[3단계] {sid}")
        for st in sy["steps"]:
            print(f"  {st['step']}) {st['name']}")
            for t in st["items"]:
                print(f"     - {t}")
        for c in sy["conflicts"]:
            summ["conflicts"] += 1
            sp = c.get("specialist") or {}
            if sp.get("mode") == "llm":
                summ["specialist_calls"] += 1
                summ["cited"] += bool(sp.get("cites"))
                summ["adjust"] += len(sp.get("adjustments") or [])
                summ["rescore"] += len(sp.get("rescore") or [])
                summ["warnings"] += len(sp.get("warnings") or [])
                for w in sp.get("warnings") or []:
                    print(f"     ! 검증({c['id']}): {w}")
            elif sp:
                print(f"     · {c['id']}: {sp.get('note')}")
        summ["overrides"] += sum(1 for o in sy["overrides"] if o["ops"])
        if sy["to_confirm"]:
            print("  추가 확인:", sy["to_confirm"])
    usage = LS.USAGE[n0:]
    print(f"\n3단계 요약: {summ} · 호출 {len(usage)}회 · 토큰 {sum(u['in'] for u in usage)}/{sum(u['out'] for u in usage)} · {time.time() - t0:.1f}초")
    return out, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    a = ap.parse_args()
    if a.local:
        os.environ["RAG_BACKEND"] = "local"
    from diet import llm_select as LS
    from diet.agents import assess_residents, to_json
    from diet.agents.llm_agent import make_judge
    st = LS.status()
    print("LLM:", st, "· 근거 저장소:", os.getenv("RAG_BACKEND", "supabase"))
    if not st.get("ready"):
        raise SystemExit("LLM 이 설정되지 않았습니다 (.env 의 DIET_LLM_PROVIDER / OPENAI_API_KEY)")
    rule = assess_residents(SAMPLES)
    n0, t0 = len(LS.USAGE), time.time()
    llm = assess_residents(SAMPLES, judge=make_judge())
    wall = time.time() - t0
    usage = LS.USAGE[n0:]
    tot = {"calls": len(usage), "in": sum(u["in"] for u in usage), "out": sum(u["out"] for u in usage)}
    summary = {"cited": 0, "uncited": 0, "changed": 0, "safety_changed": 0, "warnings": 0, "concerns": 0, "missing": 0, "fail": 0}
    for sid in SAMPLES:
        print(f"\n{'=' * 90}\n{sid}")
        rr = {(x.agent, i.code): i for x in rule[sid]["agents"] for i in x.issues}
        for ag in llm[sid]["agents"]:
            if not ag.active:
                continue
            l = ag.llm or {}
            print(f"\n  [{ag.label}] {l.get('mode')} · 근거 {len(ag.evidence)}개 · {l.get('latency_sec', '-')}초"
                  + (f" · {l.get('note')}" if l.get("mode") != "llm" else ""))
            if l.get("mode") != "llm":
                summary["fail"] += 1
                continue
            print(f"    요약: {l.get('summary')}")
            for i in ag.issues:
                r = rr.get((ag.agent, i.code))
                s0, s1 = (r.priority if r else None), i.priority
                ch = r is not None and abs(s0 - s1) > 1e-6
                summary["changed"] += ch
                summary["safety_changed"] += ch and i.level == 1
                summary["cited"] += bool(i.cites)
                summary["uncited"] += not i.cites
                print(f"    - L{i.level} {i.code}: S {s0} → {s1}{'  (변경)' if ch else ''} · 인용 {i.cites}")
                if i.rationale:
                    print(f"        {i.rationale}")
            for c in l.get("concerns") or []:
                print(f"    ⚠ 우려: {c}")
            for m in l.get("missing") or []:
                print(f"    ? 추가 확인: {m}")
            for w in l.get("warnings") or []:
                print(f"    ! 검증: {w}")
            summary["warnings"] += len(l.get("warnings") or [])
            summary["concerns"] += len(l.get("concerns") or [])
            summary["missing"] += len(l.get("missing") or [])
        o0 = [p["code"] for p in rule[sid]["synth"]["priorities"]]
        o1 = [p["code"] for p in llm[sid]["synth"]["priorities"]]
        print(f"\n  우선순위 순서 {'같음' if o0 == o1 else '바뀜'}\n    규칙: {o0}\n    AI  : {o1}")
    print(f"\n{'=' * 90}\n요약: {summary}\n호출 {tot['calls']}회 · 토큰 {tot['in']}/{tot['out']} · 전체 {wall:.1f}초 (병렬)")
    s3, s3sum = stage3(llm)
    out = BACKEND / "scripts" / "compare_agent_modes_result.json"
    json.dump({"summary": summary, "usage": tot, "rule": to_json(rule), "llm": to_json(llm), "stage3": s3, "stage3_summary": s3sum},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("상세:", out)


if __name__ == "__main__":
    main()
