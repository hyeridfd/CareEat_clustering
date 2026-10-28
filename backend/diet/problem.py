"""
problem.py  ─  28일 식단 4목적 문제 정의 (에이전트 optimizer_agent.py의 MealPlanProblem, 서버판)
"""

import numpy as np

from .meal_rules import (effective_meal, F4_WEIGHTS, ONE_DISH_MAX_PER_WEEK,
                         TEXTURE_CAUTION_MAX)


class Problem:                     # [서버] pymoo 없이 동작 (nsga2.py가 _eval_one을 직접 호출)
    def __init__(self, **kw):
        self.__dict__.update(kw)

DAILY_SLOTS = [
    ("아침_밥","밥"),  ("아침_국","국"),    ("아침_주찬","주찬"),
    ("아침_부찬1","부찬"),("아침_부찬2","부찬"),("아침_김치","김치"),
    ("점심_밥","밥"),  ("점심_국","국"),    ("점심_주찬","주찬"),
    ("점심_부찬1","부찬"),("점심_부찬2","부찬"),("점심_김치","김치"),
    ("저녁_밥","밥"),  ("저녁_국","국"),    ("저녁_주찬","주찬"),
    ("저녁_부찬1","부찬"),("저녁_부찬2","부찬"),("저녁_김치","김치"),
]
N_DAYS   = 28
N_SLOTS  = len(DAILY_SLOTS)
MEAL_SETS = {
    "아침": [0,1,2,3,4,5],
    "점심": [6,7,8,9,10,11],
    "저녁": [12,13,14,15,16,17],
}
WHITELIST = ["쌀밥", "배추김치"]
# 영양 위반 계산 대상 영양소 (pool 키 이름과 동일해야 함)
NUTRIENTS = ["energy", "protein", "fat", "sugar", "sat_fat",
             "sodium", "potassium", "fiber", "carb", "vit_d"]


class MealPlanProblem(Problem):
    def __init__(self, pool, constraint, budget_per_meal, inventory=None, inv_weight=None):
        self.pool       = pool
        self.constraint = constraint
        self.budget     = budget_per_meal * N_DAYS * 3
        # [2026-10-19] 재고 활용 (inventory.py) — f2 = 예산 초과 + INV_WEIGHT × 재고 미활용률
        self.inventory  = inventory
        if inv_weight is None:
            from .inventory import INV_WEIGHT as inv_weight
        self.inv_weight = inv_weight
        self.slot_sizes = [len(pool[cat]) for _, cat in DAILY_SLOTS]
        super().__init__(
            n_var=N_DAYS * N_SLOTS, n_obj=4,
            xl=np.zeros(N_DAYS * N_SLOTS, dtype=int),
            xu=np.array([s-1 for s in self.slot_sizes] * N_DAYS, dtype=int),
            vtype=int,
        )

    def _get_menu(self, day, slot, idx):
        _, cat = DAILY_SLOTS[slot]
        return self.pool[cat][int(idx) % len(self.pool[cat])]

    def _evaluate(self, X, out, *args, **kwargs):
        out["F"] = np.array([self._eval_one(c) for c in X])

    def effective_menus(self, chrom):
        """[2026-10-14] 염색체 → 실제 배식 메뉴 (한 그릇 음식 끼니는 밥 제외)"""
        raw = [self._get_menu(d, s, chrom[d*N_SLOTS+s])
               for d in range(N_DAYS) for s in range(N_SLOTS)]
        out = []
        for b in range(0, len(raw), 6):
            out += effective_meal(raw[b:b+6])
        return out

    def _eval_one(self, chrom):
        all_menus = self.effective_menus(chrom)
        return [
            self._nutrition_violation(all_menus),               # 1. 영양 (f1)
            self._cost_inventory(chrom, all_menus),             # 2. 예산 + 재고 미활용 (f2)
            -self._preference_weighted_diversity(all_menus),    # 3. 만족도/다양성 (f3)
            self._pattern_violation(chrom, all_menus)           # 4. 통합 패턴 위반 (f4)
        ]

    def _cost_inventory(self, chrom, menus):
        over = max(0.0, sum(m["cost"] for m in menus) - self.budget) / self.budget
        if self.inventory is None or not self.inv_weight:
            return over
        U = self.inventory.daily_usage_chrom(chrom, DAILY_SLOTS, N_SLOTS)
        return over + self.inv_weight * self.inventory.unused_score(U)

    def _nutrition_violation(self, menus):
        c       = self.constraint
        meal_v  = 0.0
        daily_v = 0.0

        for day in range(N_DAYS):
            # [2026-10-11 수정] NUTRIENTS 하나로 끼니·일일 합계를 함께 계산
            #   (기존: 끼니 합계에 vit_d 누락 → daily_vit_d_min 매일 위반 → f1 +0.4 고정)
            daily_sum = {k: 0.0 for k in NUTRIENTS}
            base      = day * N_SLOTS
            day_menus = menus[base:base+N_SLOTS]

            for _, slots in MEAL_SETS.items():
                mm = [day_menus[s] for s in slots]
                mn = {k: sum(m.get(k, 0) or 0 for m in mm) for k in NUTRIENTS}

                for k, val in mn.items():
                    lo = getattr(c, f"{k}_min", None)
                    hi = getattr(c, f"{k}_max", None)
                    if lo and val < lo: meal_v  += (lo - val) / lo
                    if hi and val > hi: meal_v  += (val - hi) / hi
                    daily_sum[k] += val

            for k, val in daily_sum.items():
                lo = getattr(c, f"daily_{k}_min", None)
                hi = getattr(c, f"daily_{k}_max", None)
                if lo and val < lo: daily_v += (lo - val) / lo
                if hi and val > hi: daily_v += (val - hi) / hi

        meal_score  = meal_v  / (N_DAYS * 3)
        daily_score = daily_v / N_DAYS
        return meal_score * 0.6 + daily_score * 0.4

    def nutrition_breakdown(self, menus) -> dict:
        """[진단용] f1을 영양소별 기여도로 분해 (끼니 60% / 일일 40% 가중 반영)"""
        c   = self.constraint
        out = {}
        def _add(key, v):
            out[key] = out.get(key, 0.0) + v
        for day in range(N_DAYS):
            daily_sum = {k: 0.0 for k in NUTRIENTS}
            day_menus = menus[day*N_SLOTS:(day+1)*N_SLOTS]
            for _, slots in MEAL_SETS.items():
                mm = [day_menus[s] for s in slots]
                for k in NUTRIENTS:
                    val = sum(m.get(k, 0) or 0 for m in mm)
                    daily_sum[k] += val
                    lo = getattr(c, f"{k}_min", None); hi = getattr(c, f"{k}_max", None)
                    if lo and val < lo: _add(f"끼니 {k} 부족", (lo-val)/lo * 0.6/(N_DAYS*3))
                    if hi and val > hi: _add(f"끼니 {k} 초과", (val-hi)/hi * 0.6/(N_DAYS*3))
            for k, val in daily_sum.items():
                lo = getattr(c, f"daily_{k}_min", None); hi = getattr(c, f"daily_{k}_max", None)
                if lo and val < lo: _add(f"일일 {k} 부족", (lo-val)/lo * 0.4/N_DAYS)
                if hi and val > hi: _add(f"일일 {k} 초과", (val-hi)/hi * 0.4/N_DAYS)
        return dict(sorted(out.items(), key=lambda x: -x[1]))

    def _simpson_diversity(self, menus):
        names = [m["menu_name"] for m in menus]
        N = len(names)
        counts: dict = {}
        for n in names: counts[n] = counts.get(n, 0) + 1
        M = len(counts)
        if M <= 1: return 0.0
        return (1 - sum((c/N)**2 for c in counts.values())) / (1 - 1/M) * 100

    def _preference_weighted_diversity(self, menus):
        # 기존 simpson diversity + preference_score 혼합
        diversity = self._simpson_diversity(menus)
        pref_avg  = sum(m.get("preference_score", 0.7) for m in menus) / len(menus)
        return diversity * 0.7 + pref_avg * 100 * 0.3  # 가중 합산

    # def _same_side_dish_penalty(self, chrom):
    #     penalty = 0
    #     for day in range(N_DAYS):
    #         base = day * N_SLOTS
    #         for s1, s2 in [(3,4),(9,10),(15,16)]:
    #             if int(chrom[base+s1]) == int(chrom[base+s2]):
    #                 penalty += 1
    #     return penalty / (N_DAYS * 3)

    # def _carry_over_penalty(self, menus, look_back=1):
    #     penalty = total = 0
    #     for day in range(1, N_DAYS):
    #         cur  = [m["menu_name"] for m in menus[day*N_SLOTS:(day+1)*N_SLOTS]]
    #         past = [m["menu_name"] for m in
    #                 menus[max(0,day-look_back)*N_SLOTS:day*N_SLOTS]]
    #         for name in cur:
    #             if name in WHITELIST: continue
    #             if name in past: penalty += 1
    #             total += 1
    #     return penalty / total if total else 0.0

    # ← 여기에 추가
    def _pattern_violation(self, chrom, menus):
        """
        부찬 중복 + 연속 배식 페널티 통합
        """
        # 1. 동일 끼니 내 부찬1 == 부찬2
        side_dish_p = 0
        for day in range(N_DAYS):
            base = day * N_SLOTS
            for s1, s2 in [(3,4),(9,10),(15,16)]:
                if int(chrom[base+s1]) == int(chrom[base+s2]):
                    side_dish_p += 1
        side_score = side_dish_p / (N_DAYS * 3)

        # 2. 14일 안 반복 배식 — [2026-10-28] 끼니 단위로 계산 (기존: 날짜 단위라 '같은 날' 중복을 못 잡음)
        #    가까울수록 무겁게: 같은 날·바로 앞 끼니 3점 · 3일 안 2점 · 14일 안 1점
        carry_over_p = 0.0
        dists        = repeat_distances(menus)
        total_items  = len(dists)
        for d in dists:
            if d is not None:
                carry_over_p += REPEAT_W[0] if d <= NEAR_MEALS else REPEAT_W[1] if d <= DAYS3_MEALS else REPEAT_W[2]

        carry_score = min(1.0, carry_over_p / total_items) if total_items else 0.0

        # 3. [2026-10-14] 한 그릇 음식 규칙 (meal_rules.py)
        #    · 한 끼에 2개 이상 → 초과분   · 7일 단위 한 그릇 끼니 > 상한 → 초과분
        n_meals  = N_DAYS * 3
        one_v    = 0
        one_meal = []
        for b in range(0, len(menus), 6):
            k = sum(1 for m in menus[b+1:b+6] if m.get("one_dish"))
            one_v += max(0, k - 1)
            one_meal.append(1 if k else 0)
        for w in range(0, n_meals, 21):
            one_v += max(0, sum(one_meal[w:w+21]) - ONE_DISH_MAX_PER_WEEK)
        one_score = min(1.0, one_v / n_meals)

        # 4. [2026-10-14] 다진찬 적합도: 부적합 0개, 주의 TEXTURE_CAUTION_MAX개까지 / 끼니
        tex_v = 0.0
        for b in range(0, len(menus), 6):
            meal = menus[b+1:b+6]
            bad  = sum(1 for m in meal if m.get("texture") == "부적합")
            caut = sum(1 for m in meal if m.get("texture") == "주의")
            tex_v += bad + 0.5 * max(0, caut - TEXTURE_CAUTION_MAX)
        tex_score = min(1.0, tex_v / n_meals)

        parts = {"side_dup": side_score, "carry_over": carry_score,
                 "one_dish": one_score, "texture": tex_score}
        wsum  = sum(F4_WEIGHTS.values()) or 1.0
        return sum(F4_WEIGHTS[k] * v for k, v in parts.items()) / wsum

    def pattern_breakdown(self, chrom) -> dict:
        """[진단] f4 구성요소별 원자료"""
        menus = self.effective_menus(chrom)
        meals = [menus[b:b+6] for b in range(0, len(menus), 6)]
        return {
            "한그릇_끼니수":      sum(1 for m in meals if m[0]["menu_name"].startswith("-(")),
            "한그릇_2개이상_끼니": sum(1 for m in meals if sum(x.get("one_dish", False) for x in m[1:]) > 1),
            "다진찬_부적합_포함_끼니": sum(1 for m in meals if any(x.get("texture") == "부적합" for x in m[1:])),
            "다진찬_주의3개이상_끼니": sum(1 for m in meals if sum(x.get("texture") == "주의" for x in m[1:]) > TEXTURE_CAUTION_MAX),
            "부찬중복_끼니":       sum(1 for i in range(N_DAYS) for s1, s2 in [(3,4),(9,10),(15,16)]
                                     if int(chrom[i*N_SLOTS+s1]) == int(chrom[i*N_SLOTS+s2])),
            **repeat_counts(menus),
        }

REPEAT_SLOTS = (1, 2, 3, 4)           # 국 · 주찬 · 부찬1 · 부찬2 (밥·김치 제외 — 김치는 후보가 2종뿐이라 반복이 정상)
WINDOW_MEALS = 14 * 3 - 1             # 14일
NEAR_MEALS   = 2                      # 같은 날 앞 끼니 · 바로 앞 끼니 (아침→점심, 저녁→다음날 아침)
DAYS3_MEALS  = 9                      # 3일
REPEAT_W     = (3.0, 2.0, 1.0)        # 가까운 반복일수록 무거운 벌점


def repeat_distances(menus) -> tuple:
    """끼니 순서대로 훑으며 각 메뉴가 '몇 끼 전에 마지막으로 나왔는지' → ([거리 또는 None, …], 대상 수)
    (화이트리스트·한그릇 밥칸 제외, 같은 끼니 안 중복은 side_dup 이 따로 봄)"""
    last, out = {}, []
    for t in range(0, len(menus) // 6):
        meal = menus[t * 6:(t + 1) * 6]
        names = [meal[k]["menu_name"] for k in REPEAT_SLOTS]
        for n in names:
            if n in WHITELIST or n.startswith("-("):
                continue
            p = last.get(n)
            out.append(t - p if p is not None and t - p <= WINDOW_MEALS else None)
        for n in names:
            last[n] = t
    return out


def repeat_counts(menus) -> dict:
    near = d3 = d14 = 0
    for d in repeat_distances(menus):
        if d is None:
            continue
        if d <= NEAR_MEALS: near += 1
        elif d <= DAYS3_MEALS: d3 += 1
        else: d14 += 1
    return {"반복_같은날·연속끼니": near, "반복_3일안": d3, "반복_14일안": d14}


def get_menu(pool: dict, slot_idx: int, chrom_val: int) -> dict:
    _, cat = DAILY_SLOTS[slot_idx]
    return pool[cat][int(chrom_val) % len(pool[cat])]
