"""
serving_agent.py  ─  ServingAgent 노드 (개선 버전)
===================================================
배식량 산출 기준:
  ① 기본 배식량 = pool["weight"] (CandidateAgent Cypher sum(nutri_weight))
  ② 개인 배식 비율 = clipped_target_energy / 시설평균
     - target_energy: BMI + 허리둘레 기반 개인별 목표 열량
     - clipping: p.constraint.energy_min ~ energy_max (질환별 기준 반영)
"""

import pandas as pd
from . import registry
from .state import MealPlanState

SLOT_CATS = [
    ("밥",   "밥"),
    ("국",   "국"),
    ("주찬", "주찬"),
    ("부찬1","부찬"),
    ("부찬2","부찬"),
    ("김치", "김치"),
]

# ratio 안전 범위
RATIO_MIN = 0.6
RATIO_MAX = 1.3

# [2026-10-14] 나트륨 한도 반영 배식
#   · 반찬(국·주찬·부찬·김치)은 개인 끼니 나트륨 상한 안에서 배식
#   · 그만큼 모자란 열량은 나트륨이 거의 없는 밥으로 보충
SIDE_SLOTS      = ["국", "주찬", "부찬1", "부찬2", "김치"]
SIDE_RATIO_FLOOR = 0.8   # 반찬 비율 하한 (개인 ratio가 이보다 작으면 개인 ratio까지) → 단백질 보호
RICE_RATIO_MAX   = 1.5   # 밥 보충 상한


def _split_ratio(ratio_e: float, menu_by_slot: dict, sodium_cap) -> tuple:
    """열량 기준 ratio → (밥 비율, 반찬 비율)"""
    rice    = menu_by_slot.get("밥", {}) or {}
    rice_e  = rice.get("energy", 0) or 0
    rice_na = rice.get("sodium", 0) or 0
    side_e  = sum((menu_by_slot.get(s, {}) or {}).get("energy", 0) or 0 for s in SIDE_SLOTS)
    side_na = sum((menu_by_slot.get(s, {}) or {}).get("sodium", 0) or 0 for s in SIDE_SLOTS)

    # 반찬 비율: 나트륨 상한을 넘지 않는 범위 (단, 하한 보장)
    r_side = ratio_e
    if sodium_cap and side_na > 0:
        r_na   = (sodium_cap - rice_na * ratio_e) / side_na
        floor  = min(ratio_e, SIDE_RATIO_FLOOR)
        r_side = min(ratio_e, max(r_na, floor))

    # 밥 비율: 반찬을 줄인 만큼의 열량을 보충
    r_rice = ratio_e
    if r_side < ratio_e and rice_e > 0:
        target = ratio_e * (rice_e + side_e)
        r_rice = (target - side_e * r_side) / rice_e
        r_rice = max(ratio_e, min(RICE_RATIO_MAX, r_rice))
    return round(r_rice, 3), round(r_side, 3)


# ══════════════════════════════════════════════════════════════
# [2026-10-19] 균형 배식 (BALANCED_SERVING = True)
#   · 고령친화식품(제품) 칸은 1인분 그대로 (비율 1.0 고정)
#   · 나머지 칸(밥·국·주찬·부찬·김치) 비율을 함께 조정해 개인 기준을 맞춤
#       제약: 나트륨·당류·포화지방·지방 ≤ 개인 상한, 단백질 ≥ 하한(신장질환은 ≤ 상한),
#             열량 개인 범위(energy_min~max) 안
#       목적: Σ((칸 비율 − 개인 비율)/개인 비율)²  +  W_ENERGY × ((열량 − 목표 열량)/목표 열량)²
#             → 한 메뉴만 크게 줄이지 않고 여러 칸을 조금씩 조정, 목표 열량에 최대한 가깝게
#   · 기준을 모두 맞출 수 없으면 가장 덜 어긋나는 해를 쓰고 '조정불가'로 표시
#   · [현장 단계] 최종 비율은 0 · 0.25 · 0.5 · 0.75 · 1 · 1.25 · 1.5 · 2 중 하나 (DISCRETE_SERVING)
# ══════════════════════════════════════════════════════════════
BALANCED_SERVING = True
W_ENERGY     = 10.0                     # 목표 열량을 맞추는 중요도 (칸 비율 변화 대비)
SPREAD       = 1.0                      # 0: 짠 칸 위주로 줄임 · 1: 모든 칸을 비슷한 비율로 줄임
# [2026-10-19] 현장 배식 단계: 국자·집게로 담기 쉬운 값만 사용 (0 = 해당 칸 미배식)
SERVING_LEVELS = [0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
DISCRETE_SERVING = True                 # True: 칸별 비율을 SERVING_LEVELS 중 하나로
SLOT_BOUNDS  = {s: (SERVING_LEVELS[0], SERVING_LEVELS[-1]) for s in ("밥", "국", "주찬", "부찬1", "부찬2", "김치")}
_CAP_KEYS    = ("sodium", "sugar", "sat_fat", "fat")


def _target_energy(patient) -> float:
    c = patient.constraint
    e_min, e_max = c.energy_min or 500, c.energy_max or 800
    return max(e_min, min(e_max, getattr(patient, "target_energy", (e_min + e_max) / 2)))


def _balanced_ratios(patient, menu_by_slot: dict, base_ratio: float) -> tuple:
    """→ ({칸: 비율}, 조정 결과 문자열). 제품 칸은 1.0 고정"""
    import numpy as np
    from scipy.optimize import minimize
    c = patient.constraint
    slots = [s for s, _ in SLOT_CATS]
    fixed = {s: 1.0 for s in slots if (menu_by_slot.get(s) or {}).get("is_product")}
    free  = [s for s in slots if s not in fixed and ((menu_by_slot.get(s) or {}).get("weight") or 0) > 0]
    ratios = {s: 0.0 for s in slots}
    ratios.update(fixed)
    if not free:
        return ratios, "제품만"

    def vec(key):
        return np.array([(menu_by_slot[s] or {}).get(key, 0) or 0 for s in free], dtype=float)
    def fixed_sum(key):
        return sum((menu_by_slot[s] or {}).get(key, 0) or 0 for s in fixed)

    E, fE = vec("energy"), fixed_sum("energy")
    e_target = _target_energy(patient)
    e_min, e_max = c.energy_min or 500, c.energy_max or 800
    x0 = np.array([min(max(base_ratio, SLOT_BOUNDS[s][0]), SLOT_BOUNDS[s][1]) for s in free])
    p0 = max(base_ratio, 1e-3)

    cons = []
    for key in _CAP_KEYS:
        cap = getattr(c, f"{key}_max", None)
        if cap:
            v, f = vec(key), fixed_sum(key)
            cons.append({"type": "ineq", "fun": lambda x, v=v, f=f, cap=cap: (cap - f - v @ x) / cap})
    P, fP = vec("protein"), fixed_sum("protein")
    if c.protein_max:
        cons.append({"type": "ineq", "fun": lambda x: (c.protein_max - fP - P @ x) / c.protein_max})
    elif c.protein_min:
        cons.append({"type": "ineq", "fun": lambda x: (fP + P @ x - c.protein_min) / c.protein_min})
    cons.append({"type": "ineq", "fun": lambda x: (e_max - fE - E @ x) / e_max})
    cons.append({"type": "ineq", "fun": lambda x: (fE + E @ x - e_min) / e_min})

    # 칸별 가중치: 나트륨이 많은 칸일수록 '줄이는 비용'을 크게 → 짠 칸 하나만 깎이지 않고 여러 칸이 비슷한 비율로 줄어듦
    Na = vec("sodium")
    w = (1 - SPREAD) + SPREAD * (Na / Na.mean() if Na.mean() > 0 else np.ones_like(Na))

    def obj(x):
        # x: (칸 수,) 또는 (칸 수, 후보 수) — 후보 여러 개를 한 번에 평가할 수 있게
        X = x if x.ndim == 2 else x[:, None]
        val = (w[:, None] * ((X - p0) / p0) ** 2).sum(axis=0) + W_ENERGY * ((fE + E @ X - e_target) / e_target) ** 2
        return val if x.ndim == 2 else float(val[0])

    bounds = [SLOT_BOUNDS[s] for s in free]
    res = minimize(obj, x0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 200, "ftol": 1e-9})
    x = np.clip(res.x if res.success else x0, [b[0] for b in bounds], [b[1] for b in bounds])
    ok = all(con["fun"](x) >= -1e-4 for con in cons)
    if not ok:      # 모든 기준을 맞출 수 없음 → 열량 하한을 빼고 다시 (나트륨 등 상한 우선)
        res2 = minimize(obj, x, method="SLSQP", bounds=bounds, constraints=cons[:-1],
                        options={"maxiter": 200, "ftol": 1e-9})
        if res2.success:
            x = np.clip(res2.x, [b[0] for b in bounds], [b[1] for b in bounds])
    if DISCRETE_SERVING:
        x = _snap_levels(x, obj, cons)
    ok = all(con["fun"](x) >= -1e-4 for con in cons)
    for s, v in zip(free, x):
        ratios[s] = round(float(v), 3)
    return ratios, ("조정완료" if ok else "조정불가(기준 일부 초과)")


def _snap_levels(x, obj, cons):
    """연속 해 → 배식 단계(SERVING_LEVELS)로 맞춤.
    칸마다 연속 해 주변 3개 단계(아래 단계 · 바로 아래 · 바로 위)를 후보로 두고,
    모든 조합(최대 3^6 = 729개)을 한 번에 평가해 (기준 위반 벌점 + 목적함수)가 가장 작은 조합을 고름"""
    import itertools
    import numpy as np
    L = np.array(SERVING_LEVELS, dtype=float)
    cand = []
    for v in x:
        lo = int(np.searchsorted(L, v, side="right") - 1)
        cand.append(sorted({max(lo - 1, 0), max(lo, 0), min(lo + 1, len(L) - 1)}))
    combos = np.array(list(itertools.product(*cand)))          # (후보 수, 칸 수)
    XX = L[combos].T                                            # (칸 수, 후보 수)
    viol = np.zeros(XX.shape[1])
    for con in cons:
        viol += np.maximum(0.0, -con["fun"](XX)) ** 2
    score = 1e4 * viol + obj(XX)
    return XX[:, int(np.argmin(score))]


def _calc_ratio(patient, facility_avg_energy: float) -> float:
    """
    개인별 배식 비율 계산
    ① p.constraint 범위로 target_energy 클리핑 (질환 기준 반영)
    ② clipped_target / 시설 평균 → ratio
    """
    c = patient.constraint

    # 질환별 에너지 범위 (constraint에 이미 반영됨)
    e_min = c.energy_min or 500
    e_max = c.energy_max or 800

    # target_energy를 질환 기준 범위 내로 클리핑
    raw_target    = getattr(patient, "target_energy", facility_avg_energy)
    clipped_target = max(e_min, min(e_max, raw_target))

    # 시설 평균 대비 비율
    ratio = clipped_target / facility_avg_energy

    # 안전 범위 적용
    return round(max(RATIO_MIN, min(RATIO_MAX, ratio)), 3)


def serving_agent(state: MealPlanState) -> dict:
    print("\n[ServingAgent] 개인별 배식량 산출 시작...")

    # ── registry에서 직렬화 불가 객체 꺼내기 ─────────────────
    patients = registry.get(state["patients_key"])

    # ── df_menu: records → DataFrame 복원 ────────────────────
    df = None
    if state.get("df_menu_records"):
        df = pd.DataFrame(
            state["df_menu_records"],
            columns=state["df_menu_columns"]
        )

    if df is None:
        print("[ServingAgent] df_menu 없음 — 건너뜀")
        return {"serving_map": {}, "messages": ["[ServingAgent] df_menu 없음"]}

    pool = state.get("pool") or {}
    personal_menus = state.get("personal_menus") or {}
    sub_products   = state.get("sub_products") or {}

    # pool 빠른 조회 인덱스
    pool_index = {
        (cat, m["menu_name"]): m
        for cat, menus in pool.items()
        for m in menus
    }

    # ── 시설 평균 target_energy 계산 ─────────────────────────
    valid_energies = [
        getattr(p, "target_energy", None)
        for p in patients
        if getattr(p, "target_energy", None) is not None
    ]
    if not valid_energies:
        raise ValueError("[ServingAgent] 입소자 target_energy가 모두 없습니다.")

    facility_avg_energy = sum(valid_energies) / len(valid_energies)
    print(f"  시설 평균 목표 열량: {facility_avg_energy:.1f} kcal/끼니")

    # ── 개인별 ratio 사전 계산 (진단 출력 포함) ──────────────
    patient_ratios = {}
    for p in patients:
        ratio = _calc_ratio(p, facility_avg_energy)
        patient_ratios[p.name] = ratio

    # 대표 3명 출력
    sample = list(patient_ratios.items())[:3]
    for name, r in sample:
        print(f"  [{name}] ratio={r:.3f}")

    # ── 배식량 산출 ───────────────────────────────────────────
    serving_map: dict = {}
    _cb = state.get("progress_cb")          # 서버 진행률 표시용 (끼니 i / 전체)

    for _i, (_, menu_row) in enumerate(df.iterrows()):
        if _cb:
            _cb(_i, len(df))
        day  = menu_row["일차"]
        meal = menu_row["끼니"]

        menu_by_slot = {
            slot: pool_index.get((cat, menu_row.get(slot, "")), {})
            for slot, cat in SLOT_CATS
        }

        base_by_slot = menu_by_slot
        for p in patients:
            ratio = patient_ratios[p.name]
            c     = p.constraint

            # [2026-10-18] 개인 대체찬(고령친화우수식품) 반영
            menu_by_slot = dict(base_by_slot)
            for slot, prod_name in (personal_menus.get(f"{p.name}||{day}||{meal}") or {}).items():
                prod = sub_products.get(prod_name) or pool_index.get(
                    ({"부찬1": "부찬", "부찬2": "부찬"}.get(slot, slot), prod_name))
                if prod:
                    menu_by_slot[slot] = prod

            # ① 칸별 배식 비율
            if BALANCED_SERVING:
                # [2026-10-19] 제품 칸 1인분 고정 + 나머지 칸 균형 조정
                slot_ratio, adj_note = _balanced_ratios(p, menu_by_slot, ratio)
                r_rice = slot_ratio.get("밥", ratio)
                side_vals = [v for s, v in slot_ratio.items()
                             if s != "밥" and v and not (menu_by_slot.get(s) or {}).get("is_product")]
                r_side = round(sum(side_vals) / len(side_vals), 3) if side_vals else 1.0
            else:
                # (기존) 반찬은 나트륨 상한 안, 밥으로 열량 보충
                r_rice, r_side = _split_ratio(ratio, menu_by_slot, c.sodium_max)
                slot_ratio = {slot: (r_rice if slot == "밥" else r_side) for slot, _ in SLOT_CATS}
                adj_note = "기존방식"

            # ② 배식량 = pool weight(표준 배식량) × 슬롯별 비율
            srv = {}
            for slot, cat in SLOT_CATS:
                base_weight = (menu_by_slot.get(slot, {}) or {}).get("weight", 0) or 0
                srv[slot]   = round(base_weight * slot_ratio[slot], 1)

            # ③ 예상 영양소 (슬롯별 비율 반영)
            def _sum(key, _sr=slot_ratio):
                return sum(
                    ((menu_by_slot.get(s, {}) or {}).get(key, 0) or 0) * _sr[s]
                    for s, _ in SLOT_CATS
                )

            # ④ 영양 기준 충족 여부
            e_val = round(_sum("energy"),  1)
            p_val = round(_sum("protein"), 1)
            s_val = round(_sum("sodium"),  1)

            ok_e = (c.energy_min or 0) <= e_val <= (c.energy_max or 9999)
            ok_p = (p_val >= (c.protein_min or 0)) and \
                   (p_val <= (c.protein_max or 9999))
            ok_s = s_val <= (c.sodium_max or 9999)

            entry = {
                **srv,
                "ratio":          ratio,
                "밥비율":         r_rice,
                "반찬비율":       r_side,
                "예상열량":       e_val,
                "예상단백질":     p_val,
                "예상나트륨":     s_val,
                "예상탄수화물":   round(_sum("carb"), 1),
                "열량OK":  "✅" if ok_e else "⚠️",
                "단백질OK": "✅" if ok_p else "⚠️",
                "나트륨OK": "✅" if ok_s else "⚠️",
                "칸별비율": " ".join(f"{s}{v:.2f}" + ("(제품)" if (menu_by_slot.get(s) or {}).get("is_product") else "")
                                    for s, v in slot_ratio.items() if v),
                "조정결과": adj_note,
            }

            key_str = f"{p.name}||{day}||{meal}"
            serving_map[key_str] = entry

    print(f"[ServingAgent] 완료 — {len(serving_map)}건")
    return {
        "serving_map": serving_map,
        "messages":    [f"[ServingAgent] {len(serving_map)}건 배식량 산출 완료"],
    }
