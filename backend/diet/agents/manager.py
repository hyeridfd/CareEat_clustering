# -*- coding: utf-8 -*-
"""관리자 에이전트 — 어르신 정보를 영역별로 나눠 도메인 에이전트에 병렬로 맡기고, 결과를 모은다

  NutriOrion Stage 1 (Parallel Independent Assessment) 에 해당:
    1) 어르신 1명의 전체 정보(ctx)를 만든다 — 평가 결과·기초조사·조사 기간 섭취·기록 탭(약·알레르기)
    2) 에이전트별로 CONTEXT_KEYS 만 잘라서 넘긴다 (맥락 격리: 다른 영역 정보를 보지 못함)
    3) 해당하는 에이전트만 활성화(applicable)하고, 모든 (어르신 × 에이전트)를 동시에 실행
    4) 종합(synthesize): 영양 기준은 같은 영양소끼리 더 엄격한 값 (출처 에이전트 기록),
       피할 식재료는 합치고, 문제는 S(j) 순으로 정렬
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .base import ConstraintSpec
from .domain import BodyAgent, CognitionAgent, DiabetesAgent, HypertensionAgent, IntakeAgent, OralAgent, _num
from .medication import MedicationAgent

AGENTS = [BodyAgent(), DiabetesAgent(), HypertensionAgent(), CognitionAgent(), OralAgent(), IntakeAgent(), MedicationAgent()]
SLOT_GROUP = {"밥": "밥", "죽": "밥", "국/탕": "국", "국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "부찬": "부찬",
              "김치1": "김치", "김치2": "김치", "김치": "김치"}
FIELDS = {("energy", "min"): "energy_min", ("energy", "max"): "energy_max", ("sugar", "max"): "sugar_max",
          ("protein", "min"): "protein_min", ("protein", "max"): "protein_max", ("fat", "min"): "fat_min",
          ("fat", "max"): "fat_max", ("sat_fat", "max"): "sat_fat_max", ("sodium", "max"): "sodium_max",
          ("potassium", "min"): "potassium_min", ("fiber", "min"): "fiber_min"}


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


def synthesize(assessments: list, age: int) -> dict:
    """에이전트 결과 → 개인 영양 기준(출처 포함) · 피할 식재료 · 우선순위 문제 목록"""
    from ..sodium_config import meal_sodium_max_for_age
    body = next(a for a in assessments if a.agent == "body")
    e = body.outputs["target_energy"]
    specs = [s for a in assessments if a.active for s in a.constraints]
    # 기본 기준: 나이별 나트륨 만성질환위험감소섭취량(CDRR) ÷ 3 — 모든 어르신
    specs.append(ConstraintSpec("sodium", "max", meal_sodium_max_for_age(int(age or 80)), source="KDRI2025", agent="base"))
    chosen = {}
    for s in specs:
        fld = FIELDS.get((s.nutrient, s.bound))
        if not fld:
            continue
        v = s.resolve(e)
        cur = chosen.get(fld)
        stricter = cur is None or (v < cur["value"] if s.bound == "max" else v > cur["value"])
        if stricter:
            chosen[fld] = {"value": v, "agent": s.agent, "source": s.source,
                           "others": (cur["others"] + [cur["agent"]]) if cur else []}
        elif cur:
            cur["others"].append(s.agent)
    avoid = [x for a in assessments if a.active for x in a.avoid]
    issues = sorted((i for a in assessments if a.active for i in a.issues), key=lambda i: -i.priority)
    return {"target_energy": e, "constraints": chosen, "avoid": [x.to_dict() for x in avoid],
            "priorities": [i.to_dict() for i in issues],
            "notes": [n for a in assessments if a.active for n in a.notes]}


def assess_residents(contexts: dict, max_workers: int = 8) -> dict:
    """contexts: {elderly_id: ctx} → {elderly_id: {"agents": [...], "synth": {...}}}
    모든 (어르신 × 에이전트) 평가를 병렬로 실행. 에이전트는 서로의 결과를 보지 않는다."""
    jobs = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for eid, ctx in contexts.items():
            for ag in AGENTS:
                sub = _slice(ctx, ag.CONTEXT_KEYS)
                if ag.NAME == "body" or ag.applicable(sub):
                    jobs[(eid, ag.NAME)] = ex.submit(ag.assess, sub)
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
