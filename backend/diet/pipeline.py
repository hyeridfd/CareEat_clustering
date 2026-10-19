# -*- coding: utf-8 -*-
"""
pipeline.py  ─  맞춤 식단 설계 파이프라인 (서버판, Neo4j·LangGraph 없이)
=====================================================================
에이전트(agent_substitute_1018)와 같은 순서·같은 규칙으로 동작한다.

  ① 어르신 프로파일   care_assessments.features(질환·키·체중·나이·식사형태) + 식단 설정(매운 음식)
  ② 후보 메뉴         data/pool.json(에이전트 후보 풀 스냅샷) → 나트륨 보정·표준 배식 비율
                      → 시설 선호 점수 → 주의 재료 감점 → 한 그릇·다진찬 속성
  ③ 일반식 최적화     NSGA-II(nsga2.py) 28일 × 18칸, f1 영양 · f2 예산+재고 · f3 다양성+선호 · f4 패턴
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


def build_profiles(residents: list, assessments: dict, settings: dict) -> tuple[list, dict, list]:
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
        if any("고혈압" in d for d in dx) or _num(f.get("dx_hypertension"), 0) == 1:
            diseases.append("고혈압")
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
        profiles.append(p)
        meta[eid] = {"display_name": name, "type": p.disease_type_label + ("·치매" if dementia else ""),
                     "texture": f"{rice}/{side}", "diseases": diseases, "dementia": dementia,
                     "no_spicy": p.no_spicy, "bmi": bmi, "age": age, "sex": "여" if female else "남",
                     "target_energy": p.target_energy, "sodium_max": p.constraint.sodium_max}
    return profiles, meta, skipped


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
def menu_records(problem: MealPlanProblem, chrom) -> list:
    pool = problem.pool
    rows = []
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


def plan_metrics(problem, chrom, F_front=None, F_all=None, inv_model=None) -> dict:
    f = problem._eval_one(chrom)
    menus = problem.effective_menus(chrom)
    out = {
        "selected": {"f1_영양위반": round(f[0], 4), "f2_예산·재고": round(f[1], 4),
                     "f3_다양성·선호": round(-f[2], 2), "f4_패턴위반": round(f[3], 4)},
        "nutrition_breakdown": {k: round(v, 4) for k, v in problem.nutrition_breakdown(menus).items() if v >= 0.001},
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
# ④⑤ 개인화 · 배식
# ══════════════════════════════════════════════════════════════
def personalize_and_serve(pool, records, profiles, meta, inv_model=None, product_scores=None, progress=None,
                          inventory=None) -> dict:
    from . import substitute_agent as SA
    from .meal_form import build_meal_form
    from .serving_agent import serving_agent

    key = uuid.uuid4().hex[:8]
    registry.put(f"patients_{key}", profiles)
    registry.put(f"constraint_{key}", BaseStandard())
    SA._PROD_SCORES = dict(product_scores or {})          # 시설 제품 선호 점수 (없으면 0.7)
    try:
        if progress: progress("식사형태(죽·백김치) 적용")
        mf = build_meal_form(records, profiles, inv_model)
        state = {"df_menu_records": records, "df_menu_columns": list(records[0].keys()), "pool": pool,
                 "patients_key": f"patients_{key}", "constraint_key": f"constraint_{key}",
                 "meal_form_overrides": mf["overrides"], "meal_form_items": mf["items"], "preference_weights": {}}
        if progress: progress("대체찬 산출")
        sub = SA.substitute_agent(state)
        personal = {k: dict(v) for k, v in mf["overrides"].items()}
        for k, ch in (sub.get("personal_menus") or {}).items():
            personal.setdefault(k, {}).update(ch)
        sub_products = {**(sub.get("sub_products") or {}), **mf["items"]}
        if progress: progress("개인별 배식량 계산 0/%d끼" % len(records))
        cb = (lambda i, n: progress(f"개인별 배식량 계산 {i}/{n}끼")) if progress else None
        serving = serving_agent({**state, "personal_menus": personal, "sub_products": sub_products,
                                 "progress_cb": cb})["serving_map"]
    finally:
        registry._STORE.pop(f"patients_{key}", None)
        registry._STORE.pop(f"constraint_{key}", None)

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
                                                    "예상나트륨", "예상탄수화물", "열량OK", "단백질OK", "나트륨OK", "칸별비율", "조정결과")}})
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
        per_res[eid] = dict(c)
        for k2, v2 in c.items():
            tot[k2] += v2

    # ── 대체찬 지침 · 발주 · 제품 합계 · 입소자별 요약 ──
    subs = []
    for s in sub.get("substitutions") or []:
        subs.append({**s, "elderly_id": s["name"], "display_name": meta.get(s["name"], {}).get("display_name", s["name"])})
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
            q["사유"][w.split(":")[0]] += 1
    reason_tot = defaultdict(int)
    for s in subs:
        for w in s["reason"].split(" / "):
            reason_tot[w.split(":")[0]] += 1

    residents = []
    for p in profiles:
        m = meta[p.name]
        residents.append({"elderly_id": p.name, **m, "substitutions": sub_by_res[p.name]["건수"],
                          "reasons": dict(sub_by_res[p.name]["사유"]), "serving": per_res.get(p.name, {})})
    # ── 주간 발주 (식재료 · 고령친화식품) ──
    from .purchase import weekly_purchase
    if progress: progress("주간 발주량 계산")
    products = json.load(open(os.path.join(DATA_DIR, "products.json"), encoding="utf-8"))
    purchase = weekly_purchase(dict(by_res), pool, subs, products, inventory, n_days=N_DAYS)
    daily_usage = purchase.pop("daily_usage", {})

    return {
        "purchase": purchase, "daily_usage": daily_usage,
        "substitutions": subs, "orders": order_rows, "product_totals": total_rows, "porridge": mf["porridge"],
        "residents": residents, "servings": dict(by_res),
        "serving_summary": dict(tot), "substitution_reasons": dict(reason_tot),
    }


# ══════════════════════════════════════════════════════════════
# 전체 실행
# ══════════════════════════════════════════════════════════════
def run_design(residents, assessments, settings, inventory=None, preference=None,
               preset="standard", seed=42, progress=None) -> dict:
    """→ 결과 dict (menu, metrics, personalization…)"""
    from .inventory import InventoryModel
    with LOCK:
        say = progress or (lambda *_: None)
        say("어르신 프로파일 생성")
        profiles, meta, skipped = build_profiles(residents, assessments, settings)
        if not profiles:
            raise ValueError("식단 설계에 쓸 어르신이 없습니다. 진단 화면에서 평가를 먼저 실행하세요.")
        pref = preference or {}
        pool = load_pool(pref.get("pool_scores"))
        inv = inventory_from_rows((inventory or {}).get("items"), (inventory or {}).get("start_date"))
        inv_model = InventoryModel(pool, inv, len(profiles)) if inv else None
        problem = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, inventory=inv_model)
        pop, gen = PRESETS.get(preset, PRESETS["standard"])
        say(f"일반식 최적화 (개체 {pop} · 세대 {gen})")
        t0 = dt.datetime.now()
        Xf, Ff, Xa, Fa = nsga2.minimize(problem, pop_size=pop, n_gen=gen, seed=seed,
                                        progress=lambda g, n, f1: say(f"일반식 최적화 {g}/{n}세대 · f1 {f1:.3f}"))
        best_i, rule = select_balanced(Ff)
        chrom = Xf[best_i]
        records = menu_records(problem, chrom)
        metrics = plan_metrics(problem, chrom, Ff, Fa, inv_model)
        metrics["selection_rule"] = rule
        metrics["optimize_sec"] = round((dt.datetime.now() - t0).total_seconds(), 1)
        metrics["preset"] = {"name": preset, "pop": pop, "gen": gen}
        pers = personalize_and_serve(pool, records, profiles, meta, inv_model, pref.get("product_scores"), say, inv)
        return {"menu": records, "metrics": metrics, "skipped": skipped, "n_residents": len(profiles),
                "inventory_used": inv is not None, "preference_used": bool(pref.get("pool_scores")), **pers}


def redo_personalization(menu: list, residents, assessments, settings, inventory=None, preference=None, progress=None):
    """영양사가 식단표를 고친 뒤: 지표·개인화·배식만 다시 계산 (최적화는 다시 돌리지 않음)"""
    from .inventory import InventoryModel
    with LOCK:
        profiles, meta, skipped = build_profiles(residents, assessments, settings)
        pref = preference or {}
        pool = load_pool(pref.get("pool_scores"))
        inv = inventory_from_rows((inventory or {}).get("items"), (inventory or {}).get("start_date"))
        inv_model = InventoryModel(pool, inv, len(profiles)) if inv else None
        problem = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, inventory=inv_model)
        chrom = records_to_chrom(problem, menu)
        records = menu_records(problem, chrom)
        metrics = plan_metrics(problem, chrom, None, None, inv_model)
        pers = personalize_and_serve(pool, records, profiles, meta, inv_model, pref.get("product_scores"), progress, inv)
        return {"menu": records, "metrics": metrics, "skipped": skipped, "n_residents": len(profiles), **pers}


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
