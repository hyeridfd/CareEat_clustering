# -*- coding: utf-8 -*-
"""관리자 에이전트 — 어르신 정보를 영역별로 나눠 도메인 에이전트에 병렬로 맡기고, 결과를 모은다

  NutriOrion Stage 1 (Parallel Independent Assessment) 에 해당:
    1) 어르신 1명의 전체 정보(ctx)를 만든다 — 평가 결과·기초조사·조사 기간 섭취·기록 탭(약·알레르기)
    2) 에이전트별로 CONTEXT_KEYS 만 잘라서 넘긴다 (맥락 격리: 다른 영역 정보를 보지 못함)
    3) 해당하는 에이전트만 활성화(applicable)하고, 모든 (어르신 × 에이전트)를 동시에 실행
    4) 종합(synthesize): 영양 기준은 같은 영양소끼리 더 엄격한 값 (출처 에이전트 기록),
       피할 식재료는 합치고, 문제는 Level 1(안전성) → Level 2(영양 중재, 파레토 묶음 → S 순)로 정렬
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .base import ConstraintSpec, rank_priorities
from .domain import BodyAgent, CognitionAgent, DiabetesAgent, HypertensionAgent, IntakeAgent, OralAgent, _num
from .medication import MedicationAgent

AGENTS = [BodyAgent(), DiabetesAgent(), HypertensionAgent(), CognitionAgent(), OralAgent(), IntakeAgent(), MedicationAgent()]
SLOT_GROUP = {"밥": "밥", "죽": "밥", "국/탕": "국", "국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "부찬": "부찬",
              "김치1": "김치", "김치2": "김치", "김치": "김치"}
FIELDS = {("energy", "min"): "energy_min", ("energy", "max"): "energy_max", ("sugar", "max"): "sugar_max",
          ("protein", "min"): "protein_min", ("protein", "max"): "protein_max", ("fat", "min"): "fat_min",
          ("fat", "max"): "fat_max", ("sat_fat", "max"): "sat_fat_max", ("sodium", "max"): "sodium_max",
          ("potassium", "min"): "potassium_min", ("fiber", "min"): "fiber_min",
          ("carb", "min"): "carb_min", ("carb", "max"): "carb_max"}
DISEASE_AGENTS = {"diabetes", "hypertension"}      # 식단형 규격·학회 지침 기준을 내는 영역


def _rates(meal_log) -> tuple:
    """조사 기간 끼니 기록 → (전체 평균 섭취율, {칸: 평균 섭취율})"""
    by, allr = {}, []
    for m in meal_log or []:
        for it in m.get("items") or []:
            r = _num(it.get("rate"))
            if r is None:
                continue
            r = r / 100 if r > 1.0 else r
            g = SLOT_GROUP.get(str(it.get("slot")), None)
            allr.append(r)
            if g:
                by.setdefault(g, []).append(r)
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    return mean(allr), {k: mean(v) for k, v in by.items()}


def build_context(resident: dict, features: dict, rice: str, side: str, med_records=None, allergy_records=None) -> dict:
    f = features or {}
    h, w = _num(f.get("height_cm")), _num(f.get("weight_kg"))
    bmi = round(w / (h / 100) ** 2, 1) if h and w and h > 100 else None
    rate, slot_rates = _rates(f.get("meal_log"))
    avg = ((f.get("nutrition") or {}).get("avg_day") or {}) if isinstance(f.get("nutrition"), dict) else {}
    ctx = {k: _num(f.get(k)) for k in ("age", "female", "mna_risk", "kmbi_score", "kmbi_max", "dx_diabetes", "dx_hypertension",
                                         "dx_dementia", "dx_depression", "sbp", "dbp", "mmse", "gds", "texture_level",
                                         "eating_dependence", "pref_meat", "pref_seafood", "pref_vegetable", "pref_fruit",
                                         "cmt_portion", "cmt_seasoning", "cmt_diabetic")}
    ctx.update({
        "height_cm": h, "weight_kg": w, "bmi": bmi,
        "diseases": [str(x) for x in (f.get("diseases") or [])],
        "medications": [str(x) for x in (f.get("medications") or [])],
        "chewing_difficulty": bool(_num(f.get("chewing_difficulty"), 0)),
        "swallowing_difficulty": bool(_num(f.get("swallowing_difficulty"), 0)),
        "meal_form": f"{rice}/{side}",
        "avg_day": avg, "na_day": _num(avg.get("na")), "k_day": _num(avg.get("k")),
        "intake_rate": rate, "slot_rates": slot_rates,
        "med_records": med_records or [], "allergy_records": allergy_records or [],
    })
    return ctx


def _slice(ctx: dict, keys) -> dict:
    return {k: ctx.get(k) for k in keys}


def resolve_constraints(specs: list, energy: float) -> dict:
    """기준 목록 → 끼니 기준 {필드: {value, agent, source, others}}.
    같은 영양소는 더 엄격한 값. 열량 비율(%E) 기준은 energy(목표 열량)로 g 환산
    → 목표 열량이 바뀌면 이 함수를 다시 부르면 된다 (Stage 2 에서 사용)"""
    chosen = {}
    for s in specs:
        if isinstance(s, dict):
            s = ConstraintSpec(**s)
        fld = FIELDS.get((s.nutrient, s.bound))
        if not fld:
            continue
        v = s.resolve(energy)
        cur = chosen.get(fld)
        cand = {"agent": s.agent, "source": s.source, "value": v}          # 후보 (KDRI 공통 · 식단형 규격 · 학회 지침 …)
        stricter = cur is None or (v < cur["value"] if s.bound == "max" else v > cur["value"])
        if stricter:
            chosen[fld] = {"value": v, "agent": s.agent, "source": s.source, "unit": s.unit,
                           "others": (cur["others"] + [cur["agent"]]) if cur else [],
                           "candidates": (cur["candidates"] if cur else []) + [cand]}
        else:
            cur["others"].append(s.agent)
            cur["candidates"].append(cand)
    return chosen


def kdri_specs(age: int) -> list:
    """[2026-11-10] 공통 기준 (KDRI) — 모든 어르신. 최적화(base_standard.py)와 같은 값 + 나이별 나트륨"""
    from ..sodium_config import meal_sodium_max_for_age
    from .domain import rules
    out = []
    for k, r in rules()["constraints"].items():
        if k.startswith("kdri.") and r.get("unit") in ("abs", "pctE"):
            kw = {"unit": "pctE", "kcal_per_g": r["kcal_per_g"]} if r["unit"] == "pctE" else {}
            out.append(ConstraintSpec(r["nutrient"], r["bound"], r["value"], source=r["source"], agent="kdri", **kw))
    # 나이별 나트륨 만성질환위험감소섭취량(CDRR) ÷ 3
    out.append(ConstraintSpec("sodium", "max", meal_sodium_max_for_age(int(age or 80)), source="KDRI2025", agent="kdri"))
    return out


def synthesize(assessments: list, age: int) -> dict:
    """에이전트 결과 → 개인 영양 기준(출처 포함) · 피할 식재료 · 우선순위 문제 목록
    [2026-11-10] 영양 기준 = KDRI 공통 + 질환별(식단형 식사관리식품 규격 · 학회 진료지침) → 영양소마다 가장 엄격한 값"""
    body = next(a for a in assessments if a.agent == "body")
    agent_specs = [s for a in assessments if a.active for s in a.constraints]
    # [2026-11-10] 개인화 기준: 질환(식단형 규격·학회 지침)이 정한 영양소는 그 값들만, 나머지는 KDRI.
    #   나트륨은 나이별 KDRI 도 함께 비교 (질환자가 일반 어르신보다 짜게 먹지 않도록)
    by_disease = {(s.nutrient, s.bound) for s in agent_specs if s.agent in DISEASE_AGENTS}
    kd = [s for s in kdri_specs(age) if (s.nutrient, s.bound) not in by_disease or s.nutrient == "sodium"]
    specs = kd + agent_specs
    # 목표 열량: ESPEN 30 kcal/kg(비만은 조정체중) ÷ 3 을 열량 범위(질환 500~800, 그 외 450~700) 안으로.
    #   체중이 없으면 BMI 점수로 범위 안에서 계산 (예전 방식)
    rng = resolve_constraints([s for s in specs if s.nutrient == "energy"], 0)
    lo, hi = (rng.get("energy_min") or {}).get("value"), (rng.get("energy_max") or {}).get("value")
    e = body.outputs.get("energy_by_weight")
    score = body.outputs.get("energy_score")
    if e is None:
        e = round(lo + score * (max(hi, lo) - lo), 0) if (lo and hi and score is not None) else body.outputs["target_energy"]
    if lo and hi:
        e = min(max(e, lo), hi)
    if e != body.outputs["target_energy"]:
        body.summary = body.summary.replace(f"목표 열량 {body.outputs['target_energy']:.0f}", f"목표 열량 {e:.0f}", 1)
    chosen = resolve_constraints(specs, e)
    avoid = [x for a in assessments if a.active for x in a.avoid]
    # 우선순위: Level 1(안전성) 먼저, 그 안과 Level 2(영양 중재)는 S 순
    #   [2026-11-10] Level 2 는 파레토 묶음(심각도·시급성·개선 가능성) → 같은 묶음 안에서 S 순
    issues = rank_priorities([i.to_dict() for a in assessments if a.active for i in a.issues])
    return {"target_energy": e, "constraints": chosen, "specs": [x.to_dict() for x in specs],
            "avoid": [x.to_dict() for x in avoid], "priorities": issues,
            "notes": [n for a in assessments if a.active for n in a.notes]}


def _run(ag, sub, judge, ctx):
    a = ag.assess(sub)
    if judge and a.active:
        judge(ag, sub, a, ctx)        # LLM 영역 전문가: 같은 맥락(sub)만 보고 근거 검색 후 판단을 정제 (실패해도 규칙 결과 유지)
    return a


def assess_residents(contexts: dict, max_workers: int = 8, judge=None) -> dict:
    """contexts: {elderly_id: ctx} → {elderly_id: {"agents": [...], "synth": {...}}}
    모든 (어르신 × 에이전트) 평가를 병렬로 실행. 에이전트는 서로의 결과를 보지 않는다.
    judge(agent, sub_ctx, assessment, full_ctx) — 있으면 규칙 평가 직후 같은 작업 안에서 LLM 판단을 덧붙인다 (llm_agent.judge)
    [2026-11-11] langgraph 가 설치돼 있으면 LangGraph 워크플로우(agents/graph.py, 1단계까지)로 실행 — 7개 영역 노드 병렬.
                 DIET_LANGGRAPH=0 이면 아래 스레드 풀 경로"""
    import os
    from . import graph as G
    if G.available() and os.getenv("DIET_LANGGRAPH", "1") != "0":
        r = G.run(contexts, judge=judge, upto="stage1", max_concurrency=max_workers)
        return {eid: {"agents": v["agents"], "synth": v["synth"]} for eid, v in r.items()}
    jobs = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for eid, ctx in contexts.items():
            for ag in AGENTS:
                sub = _slice(ctx, ag.CONTEXT_KEYS)
                if ag.NAME == "body" or ag.applicable(sub):
                    jobs[(eid, ag.NAME)] = ex.submit(_run, ag, sub, judge, ctx)
                else:
                    jobs[(eid, ag.NAME)] = None
        out = {}
        for eid, ctx in contexts.items():
            res = []
            for ag in AGENTS:
                fut = jobs[(eid, ag.NAME)]
                if fut is None:
                    a = ag._a(active=False, summary="해당 없음")
                else:
                    try:
                        a = fut.result()
                    except Exception as e:                    # 한 에이전트 오류가 전체를 멈추지 않게
                        a = ag._a(active=False, summary=f"평가 오류: {e}")
                res.append(a)
            out[eid] = {"agents": res, "synth": synthesize(res, ctx.get("age") or 80)}
    return out


def to_json(result: dict) -> dict:
    return {eid: {"agents": [a.to_dict() for a in v["agents"]], "synth": v["synth"]} for eid, v in result.items()}


def matches_avoid(ingredients: dict, name: str, avoid: list) -> list:
    """메뉴(재료 g) 또는 제품(이름)에 걸리는 피할 식재료 → [사유]"""
    hits = []
    for a in avoid or []:
        kws = a["keywords"]
        if ingredients:
            g = sum(v for ing, v in ingredients.items() if any(k in ing for k in kws))
            if g > 0 and g >= (a.get("min_g") or 0):
                hits.append(a["reason"])
                continue
        # 재료 정보가 없는 제품은 이름으로 판단 (양을 모르므로 min_g 규칙도 보수적으로 제외)
        if name and not ingredients and any(k in name for k in kws):
            hits.append(a["reason"])
    return hits
