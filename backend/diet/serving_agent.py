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


# ══════════════════════════════════════════════════════════════
# [2026-10-19] 빠른 배식 (FAST_SERVING = True)
#   _balanced_ratios(SLSQP → 단계 맞춤)를 어르신·끼니마다 4,000번 넘게 도는 대신,
#   처음부터 배식 단계(SERVING_LEVELS) 위에서 전체 (어르신 × 끼니)를 한꺼번에 탐색한다.
#     · 점수 = 1e4 × 기준 위반² + 목적함수  ← _snap_levels 와 같은 기준
#     · 시작점 여러 개(개인 비율 근처 · 나트륨 맞춘 비율 근처 · 1인분) → 칸 1개 ±1·±2단계,
#       칸 2개 동시(하나 올리고 하나 내림) 이동 중 점수가 가장 많이 줄어드는 이동을 반복
#     · 모든 행을 numpy 로 동시에 계산 → 수천 건이 1초 안팎
# ══════════════════════════════════════════════════════════════
FAST_SERVING = True
_KEYS = ("energy", "protein", "sodium", "sugar", "sat_fat", "fat")


def _batch_discrete(rows: list, max_iter: int = 60, init=None, return_score=False):
    """rows: [(patient, menu_by_slot, base_ratio)] → [({칸: 비율}, 조정결과)]"""
    import itertools
    import numpy as np
    slots = [s for s, _ in SLOT_CATS]
    R, K, Q = len(rows), len(slots), len(_KEYS)
    L = np.array(SERVING_LEVELS, dtype=float)
    NL = len(L)
    V = np.zeros((R, K, Q)); Fx = np.zeros((R, Q))
    free = np.zeros((R, K), bool); fixed1 = np.zeros((R, K), bool)
    cap = np.full((R, 4), np.inf)                  # sodium, sugar, sat_fat, fat
    pmin = np.zeros(R); pmax = np.full(R, np.inf)
    emin = np.zeros(R); emax = np.zeros(R); etg = np.zeros(R); p0 = np.zeros(R)
    for r, (p, mbs, base) in enumerate(rows):
        c = p.constraint
        for k, s in enumerate(slots):
            m = mbs.get(s) or {}
            vals = [float(m.get(q, 0) or 0) for q in _KEYS]
            if m.get("is_product"):
                fixed1[r, k] = True; Fx[r] += vals
            elif (m.get("weight") or 0) > 0:
                free[r, k] = True; V[r, k] = vals
        for j, q in enumerate(("sodium", "sugar", "sat_fat", "fat")):
            v = getattr(c, f"{q}_max", None)
            if v:
                cap[r, j] = v
        if c.protein_max:
            pmax[r] = c.protein_max
        elif c.protein_min:
            pmin[r] = c.protein_min
        emin[r], emax[r] = c.energy_min or 500, c.energy_max or 800
        etg[r] = _target_energy(p)
        p0[r] = max(base, 1e-3)
    Na = V[:, :, 2]
    nfree = np.maximum(free.sum(1), 1)
    na_mean = (Na * free).sum(1) / nfree
    w = np.where(na_mean[:, None] > 0, (1 - SPREAD) + SPREAD * Na / np.where(na_mean > 0, na_mean, 1)[:, None], 1.0) * free

    capd = np.where(np.isfinite(cap), cap, 1); pmaxd = np.where(np.isfinite(pmax), pmax, 1); pmind = np.where(pmin > 0, pmin, 1)

    def totals(X, ri=None):                         # X (n, K) 비율 → (n, Q)
        ri = slice(None) if ri is None else ri
        return Fx[ri] + np.einsum("rk,rkq->rq", X, V[ri])

    def score(X, ri=None):
        T = totals(X, ri)
        ri = slice(None) if ri is None else ri
        viol = (np.maximum(0, (T[:, [2, 3, 4, 5]] - cap[ri]) / capd[ri]) ** 2).sum(1)
        viol += np.where(np.isfinite(pmax[ri]), np.maximum(0, (T[:, 1] - pmax[ri]) / pmaxd[ri]) ** 2, 0)
        viol += np.where(pmin[ri] > 0, np.maximum(0, (pmin[ri] - T[:, 1]) / pmind[ri]) ** 2, 0)
        viol += np.maximum(0, (T[:, 0] - emax[ri]) / emax[ri]) ** 2 + np.maximum(0, (emin[ri] - T[:, 0]) / emin[ri]) ** 2
        obj = (w[ri] * ((X - p0[ri][:, None]) / p0[ri][:, None]) ** 2).sum(1) + W_ENERGY * ((T[:, 0] - etg[ri]) / etg[ri]) ** 2
        # 기준을 조금이라도 넘으면 고정 벌점 → 기준을 모두 맞추는 조합을 우선 (그다음 덜 줄이는 조합)
        return 1e4 * viol + 5.0 * (viol > 1e-7) + obj, viol

    def lv(idx):
        return np.where(free, L[idx], np.where(fixed1, 1.0, 0.0))

    # 이동 후보: 칸 1개 ±1·±2단계, 칸 2개 (하나 +1 · 하나 −1)
    moves = [(a, d, None, 0) for a in range(K) for d in (-2, -1, 1, 2)]
    moves += [(a, 1, b, -1) for a, b in itertools.permutations(range(K), 2)]

    def improve(idx):
        cur, _ = score(lv(idx))
        for _ in range(max_iter):
            best_s, best_i = cur.copy(), None
            cand_idx = []
            for a, da, b, db in moves:
                ni = idx.copy()
                ni[:, a] = np.clip(ni[:, a] + da, 0, NL - 1)
                if b is not None:
                    ni[:, b] = np.clip(ni[:, b] + db, 0, NL - 1)
                cand_idx.append(ni)
            S = np.stack([score(lv(ni))[0] for ni in cand_idx])          # (이동 수, R)
            j = S.argmin(0)
            sbest = S[j, np.arange(R)]
            better = sbest < cur - 1e-9
            if not better.any():
                break
            rr = np.where(better)[0]
            stack = np.stack(cand_idx)                                    # (이동 수, R, K)
            idx[rr] = stack[j[rr], rr]
            cur[rr] = sbest[rr]
        return idx, cur

    near = lambda x: np.abs(L[None, None, :] - x[:, :, None]).argmin(2)
    starts = [near(np.repeat(p0[:, None], K, 1)), near(np.ones((R, K)))]
    # 나트륨 상한에 맞춰 전체를 줄인 비율 근처
    T0 = totals(lv(starts[0]))
    shrink = np.clip(np.minimum(1.0, (cap[:, 0] - Fx[:, 2]) / np.maximum(T0[:, 2] - Fx[:, 2], 1e-6)), 0.25, 1.0)
    starts.append(near(np.repeat((p0 * shrink)[:, None], K, 1)))
    # 반찬은 줄이고 밥으로 열량을 채운 시작점
    rice = slots.index("밥")
    for f in (0.5, 0.75):
        X0 = np.repeat((p0 * f)[:, None], K, 1); X0[:, rice] = np.minimum(2.0, p0 * 1.5)
        starts.append(near(X0))
    if init is not None:                                   # (검증용) 주어진 비율의 점수만 계산
        best_idx = near(np.asarray(init, dtype=float))
        sc_final, viol = score(lv(best_idx))
        return sc_final, viol
    best_idx, best_sc = None, None
    for st in starts:
        idx, sc = improve(st.copy())
        if best_idx is None:
            best_idx, best_sc = idx, sc
        else:
            m = sc < best_sc
            best_idx[m], best_sc[m] = idx[m], sc[m]

    # 마무리: 칸마다 현재 단계 ±1 의 모든 조합(최대 3^6 = 729개)을 한 번에 비교 (_snap_levels 와 같은 방식)
    offs = np.array(list(itertools.product((-1, 0, 1), repeat=K)))           # (C, K)

    def score3(Xc, rr):                              # Xc (n, C, K) → (n, C)
        T = Fx[rr][:, None, :] + np.einsum("nck,nkq->ncq", Xc, V[rr])
        cp, cd = cap[rr][:, None, :], capd[rr][:, None, :]
        viol = (np.maximum(0, (T[..., [2, 3, 4, 5]] - cp) / cd) ** 2).sum(-1)
        pm, pmd, pn, pnd = pmax[rr][:, None], pmaxd[rr][:, None], pmin[rr][:, None], pmind[rr][:, None]
        viol += np.where(np.isfinite(pm), np.maximum(0, (T[..., 1] - pm) / pmd) ** 2, 0)
        viol += np.where(pn > 0, np.maximum(0, (pn - T[..., 1]) / pnd) ** 2, 0)
        ex, en, et = emax[rr][:, None], emin[rr][:, None], etg[rr][:, None]
        viol += np.maximum(0, (T[..., 0] - ex) / ex) ** 2 + np.maximum(0, (en - T[..., 0]) / en) ** 2
        pp = p0[rr][:, None, None]
        obj = (w[rr][:, None, :] * ((Xc - pp) / pp) ** 2).sum(-1) + W_ENERGY * ((T[..., 0] - et) / et) ** 2
        return 1e4 * viol + 5.0 * (viol > 1e-7) + obj

    for _ in range(3):
        changed = False
        for c0 in range(0, R, 500):
            rr = np.arange(c0, min(R, c0 + 500)); n = len(rr)
            fr = free[rr][:, None, :]
            cand = np.clip(best_idx[rr][:, None, :] + offs[None] * fr, 0, NL - 1)          # (n, C, K)
            Xc = np.where(fr, L[cand], np.where(fixed1[rr][:, None, :], 1.0, 0.0))
            sc = score3(Xc, rr)
            j = sc.argmin(1)
            new_sc = sc[np.arange(n), j]
            m = new_sc < best_sc[rr] - 1e-9
            if m.any():
                changed = True
                best_idx[rr[m]] = cand[np.arange(n)[m], j[m]]
                best_sc[rr[m]] = new_sc[m]
        if not changed:
            break
    X = lv(best_idx)
    sc_final, viol = score(X)
    if return_score:
        return sc_final, viol
    out = []
    for r in range(R):
        ratios = {s: round(float(X[r, k]), 3) for k, s in enumerate(slots)}
        if not free[r].any():
            out.append((ratios, "제품만"))
        else:
            out.append((ratios, "조정완료" if viol[r] <= 1e-7 else "조정불가(기준 일부 초과)"))
    return out


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

    # [빠른 배식] 칸별 비율을 끼니 묶음(CHUNK끼) 단위로 한꺼번에 계산해 둠
    pre = {}
    if BALANCED_SERVING and FAST_SERVING:
        CHUNK = 14
        rows_all = list(df.iterrows())
        for c0 in range(0, len(rows_all), CHUNK):
            if _cb:
                _cb(c0, len(rows_all))
            batch, keys = [], []
            for _, mr in rows_all[c0:c0 + CHUNK]:
                d_, m_ = mr["일차"], mr["끼니"]
                base_ = {slot: pool_index.get((cat, mr.get(slot, "")), {}) for slot, cat in SLOT_CATS}
                for p in patients:
                    mbs = dict(base_)
                    for slot, prod_name in (personal_menus.get(f"{p.name}||{d_}||{m_}") or {}).items():
                        prod = sub_products.get(prod_name) or pool_index.get(
                            ({"부찬1": "부찬", "부찬2": "부찬"}.get(slot, slot), prod_name))
                        if prod:
                            mbs[slot] = prod
                    batch.append((p, mbs, patient_ratios[p.name])); keys.append(f"{p.name}||{d_}||{m_}")
            for k_, res_ in zip(keys, _batch_discrete(batch)):
                pre[k_] = res_

    for _i, (_, menu_row) in enumerate(df.iterrows()):
        if _cb and not pre:
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
                k_ = f"{p.name}||{day}||{meal}"
                slot_ratio, adj_note = pre[k_] if k_ in pre else _balanced_ratios(p, menu_by_slot, ratio)
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
