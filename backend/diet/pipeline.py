# -*- coding: utf-8 -*-
"""
pipeline.py  ─  맞춤 식단 설계 파이프라인 (서버판, Neo4j·LangGraph 없이)
=====================================================================
에이전트(agent_substitute_1018)와 같은 순서·같은 규칙으로 동작한다.

  ① 어르신 프로파일   care_assessments.features(질환·키·체중·나이·식사형태) + 식단 설정(매운 음식)
  ② 후보 메뉴         data/pool.json(에이전트 후보 풀 스냅샷) → 나트륨 보정·표준 배식 비율
                      → 시설 선호 점수 → 주의 재료 감점 → 한 그릇·다진찬 속성
  ③ 일반식 최적화     NSGA-II(nsga2.py) 28일 × 18칸, f1 영양 · f2 비용(예산+재고) · f3 다양성(반복·편중) · f4 조화(한 끼 내부 조합·선호·규칙)
                      → 균형 해 선택(moo_metrics.select_balanced)
  ④ 개인화           식사형태(죽·백김치, meal_form.py) + 질환 맞춤 대체찬(substitute_agent.py)
  ⑤ 배식량           균형 배식 + 현장 단계(serving_agent.py)
  ⑥ 집계             대체찬 지침 · 발주 · 죽 계획 · 배식 기준 충족

시설 선호도(facility_preference.py)는 별도 함수 refresh_preference()로 잔반 기록에서 갱신한다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
import uuid
from collections import defaultdict

import numpy as np
import pandas as pd

from . import registry
from . import nsga2
from .base_standard import BaseStandard
from .ingredient_policy import apply_caution_penalty
from .meal_rules import apply_meal_rules, effective_meal
from .moo_metrics import evaluate_front, select_balanced
from .patient_profile_final import PatientProfile, Sex, KidneyType
from .problem import MealPlanProblem, DAILY_SLOTS, N_DAYS, N_SLOTS
from .sodium_config import apply_sodium_adjustment

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
POOL_JSON = os.path.join(DATA_DIR, "pool.json")
LOCK = threading.Lock()          # 한 번에 한 설계만 (메모리·전역 상태 보호)

PRESETS = {                       # 실행 강도 (개체 수, 세대 수)
    "quick":    (100, 80),
    "standard": (150, 150),
    "thorough": (200, 250),
}
MEAL_NAMES = ["아침", "점심", "저녁"]
SLOT_CATS = [("밥", "밥"), ("국", "국"), ("주찬", "주찬"), ("부찬1", "부찬"), ("부찬2", "부찬"), ("김치", "김치")]
SURVEY_SLOT = {"밥/죽": "밥", "국/탕": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "김치1": "김치", "김치2": "김치"}
BUDGET_PER_MEAL = 10000


# ══════════════════════════════════════════════════════════════
# ① 어르신 프로파일
# ══════════════════════════════════════════════════════════════
def _num(v, default=None):
    try:
        f = float(v)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def parse_meal_form(resident_form: str | None, survey_type: str | None) -> tuple[str, str]:
    """('밥'|'죽', '일반찬'|'다진찬'|'갈찬')
    resident_form 예: '일반밥/다진찬', '죽/일반찬', '갈죽/갈찬'  ·  survey_type 예: '일반식', '다진식', '갈은식(믹서식)'"""
    f = str(resident_form or "")
    if "/" in f:
        rice, side = f.split("/", 1)
        rice = "죽" if ("죽" in rice) else "밥"
        side = "갈찬" if "갈" in side else "다진찬" if "다진" in side else "일반찬"
        return rice, side
    t = str(survey_type or "")
    if "갈" in t or "유동" in t:
        return "죽", "갈찬"
    if "다진" in t:
        return "밥", "다진찬"
    return "밥", "일반찬"


USE_KIDNEY = False


def build_profiles(residents: list, assessments: dict, settings: dict, ehr: dict | None = None) -> tuple[list, dict, list]:
    """→ (PatientProfile 목록, {elderly_id: 표시 정보}, 제외 목록)
    PatientProfile.name 에는 elderly_id 를 넣는다 (이름 중복 방지)."""
    profiles, meta, skipped = [], {}, []
    for r in residents:
        eid = r["id"]
        name = r.get("name") or r.get("elderly_name") or eid
        a = assessments.get(eid)
        f = (a or {}).get("features") or {}
        if not a:
            skipped.append({"elderly_id": eid, "display_name": name, "reason": "평가 기록 없음"})
            continue
        dx = [str(x) for x in (f.get("diseases") or [])]
        diseases = []
        if any("당뇨" in d for d in dx) or _num(f.get("dx_diabetes"), 0) == 1:
            diseases.append("당뇨병")
        from .agents.domain import bp_hypertension
        htn_by_bp = False
        if any("고혈압" in d for d in dx) or _num(f.get("dx_hypertension"), 0) == 1:
            diseases.append("고혈압")
        elif bp_hypertension(f.get("sbp"), f.get("dbp")):
            # [2026-11-09] 진단 기록이 없어도 수축기 ≥140 또는 이완기 ≥90 mmHg 이면 고혈압으로 판단
            diseases.append("고혈압")
            htn_by_bp = True
        # 1차 버전: 신장질환은 없는 것으로 가정 (당뇨·고혈압·치매만 반영). 켜려면 USE_KIDNEY=True
        kidney = USE_KIDNEY and any("신장" in d for d in dx)
        if kidney:
            diseases.append("신장질환")
        dementia = any("치매" in d for d in dx) or _num(f.get("dx_dementia"), 0) == 1
        h, w = _num(f.get("height_cm")), _num(f.get("weight_kg"))
        bmi = round(w / (h / 100) ** 2, 1) if h and w and h > 100 else 22.0
        female = _num(f.get("female"), 1) == 1
        age = int(_num(f.get("age"), 80) or 80)
        rice, side = parse_meal_form(r.get("meal_form"), f.get("meal_form"))
        st = settings.get(eid) or {}
        p = PatientProfile(
            name=eid, sex=Sex.FEMALE if female else Sex.MALE, age=age, bmi=bmi,
            waist_cm=82.0 if female else 87.0, diseases=diseases, budget_per_meal=BUDGET_PER_MEAL,
            kidney_type=KidneyType.NON_DIALYSIS if kidney else None,
            meal_texture_rice=rice, meal_texture_side=side,
            dementia=dementia, no_spicy=bool(st.get("no_spicy")),
        )
        # [다중 에이전트] 영역별 에이전트가 쓸 어르신 전체 정보 (에이전트마다 필요한 부분만 잘라서 전달)
        from .agents import build_context
        e_ = (ehr or {}).get(eid) or {}
        p.context = build_context(r, f, rice, side, e_.get("medications"), e_.get("allergies"))
        profiles.append(p)
        meta[eid] = {"display_name": name, "type": p.disease_type_label + ("·치매" if dementia else ""),
                     "texture": f"{rice}/{side}", "diseases": diseases, "dementia": dementia, "htn_by_bp": htn_by_bp,
                     "no_spicy": p.no_spicy, "bmi": bmi, "age": age, "sex": "여" if female else "남",
                     "target_energy": p.target_energy, "sodium_max": p.constraint.sodium_max}
    return profiles, meta, skipped


USE_AGENT_CONSTRAINTS = True     # True: 에이전트 종합 기준을 개인 기준으로 사용 (숫자는 기존과 같음 · 출처 기록)


def apply_agents(profiles: list, progress=None, refiner: str = "off", prev: dict | None = None,
                 agent_mode: str = "rule") -> dict:
    """[Stage 1] 관리자 에이전트 → 영역별 에이전트 7종 병렬 독립 평가 → 종합
    [Stage 2] refiner="llm" 이면 LLM 임상 영양사가 어르신별로 충돌 조정·기준 조정·우선순위 재평가 (agents/refine.py)
              prev = 이전 설계의 {elderly_id: refine 결과} — 입력이 같으면 다시 호출하지 않고 재사용 (영양사 수정본)
    [Stage 3] 우선순위 S(j) → p.priority_weights → 대체찬 배분 가중치 (substitute_agent.priority_weights)
    · 개인 영양 기준(p.constraint) = 종합 기준 (같은 영양소는 더 엄격한 값, 출처 에이전트 기록)
    · p.avoid = 약물·알레르기로 피할 식재료 (대체찬·제품 선택의 절대 조건)
    → {elderly_id: {agents, synth}} (결과 저장용)"""
    from .agents import assess_residents, to_json
    from .patient_profile_final import NutritionConstraint
    ctxs = {p.name: getattr(p, "context", {}) or {} for p in profiles}
    judge = None
    if agent_mode == "llm":
        # [Stage 1 + RAG] 영역마다 근거 문단을 검색하고 LLM 영역 전문가가 판단을 정제 (agents/llm_agent.py)
        from .agents.llm_agent import make_judge
        judge = make_judge()
    import os
    from .agents import graph as G
    if G.available() and os.getenv("DIET_LANGGRAPH", "1") != "0":
        # [2026-11-11] LangGraph 워크플로우: START → 7개 영역 노드(병렬) → 1단계 종합 → (2단계 정제) → 3단계 종합·안전성 → END
        #   어르신마다 그래프 1회, 여러 명은 batch 로 동시에 (agents/graph.py)
        if progress: progress("LangGraph 에이전트 워크플로우" + (" · AI 영역 전문가(근거 검색)" if judge else "")
                              + (" · AI 임상 영양사" if refiner == "llm" else ""))
        gr = G.run(ctxs, judge=judge, refiner=refiner, prev=prev)
        res = {eid: {"agents": v["agents"], "synth": v["synth"]} for eid, v in gr.items()}
        refs = {eid: v["refine"] for eid, v in gr.items() if refiner == "llm" and v["refine"]}
        return _finish_agents(profiles, res, refs)
    if progress: progress("영역별 에이전트 평가" + (" · AI 영역 전문가(근거 검색)" if judge else ""))
    res = assess_residents(ctxs, judge=judge)
    stage1 = {eid: json.loads(json.dumps(v["synth"], default=str)) for eid, v in res.items()}   # 3단계 잠금·범위 기준점
    refs = {}
    if refiner == "llm":
        from .agents.refine import apply_refine, refine_all
        refs = refine_all(ctxs, res, prev=prev, progress=progress)
        for eid in res:
            res[eid]["synth"] = apply_refine(res[eid]["synth"], refs.get(eid) or {})
            if refs.get(eid, {}).get("mode") == "llm":
                refs[eid] = {**refs[eid], "energy_rescaled": res[eid]["synth"].get("energy_rescaled") or []}
    # [3단계] 종합·안전성 검증: 안전성 → 우선순위(파레토) → 지침 충돌 조정 → 약물·질환 강제 제약 (agents/synthesis.py)
    #   충돌 전문가(LLM)는 AI 임상 영양사(refiner="llm")를 켰을 때만, 충돌이 확인된 어르신·충돌에만 호출
    from .agents.synthesis import finalize
    use_sp = refiner == "llm"
    if use_sp and progress:
        progress("종합·안전성 검증 (충돌별 질환 전문가)")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {eid: ex.submit(finalize, res[eid]["synth"], ctxs[eid], stage1[eid], res[eid]["agents"], None, use_sp)
                for eid in res}
        for eid, f in futs.items():
            res[eid]["synth"] = f.result()
    return _finish_agents(profiles, res, refs)


def _finish_agents(profiles: list, res: dict, refs: dict) -> dict:
    """종합 결과 → 어르신 프로필(개인 기준·목표 열량·피할 식재료·우선순위 가중치) + 저장용 JSON"""
    from .agents import to_json
    from .patient_profile_final import NutritionConstraint
    from .substitute_agent import priority_weights
    mismatch = []
    for p in profiles:
        syn = res[p.name]["synth"]
        new = NutritionConstraint(**{k: v["value"] for k, v in syn["constraints"].items()})
        old = p.constraint
        for k in vars(old):
            a_, b_ = getattr(old, k), getattr(new, k)
            if k in ("energy_min", "energy_max") and a_ is None:
                continue                                   # 기존: 질환 없으면 미지정(=500~800 기본)
            if (a_ or 0) != (b_ or 0) and abs((a_ or 0) - (b_ or 0)) > 0.01:
                mismatch.append((p.name, k, a_, b_))
        if USE_AGENT_CONSTRAINTS:
            p.constraint = new
            p.target_energy = syn["target_energy"]
        p.avoid = [a for a in syn["avoid"] if a.get("hard")]
        p.priorities = syn["priorities"]
        p.priority_weights = priority_weights(syn["priorities"])
    if mismatch:
        print(f"  [에이전트] 기존 기준과 다른 값 {len(mismatch)}건 (예: {mismatch[:3]})")
    out = to_json(res)
    for eid, v in out.items():
        p = next(x for x in profiles if x.name == eid)
        v["priority_weights"] = p.priority_weights
        if eid in refs:
            v["refine"] = refs[eid]
    return out


def _sync_meta(profiles, meta):
    """Stage 2 로 바뀐 목표 열량·나트륨 상한을 화면용 meta 에도 반영"""
    for p in profiles:
        if p.name in meta:
            meta[p.name]["target_energy"] = p.target_energy
            meta[p.name]["sodium_max"] = p.constraint.sodium_max


# ══════════════════════════════════════════════════════════════
# ② 후보 메뉴
# ══════════════════════════════════════════════════════════════
def load_pool(pool_scores: dict | None = None) -> dict:
    pool = json.load(open(POOL_JSON, encoding="utf-8"))
    pool = apply_sodium_adjustment(pool, verbose=False)
    if pool_scores:
        for ms in pool.values():
            for m in ms:
                if m["menu_name"] in pool_scores:
                    m["preference_score"] = pool_scores[m["menu_name"]]
    pool = apply_caution_penalty(pool, verbose=False)
    return apply_meal_rules(pool, verbose=False)


def inventory_from_rows(items: list, start_date) -> dict | None:
    """diet_inventory.items [{식재료명, 재고량(g), 유통기한}] → inventory.InventoryModel 입력"""
    rows = [x for x in (items or []) if str(x.get("식재료명") or "").strip() and _num(x.get("재고량(g)"), 0) > 0]
    if not rows:
        return None
    start = pd.to_datetime(start_date).date() if start_date else dt.date.today()
    df = pd.DataFrame(rows)
    df["식재료명"] = df["식재료명"].astype(str).str.strip()
    df["재고량(g)"] = pd.to_numeric(df["재고량(g)"], errors="coerce").fillna(0)
    exp = pd.to_datetime(df.get("유통기한"), errors="coerce")
    df["남은일수"] = [(e.date() - start).days if pd.notna(e) else N_DAYS + 1 for e in exp]
    df = df.groupby("식재료명", as_index=False).agg({"재고량(g)": "sum", "남은일수": "min"})
    return {"items": df, "start": start}


# ══════════════════════════════════════════════════════════════
# ③ 일반식
# ══════════════════════════════════════════════════════════════
USE_HARMONY = True


def harmony_table(pool):
    """조화 점수표 (data/harmony/harmony_model.json 이 있을 때만)"""
    if not USE_HARMONY:
        return None
    from .harmony import HarmonyTable, enabled
    return HarmonyTable(pool) if enabled() else None


def menu_records(problem: MealPlanProblem, chrom) -> list:
    pool = problem.pool
    rows = []
    hs = problem.meal_harmony(chrom)
    for day in range(N_DAYS):
        base = day * N_SLOTS
        for mi, meal_name in enumerate(MEAL_NAMES):
            raw = [pool[cat][int(chrom[base + mi * 6 + s]) % len(pool[cat])] for s, (_, cat) in enumerate(SLOT_CATS)]
            meal = effective_meal(raw)
            row = {"일차": f"{day + 1}일", "끼니": meal_name}
            for (slot, _), m in zip(SLOT_CATS, meal):
                row[slot] = m["menu_name"]
            row["열량(kcal)"] = round(sum(m.get("energy", 0) or 0 for m in meal), 1)
            row["나트륨(mg)"] = round(sum(m.get("sodium", 0) or 0 for m in meal), 1)
            row["단백질(g)"] = round(sum(m.get("protein", 0) or 0 for m in meal), 1)
            row["비용(원)"] = round(sum(m.get("cost", 0) or 0 for m in meal))
            notes = [f"{m['menu_name']}({m.get('texture')})" for m in meal[1:] if m.get("texture") in ("부적합", "주의")]
            row["다진찬주의"] = " / ".join(notes) if notes else "-"
            if hs is not None:
                row["조화"] = round(float(hs[day * 3 + mi]), 3)
            rows.append(row)
    return rows


def records_to_chrom(problem: MealPlanProblem, records: list) -> np.ndarray:
    idx = {cat: {m["menu_name"]: i for i, m in enumerate(ms)} for cat, ms in problem.pool.items()}
    chrom = np.zeros(N_DAYS * N_SLOTS, dtype=int)
    order = {"아침": 0, "점심": 1, "저녁": 2}
    for r in records:
        d = int(re.sub(r"\D", "", str(r["일차"])) or 1) - 1
        mi = order.get(r["끼니"], 0)
        for s, (slot, cat) in enumerate(SLOT_CATS):
            chrom[d * N_SLOTS + mi * 6 + s] = idx[cat].get(r.get(slot), 0)
    return chrom


def _harmony_summary(problem, chrom):
    h = problem.meal_harmony(chrom)
    if h is None:
        return None
    from .harmony import load_model
    m = load_model()
    v = m.get("validation") or {}
    c = np.asarray(chrom, dtype=int).reshape(N_DAYS * 3, 6)
    n = [len(problem.pool[cat]) for cat in ("국", "주찬", "부찬")]
    sim, js = problem.harmony.style_similarity(c[:, 1] % n[0], c[:, 2] % n[1], c[:, 3] % n[2], c[:, 4] % n[2],
                                               np.tile(np.arange(3), N_DAYS))
    return {"mean": round(float(h.mean()), 3), "low_meals": int((h < 0.4).sum()),
            "style_similarity": round(sim, 3), "style_js": round(js, 4), "objective": round(problem.harmony_objective(chrom), 3),
            "model": {"facility": m.get("facility"), "n_meals": m.get("n_meals"), "period": m.get("period"),
                      "auc": v.get("auc"), "ref_real_mean": m.get("ref_real_mean"), "ref_random_mean": m.get("ref_random_mean")}}


def plan_metrics(problem, chrom, F_front=None, F_all=None, inv_model=None) -> dict:
    f = problem._eval_one(chrom)
    menus = problem.effective_menus(chrom)
    out = {
        "selected": {"f1_영양": round(f[0], 4), "f2_비용": round(f[1], 4),
                     "f3_다양성": round(f[2], 4), "f4_조화": round(f[3], 4)},
        "objective_parts": problem.objective_parts(chrom),
        "nutrition_breakdown": {k: round(v, 4) for k, v in problem.nutrition_breakdown(menus).items() if v >= 0.001},
        "harmony": _harmony_summary(problem, chrom),
        "pattern": problem.pattern_breakdown(chrom),
    }
    if F_front is not None and len(F_front):
        m = evaluate_front(F_front)
        out["front"] = {"hv": m["hv_norm"], "spacing": m["spacing"], "n_nondom": m["n_nondom"],
                        "f1_min": round(float(F_front[:, 0].min()), 4),
                        "f1_pass_rate": round(float((F_all[:, 0] <= 0.3).mean() * 100), 1) if F_all is not None else None}
    if inv_model is not None:
        U = inv_model.daily_usage_chrom(chrom, DAILY_SLOTS, N_SLOTS)
        out["inventory_unused"] = round(inv_model.unused_score(U), 3)
        rep = inv_model.report(U)
        out["inventory"] = json.loads(rep.to_json(orient="records", force_ascii=False))
    return out


# ══════════════════════════════════════════════════════════════
# [2026-10-28] 반복 메뉴 보정 — 최적화 뒤 남은 '3일 안 반복'을 같은 분류의 다른 메뉴로 바꿈
#   최적화(f4)는 반복을 벌점으로만 다뤄 영양(f1)과 맞바꿀 수 있으므로, 가까운 반복은 결정적으로 정리한다.
#   후보: 같은 분류 · 앞뒤 3일 안에 안 나온 메뉴 · 한그릇 여부 같음 · 다진찬 적합도가 나빠지지 않음
#   선택: 그날 영양 위반이 가장 적고(허용 +0.05) 비용·선호가 비슷한 메뉴
# ══════════════════════════════════════════════════════════════
REPAIR_WINDOW = 9          # 앞뒤 9끼(3일)
REPAIR_SLOTS  = (1, 2, 3, 4)   # 국 · 주찬 · 부찬1 · 부찬2 (김치는 종류가 적어 제외)
_TEX = {"적합": 0, "주의": 1, "부적합": 2}


def _day_violation(problem, menus, day):
    from .problem import MEAL_SETS, NUTRIENTS
    c = problem.constraint
    v, dsum = 0.0, {k: 0.0 for k in NUTRIENTS}
    dm = menus[day * N_SLOTS:(day + 1) * N_SLOTS]
    for slots in MEAL_SETS.values():
        mn = {k: sum((dm[s].get(k, 0) or 0) for s in slots) for k in NUTRIENTS}
        for k, val in mn.items():
            lo, hi = getattr(c, f"{k}_min", None), getattr(c, f"{k}_max", None)
            if lo and val < lo: v += 0.6 * (lo - val) / lo / 3
            if hi and val > hi: v += 0.6 * (val - hi) / hi / 3
            dsum[k] += val
    for k, val in dsum.items():
        lo, hi = getattr(c, f"daily_{k}_min", None), getattr(c, f"daily_{k}_max", None)
        if lo and val < lo: v += 0.4 * (lo - val) / lo
        if hi and val > hi: v += 0.4 * (val - hi) / hi
    return v


def repair_repeats(problem, chrom, window: int = REPAIR_WINDOW, tol: float = 0.05):
    """→ (보정한 염색체, [변경 기록])"""
    from .problem import WHITELIST
    chrom = np.array(chrom, dtype=int).copy()
    pool = problem.pool
    n_meals = N_DAYS * 3
    changes = []

    def names_at(menus, t):
        return [menus[t * 6 + k]["menu_name"] for k in range(1, 6)]

    menus = problem.effective_menus(chrom)
    for t in range(n_meals):
        day, mi = divmod(t, 3)
        for k in REPAIR_SLOTS:
            gi = day * N_SLOTS + mi * 6 + k
            cur = menus[t * 6 + k]
            nm = cur["menu_name"]
            if nm in WHITELIST or nm.startswith("-("):
                continue
            before = {n for u in range(max(0, t - window), t) for n in names_at(menus, u)}
            if nm not in before:
                continue
            near = {n for u in range(max(0, t - window), min(n_meals, t + window + 1)) for n in names_at(menus, u)}
            _, cat = DAILY_SLOTS[mi * 6 + k]
            base_v = _day_violation(problem, menus, day)
            best = None
            for j, cand in enumerate(pool[cat]):
                cn = cand["menu_name"]
                if cn in near or cn in WHITELIST or bool(cand.get("one_dish")) != bool(cur.get("one_dish")):
                    continue
                if _TEX.get(cand.get("texture"), 0) > _TEX.get(cur.get("texture"), 0):
                    continue
                trial = list(menus)
                trial[t * 6 + k] = cand
                v = _day_violation(problem, trial, day)
                key = (round(v, 4), abs((cand.get("cost") or 0) - (cur.get("cost") or 0)) / 1000,
                       -(cand.get("preference_score") or 0.7))
                if best is None or key < best[0]:
                    best = (key, j, cand, v)
            if best and best[3] <= base_v + tol:
                chrom[gi] = best[1]
                menus[t * 6 + k] = best[2]
                changes.append({"일차": f"{day + 1}일", "끼니": MEAL_NAMES[mi], "칸": ["밥", "국", "주찬", "부찬1", "부찬2", "김치"][k],
                                "기존": nm, "변경": best[2]["menu_name"], "영양위반_변화": round(best[3] - base_v, 4)})
    return chrom, changes


# ══════════════════════════════════════════════════════════════
# ④⑤ 개인화 · 배식
# ══════════════════════════════════════════════════════════════
def _reason_key(w: str) -> str:
    """대체 사유 문구 → 집계용 이름 ('안전(알레르기: 갑각류): 메뉴' → '안전(알레르기: 갑각류)')"""
    if w.startswith("안전(") and "):" in w:
        return w[:w.index("):") + 1]
    return w.split(":")[0]


def ps_begin(pool, records, profiles, inv_model=None, product_scores=None) -> dict:
    """[개인화·배식] 공용 상태 준비 — 시설 그래프(workflow.py)의 meal_form 노드가 시작, assemble 노드에서 정리"""
    from . import substitute_agent as SA
    key = uuid.uuid4().hex[:8]
    registry.put(f"patients_{key}", profiles)
    registry.put(f"constraint_{key}", BaseStandard())
    SA._PROD_SCORES = dict(product_scores or {})          # 시설 제품 선호 점수 (없으면 0.7)
    return {"key": key, "pool": pool, "records": records, "profiles": profiles, "inv_model": inv_model}


def ps_end(ps: dict):
    registry._STORE.pop(f"patients_{ps['key']}", None)
    registry._STORE.pop(f"constraint_{ps['key']}", None)


def ps_meal_form(ps: dict, progress=None) -> dict:
    """식사형태(죽·백김치 등) 적용"""
    from .meal_form import build_meal_form
    if progress: progress("식사형태(죽·백김치) 적용")
    records, key = ps["records"], ps["key"]
    mf = build_meal_form(records, ps["profiles"], ps["inv_model"])
    state = {"df_menu_records": records, "df_menu_columns": list(records[0].keys()), "pool": ps["pool"],
             "patients_key": f"patients_{key}", "constraint_key": f"constraint_{key}",
             "meal_form_overrides": mf["overrides"], "meal_form_items": mf["items"], "preference_weights": {}}
    return {**ps, "mf": mf, "state": state}


def ps_substitute(ps: dict, progress=None) -> dict:
    """개인 대체찬"""
    from . import substitute_agent as SA
    if progress: progress("대체찬 산출")
    mf = ps["mf"]
    sub = SA.substitute_agent(ps["state"])
    personal = {k: dict(v) for k, v in mf["overrides"].items()}
    for k, ch in (sub.get("personal_menus") or {}).items():
        personal.setdefault(k, {}).update(ch)
    sub_products = {**(sub.get("sub_products") or {}), **mf["items"]}
    return {**ps, "sub": sub, "personal": personal, "sub_products": sub_products}


def ps_serve(ps: dict, progress=None) -> dict:
    """개인 배식률"""
    from .serving_agent import serving_agent
    records = ps["records"]
    if progress: progress("개인별 배식량 계산 0/%d끼" % len(records))
    cb = (lambda i, n: progress(f"개인별 배식량 계산 {i}/{n}끼")) if progress else None
    serving = serving_agent({**ps["state"], "personal_menus": ps["personal"], "sub_products": ps["sub_products"],
                             "progress_cb": cb})["serving_map"]
    return {**ps, "serving": serving}


def personalize_and_serve(pool, records, profiles, meta, inv_model=None, product_scores=None, progress=None,
                          inventory=None) -> dict:
    """식사형태 → 대체찬 → 배식률 → 결과 정리 (시설 그래프 밖에서 쓸 때: 식단 수정 후 다시 계산 등)"""
    ps = ps_begin(pool, records, profiles, inv_model, product_scores)
    try:
        ps = ps_serve(ps_substitute(ps_meal_form(ps, progress), progress), progress)
    finally:
        ps_end(ps)
    return ps_assemble(ps, meta, progress, inventory)


def ps_assemble(ps: dict, meta: dict, progress=None, inventory=None) -> dict:
    """배식표·충족 요약·대체찬 지침·발주·어르신별 요약으로 정리"""
    pool, records, profiles = ps["pool"], ps["records"], ps["profiles"]
    serving, personal, sub, mf = ps["serving"], ps["personal"], ps["sub"], ps["mf"]

    # ── 개인 배식표 (어르신별) ──
    by_res = defaultdict(list)
    order = {"아침": 0, "점심": 1, "저녁": 2}
    rec_idx = {(r["일차"], r["끼니"]): r for r in records}
    for k, v in serving.items():
        eid, day, meal = k.split("||")
        base = rec_idx.get((day, meal), {})
        ch = personal.get(k, {})
        menus = {s: ch.get(s, base.get(s)) for s, _ in SLOT_CATS}
        by_res[eid].append({"일차": day, "끼니": meal, "메뉴": menus,
                            "대체": [s for s in ch if s not in ("밥", "김치")] , "식사형태변경": [s for s in ch if s in ("밥", "김치")],
                            **{x: v.get(x) for x in ("밥", "국", "주찬", "부찬1", "부찬2", "김치", "ratio", "예상열량", "예상단백질",
                                                    "예상나트륨", "예상탄수화물", "예상지방", "예상당류", "예상식이섬유", "예상칼륨",
                                                    "열량OK", "단백질OK", "나트륨OK", "식이섬유OK", "칼륨OK", "탄수화물OK", "칸별비율", "조정결과")}})
    for eid in by_res:
        by_res[eid].sort(key=lambda x: (int(re.sub(r"\D", "", x["일차"]) or 0), order.get(x["끼니"], 9)))

    # ── 배식 기준 충족 요약 ──
    tot = defaultdict(int)
    per_res = {}
    for eid, rows in by_res.items():
        c = defaultdict(int)
        for x in rows:
            c["끼니"] += 1
            c["열량OK"] += x["열량OK"] == "✅"; c["단백질OK"] += x["단백질OK"] == "✅"; c["나트륨OK"] += x["나트륨OK"] == "✅"
            c["조정불가"] += str(x["조정결과"]).startswith("조정불가")
            for k3 in ("식이섬유OK", "칼륨OK", "탄수화물OK"):          # [2026-11-10] 배식률 목표 영양소
                c[k3] += x.get(k3) == "✅"
        per_res[eid] = dict(c)
        for k2, v2 in c.items():
            tot[k2] += v2

    # ── 대체찬 지침 · 발주 · 제품 합계 · 입소자별 요약 ──
    subs = []
    for s in sub.get("substitutions") or []:
        subs.append({**s, "elderly_id": s["name"], "display_name": meta.get(s["name"], {}).get("display_name", s["name"])})
    # 배식량 조정까지 마친 그 끼니의 최종 영양 (배식 에이전트가 계산하는 열량·단백질·나트륨)
    srv_idx = {(eid, x["일차"], x["끼니"]): x for eid, rows in by_res.items() for x in rows}
    for s in subs:
        x = srv_idx.get((s["elderly_id"], s["day"], s["meal"]))
        if x and s.get("nut") is not None:
            s["nut"]["served"] = {"energy": x.get("예상열량"), "protein": x.get("예상단백질"), "sodium": x.get("예상나트륨"),
                                  "fiber": x.get("예상식이섬유"), "potassium": x.get("예상칼륨"), "carb": x.get("예상탄수화물"),
                                  "fat": x.get("예상지방"), "sugar": x.get("예상당류"),
                                  "result": x.get("조정결과"), "portions": x.get("칸별비율")}
    dn = lambda d: int(re.sub(r"\D", "", str(d)) or 0)
    subs.sort(key=lambda s: (dn(s["day"]), order.get(s["meal"], 9), s["display_name"]))
    orders = defaultdict(lambda: {"인분": 0, "총량(g)": 0.0})
    totals = defaultdict(lambda: {"인분": 0, "총량(g)": 0.0})
    for s in subs:
        o = orders[(s["day"], s["product"])]; o["인분"] += 1; o["총량(g)"] += s["grams"] or 0
        o["업체"] = s["maker"]; o["규격단계"] = s["stage"]
        t = totals[s["product"]]; t["인분"] += 1; t["총량(g)"] += s["grams"] or 0; t["업체"] = s["maker"]
    order_rows = [{"일차": d, "제품": p, **v, "총량(g)": round(v["총량(g)"])}
                  for (d, p), v in sorted(orders.items(), key=lambda x: (dn(x[0][0]), x[0][1]))]
    total_rows = [{"제품": p, **v, "총량(kg)": round(v["총량(g)"] / 1000, 2)}
                  for p, v in sorted(totals.items(), key=lambda x: -x[1]["인분"])]
    for t in total_rows:
        t.pop("총량(g)", None)
    sub_by_res = defaultdict(lambda: {"건수": 0, "사유": defaultdict(int)})
    for s in subs:
        q = sub_by_res[s["elderly_id"]]; q["건수"] += 1
        for w in s["reason"].split(" / "):
            q["사유"][_reason_key(w)] += 1
    reason_tot = defaultdict(int)
    for s in subs:
        for w in s["reason"].split(" / "):
            reason_tot[_reason_key(w)] += 1

    # 대체 판단 기준(개인 영양 기준)은 어르신마다 같으므로 대체찬마다 두지 않고 어르신 정보로 옮긴다 (결과 크기 절약)
    sub_limits = {}
    for s in subs:
        lim = (s.get("nut") or {}).pop("limits", None)
        if lim is not None:
            sub_limits.setdefault(s["elderly_id"], lim)
    residents = []
    for p in profiles:
        m = meta[p.name]
        residents.append({"elderly_id": p.name, **m, "substitutions": sub_by_res[p.name]["건수"],
                          "reasons": dict(sub_by_res[p.name]["사유"]), "serving": per_res.get(p.name, {}),
                          "sub_limits": sub_limits.get(p.name)})
    # ── 주간 발주 (식재료 · 고령친화식품) ──
    from .purchase import weekly_purchase
    if progress: progress("주간 발주량 계산")
    products = json.load(open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8"))
    purchase = weekly_purchase(dict(by_res), pool, subs, products, inventory, n_days=N_DAYS)
    daily_usage = purchase.pop("daily_usage", {})

    return {
        "purchase": purchase, "daily_usage": daily_usage,
        "safety_flags": [{**f_, "display_name": meta.get(f_["elderly_id"], {}).get("display_name", f_["elderly_id"])}
                         for f_ in (sub.get("safety_flags") or [])],
        "substitutions": subs, "orders": order_rows, "product_totals": total_rows, "porridge": mf["porridge"],
        "residents": residents, "servings": dict(by_res),
        "serving_summary": dict(tot), "substitution_reasons": dict(reason_tot),
    }


# ══════════════════════════════════════════════════════════════
# 전체 실행
# ══════════════════════════════════════════════════════════════
def run_design(residents, assessments, settings, inventory=None, preference=None,
               preset="standard", seed=42, progress=None, ehr=None, selector="llm", reviewer="llm",
               refiner="llm", agent_mode="rule") -> dict:
    """→ 결과 dict (menu, metrics, personalization…)
    selector = "llm" (파레토 후보 중 AI 영양사가 선택, 실패·미설정 시 규칙) | "rule" (균형점 규칙)
    reviewer = "llm" (AI 식단 검토자가 어색한 칸 교체 제안 → 코드 검증 후 반영) | off (검토 안 함)
    refiner  = "llm" (Stage 2 AI 임상 영양사 어르신별 종합 판단) | off (Stage 1 종합 규칙만)
    agent_mode = "llm" (Stage 1 영역 전문가가 근거 검색 후 판단·인용) | rule (규칙 선별만)"""
    # [2026-11-11] 전체 흐름 = LangGraph 시설 그래프 (diet/workflow.py) — 어르신 개인화는 Send 로 개인화 그래프(agents/graph.py)
    #   langgraph 가 없거나 DIET_LANGGRAPH=0 이면 같은 노드 함수를 순서대로 (계산 결과는 같음)
    from . import workflow as WF
    inp = {"residents": residents, "assessments": assessments, "settings": settings, "inventory": inventory,
           "preference": preference, "preset": preset, "seed": seed, "ehr": ehr, "selector": selector,
           "reviewer": reviewer, "refiner": refiner, "agent_mode": agent_mode}
    judge = None
    if agent_mode == "llm":
        from .agents.llm_agent import make_judge
        judge = make_judge()
    with LOCK:
        if WF.available() and os.getenv("DIET_LANGGRAPH", "1") != "0":
            return WF.run(inp, progress, judge=judge)
        return WF.run_sequential(inp, progress, judge=judge)


def redo_personalization(menu: list, residents, assessments, settings, inventory=None, preference=None, progress=None,
                         ehr=None, refiner="off", prev_assessments: dict | None = None, agent_mode="rule"):
    """영양사가 식단표를 고친 뒤: 지표·개인화·배식만 다시 계산 (최적화는 다시 돌리지 않음)
    prev_assessments = 고치기 전 설계의 assessments → Stage 2 결과를 그대로 재사용 (평가가 같으면 LLM 다시 안 부름)"""
    from .inventory import InventoryModel
    with LOCK:
        profiles, meta, skipped = build_profiles(residents, assessments, settings, ehr)
        prev = {k: v.get("refine") for k, v in (prev_assessments or {}).items() if isinstance(v, dict) and v.get("refine")}
        agent_json = apply_agents(profiles, progress, refiner, prev, agent_mode=agent_mode)
        _sync_meta(profiles, meta)
        pref = preference or {}
        pool = load_pool(pref.get("pool_scores"))
        inv = inventory_from_rows((inventory or {}).get("items"), (inventory or {}).get("start_date"))
        inv_model = InventoryModel(pool, inv, len(profiles)) if inv else None
        problem = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, inventory=inv_model, harmony=harmony_table(pool))
        chrom = records_to_chrom(problem, menu)
        records = menu_records(problem, chrom)
        metrics = plan_metrics(problem, chrom, None, None, inv_model)
        pers = personalize_and_serve(pool, records, profiles, meta, inv_model, pref.get("product_scores"), progress, inv)
        return {"menu": records, "metrics": metrics, "skipped": skipped, "n_residents": len(profiles),
                "assessments": agent_json, **pers}


# ══════════════════════════════════════════════════════════════
# 시설 선호도 (잔반 기록 → 메뉴·제품 점수)
# ══════════════════════════════════════════════════════════════
def waste_from_assessments(assessments: dict, residents: list) -> pd.DataFrame:
    """care_assessments.features.meal_log(목측 잔반 → 섭취율) → facility_preference 입력 표"""
    forms = {r["id"]: r.get("meal_form") for r in residents}
    rows = []
    for eid, a in assessments.items():
        f = (a or {}).get("features") or {}
        log = f.get("meal_log") or []
        try:
            base = pd.to_datetime(f.get("survey_start")).normalize().tz_localize(None)
        except Exception:
            base = pd.Timestamp.today().normalize()
        if pd.isna(base):
            base = pd.Timestamp.today().normalize()
        form = forms.get(eid) or f.get("meal_form") or ""
        for cell in log:
            if cell.get("meal") not in MEAL_NAMES:
                continue
            day = int(cell.get("day") or 1)
            for it in cell.get("items") or []:
                cat = SURVEY_SLOT.get(it.get("slot"))
                name = it.get("name")
                if not cat or not name or it.get("rate") is None:
                    continue
                name = re.sub(r"_HS$", "", str(name)).replace("죽:", "")
                rows.append({"일자": base + pd.Timedelta(days=day - 1), "식사": cell["meal"], "음식명": name,
                             "구분": cat, "섭취율": float(it["rate"]) / 100, "기존식사형태": form, "elderly_id": eid})
    return pd.DataFrame(rows)


def refresh_preference(assessments: dict, residents: list) -> dict:
    from . import facility_preference as FP
    from .substitute_agent import load_products
    with LOCK:
        waste = waste_from_assessments(assessments, residents)
        if waste.empty:
            raise ValueError("잔반(섭취율) 기록이 있는 평가가 없습니다. 영양 조사 후 평가를 실행하세요.")
        FP.MIN_RESIDENTS = 3
        raw = json.load(open(POOL_JSON, encoding="utf-8"))
        res = FP.fit_scores(raw, waste, load_products(), verbose=False)
        obs = res["obs"].copy()
        obs["시설점수"] = [res["pool"].get(n) for n in obs.index]
        try:
            cv = json.loads(FP.cross_validate(waste).to_json(orient="records", force_ascii=False))
        except Exception:
            cv = []
        served = obs.reset_index().rename(columns={"index": "음식명", "y": "관측섭취율", "n": "가중배식횟수"})
        served = served.rename(columns={served.columns[0]: "음식명"})
        report = {
            "n_records": int(len(waste)), "n_menus_observed": int(len(obs)),
            "n_residents": int(waste["elderly_id"].nunique()), "facility_mean": round(res["model"].mu, 3),
            "period": [str(waste["일자"].min().date()), str(waste["일자"].max().date())],
            "served": json.loads(served[["음식명", "구분", "배식횟수", "관측섭취율", "시설점수"]].round(3)
                                 .sort_values("시설점수").to_json(orient="records", force_ascii=False)),
            "effects": json.loads(res["model"].effects().to_json(orient="records", force_ascii=False)),
            "products": sorted([{"제품": k, "예측점수": v} for k, v in res["product"].items()], key=lambda x: -x["예측점수"]),
            "cv": cv,
        }
        return {"pool_scores": res["pool"], "product_scores": res["product"], "report": report}


def menu_options() -> dict:
    """식단표 수정용 후보 메뉴 목록 {카테고리: [메뉴명…]}"""
    pool = json.load(open(POOL_JSON, encoding="utf-8"))
    return {cat: sorted(m["menu_name"] for m in ms) for cat, ms in pool.items()}
