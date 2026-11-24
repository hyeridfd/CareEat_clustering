# -*- coding: utf-8 -*-
"""[2026-11-24] 시설 개선안 → 맞춤 식단 설계 반영

  시설 진단(care/facility_rules.py)의 관리 우선순위 중 '식단으로 풀 수 있는 문제'를
  공통 식단 최적화(NSGA-II)의 지시로 바꾼다. 기존 기준(KDRI 공통 기준 · 개인 맞춤 기준 · 식단 규칙)은 그대로 두고
  그 위에 무게와 선호만 얹는다 — 기준을 느슨하게 만드는 지시는 없다.

  지시 종류
    nutrient_weight  f1(영양 위반)에서 해당 영양소 위반의 가중치 (기본 1)        예: 나트륨 ×2
    prefer / limit   메뉴 이름·재료 키워드 — f4(조화)에 '개선안 부합도' 항을 더해 선호·제한  예: 칼슘 급원 선호, 장아찌·젓갈 제한
    potassium        칼륨이 많은 국·부찬을 선호 (나트륨 개선안, 고혈압 지침의 칼륨 권고)
    pref_mult        f4 의 시설 선호(실제 섭취율) 항 가중치 배수                  예: 섭취율이 낮을 때 ×1.5
    texture_mult     f4 의 다진찬 부적합 규칙 가중치 배수                         예: 형태 조정 수요가 많을 때 ×2
    avoid_menus      잔반이 특히 많은 메뉴를 후보에서 뺀다 (자리별 후보가 10% 넘게 줄면 빼지 않음)
    targets          영양 목표치를 '더 엄격하게만' 올린다 (예: 단백질 끼니 16.7 → 23 g, 하루 50 → 69 g)
                     — 이미 대부분 충족한 기준에 가중치만 곱하면 위반이 0이라 효과가 없어서 (2026-11-24)

  선택 보호장치(guard_candidates): 파레토 후보 중 개선안이 겨냥한 영양소가 '비교 기준(무작위 식단)'보다
  나빠지는 후보는 고르지 않는다. 모든 후보가 걸리면 가장 덜 나빠지는 후보들로 좁힌다.

  식사 도움·우울·끼니 운영처럼 식단 밖의 조치는 반영하지 않고 '식단 외 조치'로 따로 돌려준다.
  어르신별 맞춤(대체찬·배식량)은 기존 개인 기준을 그대로 따른다.
"""
from __future__ import annotations

import re

PLAN_W = 0.15          # f4 에 더하는 '개선안 부합도' 항의 가중치 (조화 0.5 · 선호 0.2 · 규칙 0.3 과 같은 척도)
PREFER_BONUS = 0.25    # 선호 키워드가 있는 메뉴 → 부합도 0.75
LIMIT_PENALTY = 0.5    # 제한 키워드가 있는 메뉴 → 부합도 0.0
K_BONUS = 0.15         # 칼륨 상위 25% 국·부찬 → 부합도 +0.15
SCORED = ("국", "주찬", "부찬")   # 밥·김치는 후보가 1~2개라 선호·제한을 매기지 않는다 (김치의 젓갈은 피할 수 없음)

SODIUM_LIMIT = ["장아찌", "젓갈", "젓무침", "명란", "창난", "오징어젓", "어리굴젓", "햄", "소시지", "베이컨", "스팸",
                "어묵", "맛살", "짠지", "절임", "자반"]
CALCIUM_SRC = ["우유", "요구르트", "요거트", "치즈", "멸치", "뱅어포", "두부", "무청", "시래기", "깻잎", "쑥", "미꾸라지",
               "꽁치", "들깨"]
VITD_SRC = ["표고", "고등어", "연어", "꽁치", "삼치", "달걀", "계란", "메추리알"]
FIBER_SRC = ["나물", "시래기", "우거지", "버섯", "미역", "다시마", "톳", "잡곡", "보리", "현미", "고구마", "브로콜리", "배추", "양배추"]
# 저체중·영양위험·단백질 부족 개선안: 단백질 목표 상향
#   끼니 23 g · 하루 69 g ≈ 영양불량 노인 권고 1.2~1.5 g/kg (저체중군 체중 45~55 kg)
#   20 g(하루 60 g)으로는 무작위 식단 평균(끼니 약 26.7 g)보다 낮게 나와 개선이 안 됐음 (2026-11-24 시험)
PROTEIN_BOOST = {"protein_min": 23.0, "daily_protein_min": 69.0}
PROTEIN_W = 3.0
PROTEIN_SRC = ["두부", "달걀", "계란", "생선", "고등어", "조기", "가자미", "동태", "닭", "돼지", "소고기", "쇠고기", "불고기", "연두부"]

# 관리 우선순위 id → 식단 반영 지시
MENU_DIRECTIVES = {
    "F_NUT_SODIUM": dict(weight={"sodium": 2.0}, limit=SODIUM_LIMIT, potassium=True,
                         how=["영양 위반(f1)에서 나트륨 위반 가중치 ×2",
                              "장아찌·젓갈·가공육·어묵 메뉴를 덜 고르도록 제한",
                              "칼륨이 많은 국·부찬을 더 고르도록 선호 (신장질환·칼륨 보존 이뇨제 어르신은 개인 맞춤에서 제외)"]),
    "F_NUT_ENERGY": dict(weight={"energy": 1.5}, how=["영양 위반(f1)에서 열량 부족 가중치 ×1.5"]),
    "F_NUT_PROTEIN": dict(weight={"protein": PROTEIN_W}, prefer=PROTEIN_SRC, targets=PROTEIN_BOOST,
                          how=["단백질 목표 상향: 끼니 16.7 → 23 g, 하루 50 → 69 g",
                               "영양 위반(f1)에서 단백질 부족 가중치 ×3", "단백질 급원 메뉴 선호"]),
    "F_NUT_CALCIUM": dict(prefer=CALCIUM_SRC, how=["우유·멸치·두부·무청 등 칼슘 급원 메뉴 선호"]),
    "F_NUT_FIBER": dict(weight={"fiber": 1.5}, prefer=FIBER_SRC,
                        how=["영양 위반(f1)에서 식이섬유 부족 가중치 ×1.5", "나물·버섯·해조류·잡곡 메뉴 선호"]),
    "F_NUT_VITD": dict(prefer=VITD_SRC, how=["표고버섯·등푸른생선·달걀 메뉴 선호"]),
    "F_MALNUT": dict(weight={"energy": 1.5, "protein": PROTEIN_W}, prefer=PROTEIN_SRC, targets=PROTEIN_BOOST,
                     how=["단백질 목표 상향: 끼니 16.7 → 23 g, 하루 50 → 69 g",
                          "영양 위반(f1)에서 열량 부족 가중치 ×1.5 · 단백질 부족 가중치 ×3", "단백질 급원 메뉴 선호"]),
    "F_UNDERWEIGHT": dict(weight={"energy": 1.5, "protein": PROTEIN_W}, prefer=PROTEIN_SRC, targets=PROTEIN_BOOST,
                          how=["단백질 목표 상향: 끼니 16.7 → 23 g, 하루 50 → 69 g",
                               "영양 위반(f1)에서 열량 부족 가중치 ×1.5 · 단백질 부족 가중치 ×3", "단백질 급원 메뉴 선호"]),
    "F_TEXTURE_NEED": dict(texture=2.0, how=["다진찬으로 만들기 어려운 메뉴 제한 규칙 가중치 ×2"]),
    "F_TEXTURE_GAP": dict(texture=2.0, how=["다진찬으로 만들기 어려운 메뉴 제한 규칙 가중치 ×2"]),
    "F_LOW_INTAKE": dict(pref=1.5, how=["실제 섭취율이 높은 메뉴(시설 선호) 가중치 ×1.5"]),
    "F_COMPONENT_LOW": dict(pref=1.5, how=["실제 섭취율이 높은 메뉴(시설 선호) 가중치 ×1.5"]),
    "F_SATISFACTION": dict(pref=1.5, how=["실제 섭취율이 높은 메뉴(시설 선호) 가중치 ×1.5"]),
    "F_MENU_WORST": dict(pref=1.5, avoid=True, how=["잔반이 특히 많은 메뉴를 후보에서 제외", "실제 섭취율이 높은 메뉴 가중치 ×1.5"]),
}


def _norm(s: str) -> str:
    return re.sub(r"[\s()\[\]·,_\-*]|저염", "", str(s or ""))


def from_priorities(priorities: list, profile: dict | None = None) -> dict:
    """시설 관리 우선순위 → 식단 반영 지시 (같은 영양소 가중치는 큰 값)"""
    plan = {"items": [], "outside": [], "nutrient_weight": {}, "prefer": [], "limit": [], "potassium": False,
            "pref_mult": 1.0, "texture_mult": 1.0, "avoid_menus": [], "targets": {}}
    worst = [m.get("menu") for m in ((profile or {}).get("menus") or {}).get("worst") or []
             if m.get("menu") and (m.get("rate") or 100) < 60]
    for pr in priorities or []:
        d = MENU_DIRECTIVES.get(pr.get("id"))
        base = {"id": pr.get("id"), "title": pr.get("title"), "severity": pr.get("severity"),
                "severity_label": pr.get("severity_label"), "detail": pr.get("detail")}
        if not d:
            plan["outside"].append({**base, "action": pr.get("action")})
            continue
        for k, w in (d.get("weight") or {}).items():
            plan["nutrient_weight"][k] = max(plan["nutrient_weight"].get(k, 1.0), w)
        for k, v in (d.get("targets") or {}).items():
            plan["targets"][k] = max(plan["targets"].get(k, 0.0), v)
        for kw in d.get("prefer") or []:
            if kw not in plan["prefer"]:
                plan["prefer"].append(kw)
        for kw in d.get("limit") or []:
            if kw not in plan["limit"]:
                plan["limit"].append(kw)
        plan["potassium"] = plan["potassium"] or bool(d.get("potassium"))
        plan["pref_mult"] = max(plan["pref_mult"], d.get("pref", 1.0))
        plan["texture_mult"] = max(plan["texture_mult"], d.get("texture", 1.0))
        if d.get("avoid"):
            plan["avoid_menus"] = worst
        plan["items"].append({**base, "how": d["how"]})
    # 선호와 제한이 겹치면 제한을 따른다 (예: 멸치 → 젓갈은 제한)
    plan["prefer"] = [k for k in plan["prefer"] if k not in plan["limit"]]
    return plan


def _menu_text(m: dict, recipes: dict) -> str:
    ings = recipes.get(m.get("menu_name")) or {}
    return f"{m.get('menu_name', '')} {' '.join(ings)}"


def apply_pool(pool: dict, plan: dict) -> tuple[dict, dict]:
    """메뉴마다 plan_score(개선안 부합도 0~1)를 달고, 피할 메뉴를 뺀다. → (pool, 적용 기록)"""
    from .inventory import recipe_ingredients
    recipes = recipe_ingredients()
    prefer, limit = plan.get("prefer") or [], plan.get("limit") or []
    k_cut = {}
    if plan.get("potassium"):
        for cat in ("국", "부찬"):
            ks = sorted(float(m.get("potassium") or 0) for m in pool.get(cat, []))
            k_cut[cat] = ks[int(len(ks) * 0.75)] if ks else None
    log = {"preferred": 0, "limited": 0, "potassium": 0, "removed": []}
    avoid = {_norm(n) for n in plan.get("avoid_menus") or []}
    for cat, ms in pool.items():
        keep = [m for m in ms if _norm(m.get("menu_name")) not in avoid]
        if avoid and len(keep) < len(ms) and len(keep) >= 0.9 * len(ms):
            log["removed"] += [m["menu_name"] for m in ms if m not in keep]
            pool[cat] = ms = keep
        for m in ms:
            if cat not in SCORED:
                m["plan_score"] = 0.5
                continue
            txt = _menu_text(m, recipes)
            score = 0.5
            if limit and any(k in txt for k in limit):
                score -= LIMIT_PENALTY
                log["limited"] += 1
            elif prefer and any(k in txt for k in prefer):
                score += PREFER_BONUS
                log["preferred"] += 1
            cut = k_cut.get(cat)
            if cut is not None and float(m.get("potassium") or 0) >= cut and score >= 0.5:
                score += K_BONUS
                log["potassium"] += 1
            m["plan_score"] = round(max(0.0, min(1.0, score)), 3)
    return pool, log


def configure(problem, plan: dict):
    """최적화 문제에 지시를 건다 — 기준값은 그대로, 가중치만"""
    problem.constraint.nutrient_weight = dict(plan.get("nutrient_weight") or {})
    problem.pref_mult = float(plan.get("pref_mult") or 1.0)
    problem.texture_mult = float(plan.get("texture_mult") or 1.0)
    problem.plan_w = PLAN_W if (plan.get("prefer") or plan.get("limit") or plan.get("potassium")) else 0.0
    # 목표치 상향 — 하한(_min)은 올리기만, 상한(_max)은 내리기만 (기준을 느슨하게 만들지 않음)
    c = problem.constraint
    for k, v in (plan.get("targets") or {}).items():
        cur = getattr(c, k, None)
        if k.endswith("_min"):
            setattr(c, k, max(cur or 0, v))
        elif k.endswith("_max"):
            setattr(c, k, min(cur, v) if cur else v)
    return problem


NUT_KO = {"sodium": "나트륨", "energy": "열량", "protein": "단백질", "fiber": "식이섬유", "potassium": "칼륨"}
NUT_UNIT = {"sodium": "mg", "energy": "kcal", "protein": "g", "fiber": "g", "potassium": "mg"}
SRC_LABEL = {"F_NUT_PROTEIN": "단백질 급원", "F_NUT_CALCIUM": "칼슘 급원", "F_NUT_FIBER": "식이섬유 급원", "F_NUT_VITD": "비타민 D 급원"}
PREF_IDS = {"F_LOW_INTAKE", "F_COMPONENT_LOW", "F_SATISFACTION", "F_MENU_WORST"}
TEXTURE_IDS = {"F_TEXTURE_NEED", "F_TEXTURE_GAP"}
N_BASE = 3000          # 비교 기준: 같은 후보에서 메뉴를 무작위로 고른 끼니 수


def _meal_stats(meals, recipes, plan, c):
    """끼니 목록(각 끼니 = 메뉴 dict 6개) → 끼니당 지표 합계 (평균은 호출한 쪽에서)"""
    from .problem import NUTRIENTS
    limit = plan.get("limit") or []
    st = {"n": 0, "nut": {k: 0.0 for k in NUTRIENTS}, "ok": {}, "limit": 0, "src": {}, "pref": 0.0, "pref_n": 0, "tex_bad": 0}
    srcs = {iid: [k for k in (MENU_DIRECTIVES[iid].get("prefer") or []) if k not in limit] for iid in SRC_LABEL}
    for mm in meals:
        st["n"] += 1
        for k in NUTRIENTS:
            v = sum(float(m.get(k) or 0) for m in mm)
            st["nut"][k] += v
            lo, hi = getattr(c, f"{k}_min", None), getattr(c, f"{k}_max", None)
            if lo or hi:
                st["ok"][k] = st["ok"].get(k, 0) + int((not lo or v >= lo) and (not hi or v <= hi))
        for m in mm:
            if m.get("category") not in SCORED:
                continue
            t = _menu_text(m, recipes)
            if limit and any(y in t for y in limit):
                st["limit"] += 1
            else:
                for iid, kws in srcs.items():
                    if kws and any(x in t for x in kws):
                        st["src"][iid] = st["src"].get(iid, 0) + 1
            st["pref"] += float(m.get("preference_score", 0.7) or 0.7)
            st["pref_n"] += 1
        st["tex_bad"] += int(any(x.get("texture") == "부적합" for x in mm[1:]))
    return st


def _better(k, lo, hi):
    if lo and hi:
        return "range"
    return "down" if (hi and not lo) or k == "sodium" else "up"


def _range_gap(v, lo, hi):
    return max(0.0, (lo or v) - v) + max(0.0, v - (hi or v))


def _fmt(x):
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _ok_label(k, lo, hi):
    ko, u = NUT_KO.get(k, k), NUT_UNIT.get(k, "")
    if lo and hi:
        return f"{ko} 기준 범위({_fmt(lo)}~{_fmt(hi)} {u}) 안 끼니"
    if lo:
        return f"{ko} 기준({_fmt(lo)} {u}) 이상 끼니"
    return f"{ko} 기준({_fmt(hi)} {u}) 이내 끼니"


def _baseline_meals(problem, n=N_BASE, seed=0):
    import random
    from .problem import MEAL_SETS, DAILY_SLOTS
    rng = random.Random(seed)
    cats = [cat for _, cat in DAILY_SLOTS[:len(MEAL_SETS["아침"])]]
    return [[rng.choice(problem.pool[cat]) for cat in cats] for _ in range(n)]


def _plan_meals(problem, chrom):
    from .problem import MEAL_SETS, N_DAYS, N_SLOTS
    menus = problem.effective_menus(chrom)
    out = []
    for day in range(N_DAYS):
        dm = menus[day * N_SLOTS:(day + 1) * N_SLOTS]
        for _, slots in MEAL_SETS.items():
            out.append([dm[s] for s in slots])
    return out


def _nut_checks(meals, c, keys):
    """영양소별 (끼니 평균, 기준 충족 끼니 비율 %)"""
    out = {}
    n = len(meals) or 1
    for k in keys:
        vals = [sum(float(m.get(k) or 0) for m in mm) for mm in meals]
        lo, hi = getattr(c, f"{k}_min", None), getattr(c, f"{k}_max", None)
        ok = sum(1 for v in vals if (not lo or v >= lo) and (not hi or v <= hi)) if (lo or hi) else None
        out[k] = (sum(vals) / n, None if ok is None else 100 * ok / n, lo, hi)
    return out


def guard_candidates(problem, Xf, plan: dict) -> dict:
    """[B] 파레토 후보 중 개선안이 겨냥한 영양소가 비교 기준(같은 후보 무작위 식단)보다 나빠지지 않는 후보 번호.
    검사: 기준 충족 끼니 비율이 1끼(≈1.2%p) 넘게 줄지 않고, 평균이 나쁜 쪽으로 가지 않을 것
          (하한만 있으면 평균 ≥ 기준, 상한만 있으면 ≤, 범위면 범위까지 거리 ≤).
    → {"keep": [후보 번호], "checked": [...], "fallback": bool, "detail": {후보: 실패 항목}}"""
    keys = [k for k in (plan.get("nutrient_weight") or {})]
    if not keys:
        return {"keep": list(range(len(Xf))), "checked": [], "fallback": False, "detail": {}}
    c = problem.constraint
    base = _nut_checks(_baseline_meals(problem), c, keys)
    tol = 100 / 84 + 1e-6
    fails = {}
    for i, x in enumerate(Xf):
        cur = _nut_checks(_plan_meals(problem, x), c, keys)
        bad = []
        for k in keys:
            (ma, pa, lo, hi), (mb, pb, _, _) = cur[k], base[k]
            b = _better(k, lo, hi)
            if b == "range":
                worse_mean = _range_gap(ma, lo, hi) > _range_gap(mb, lo, hi) + 1e-9
            elif b == "up":
                worse_mean = ma < mb
            else:
                worse_mean = ma > mb
            if worse_mean:
                bad.append(f"{NUT_KO.get(k, k)} 평균")
            if pa is not None and pb is not None and pa < pb - tol:
                bad.append(f"{NUT_KO.get(k, k)} 기준 충족")
        fails[i] = bad
    keep = [i for i, b in fails.items() if not b]
    fallback = False
    if not keep:                      # 모두 걸리면 실패 항목이 가장 적은 후보들
        m = min(len(b) for b in fails.values())
        keep = [i for i, b in fails.items() if len(b) == m]
        fallback = True
    return {"keep": keep, "checked": keys, "fallback": fallback,
            "detail": {int(i): b for i, b in fails.items() if b}}


def evaluate(problem, chrom, plan: dict, pool_log: dict | None = None) -> dict:
    """설계된 28일 식단이 개선안을 얼마나 반영했는지 — 개선안 항목마다 '이 식단' vs '같은 후보에서 무작위로 고른 식단(기대값)'"""
    import random
    from .problem import MEAL_SETS, N_DAYS, N_SLOTS, DAILY_SLOTS
    from .inventory import recipe_ingredients
    recipes = recipe_ingredients()
    menus = problem.effective_menus(chrom)
    c = problem.constraint
    meals = []
    for day in range(N_DAYS):
        dm = menus[day * N_SLOTS:(day + 1) * N_SLOTS]
        for _, slots in MEAL_SETS.items():
            meals.append([dm[s] for s in slots])
    # 비교 기준: 같은 후보 풀(제외 메뉴를 뺀 뒤)에서 칸마다 무작위로 고른 끼니
    rng = random.Random(0)
    cats = [cat for _, cat in DAILY_SLOTS[:len(MEAL_SETS["아침"])]]
    pool = problem.pool
    base_meals = [[rng.choice(pool[cat]) for cat in cats] for _ in range(N_BASE)]
    A, B = _meal_stats(meals, recipes, plan, c), _meal_stats(base_meals, recipes, plan, c)
    nA, scale = A["n"] or 1, (A["n"] or 1) / N_BASE      # 무작위 횟수는 28일(끼니 수)로 환산

    def avg(st, k): return round(st["nut"][k] / (st["n"] or 1), 1)
    def okp(st, k): return round(100 * st["ok"].get(k, 0) / (st["n"] or 1), 1) if k in st["ok"] else None
    def cnt(v_a, v_b): return v_a, round(v_b * scale, 1)

    limit = plan.get("limit") or []
    effects = []
    for it in plan.get("items") or []:
        iid, d = it.get("id"), MENU_DIRECTIVES.get(it.get("id"), {})
        rows = []
        for k in (d.get("weight") or {}):
            lo, hi = getattr(c, f"{k}_min", None), getattr(c, f"{k}_max", None)
            better = _better(k, lo, hi)
            rows.append({"label": f"{NUT_KO.get(k, k)} 끼니 평균", "value": avg(A, k), "base": avg(B, k),
                         "unit": NUT_UNIT.get(k, ""), "better": better, "range": [lo, hi] if better == "range" else None})
            if okp(A, k) is not None:
                rows.append({"label": _ok_label(k, lo, hi), "value": okp(A, k), "base": okp(B, k), "unit": "%", "better": "up"})
        if d.get("limit"):
            a, b = cnt(A["limit"], B["limit"])
            rows.append({"label": "장아찌·젓갈·가공육·어묵 메뉴 (28일)", "value": a, "base": b, "unit": "회", "better": "down"})
        if d.get("potassium"):
            rows.append({"label": "칼륨 끼니 평균", "value": avg(A, "potassium"), "base": avg(B, "potassium"), "unit": "mg", "better": "up"})
        if iid in SRC_LABEL:
            a, b = cnt(A["src"].get(iid, 0), B["src"].get(iid, 0))
            rows.append({"label": f"{SRC_LABEL[iid]} 메뉴 (28일, 국·주찬·부찬)", "value": a, "base": b, "unit": "회", "better": "up"})
        if iid in PREF_IDS:
            rows.append({"label": "고른 메뉴의 평균 섭취율 (잔반 기록)", "value": round(100 * A["pref"] / (A["pref_n"] or 1), 1),
                         "base": round(100 * B["pref"] / (B["pref_n"] or 1), 1), "unit": "%", "better": "up"})
        if iid in TEXTURE_IDS:
            a, b = cnt(A["tex_bad"], B["tex_bad"])
            rows.append({"label": "다진찬 부적합 메뉴가 든 끼니 (28일)", "value": a, "base": b, "unit": "끼", "better": "down"})
        if d.get("avoid"):
            removed = (pool_log or {}).get("removed") or []
            used = sum(1 for m in menus if _norm(m.get("menu_name")) in {_norm(x) for x in plan.get("avoid_menus") or []})
            rows.append({"label": f"잔반 많은 메뉴 사용 (후보에서 {len(removed)}개 제외)", "value": used, "base": None, "unit": "회", "better": "down"})
        for r in rows:
            if r["base"] is not None and r["value"] is not None:
                diff = r["value"] - r["base"]
                r["diff"] = round(diff, 1)
                if r["better"] == "range":   # 범위 기준: 범위까지의 거리가 줄었으면 좋음 (평균이 낮아져도 상한 안으로 들어오면 개선)
                    lo, hi = r["range"]
                    r["good"] = _range_gap(r["value"], lo, hi) < _range_gap(r["base"], lo, hi) or \
                        (_range_gap(r["value"], lo, hi) == 0 and _range_gap(r["base"], lo, hi) == 0 and diff == 0)
                else:
                    r["good"] = (diff > 0) if r["better"] == "up" else (diff < 0)
        effects.append({**it, "rows": rows})

    # 식단표 표시용: 이 식단에 쓰인 메뉴 중 개선안으로 선호·제한된 메뉴 → 어떤 개선안 때문인지
    tags, counts = {}, {}
    src_kws = {iid: [k for k in (MENU_DIRECTIVES[iid].get("prefer") or []) if k not in limit] for iid in SRC_LABEL}
    item_ids = {x.get("id") for x in plan.get("items") or []}
    k_cut = {}
    if plan.get("potassium"):
        for cat in ("국", "부찬"):
            ks = sorted(float(m.get("potassium") or 0) for m in pool.get(cat, []))
            k_cut[cat] = ks[int(len(ks) * 0.75)] if ks else None
    for m in menus:
        if m.get("category") not in SCORED:
            continue
        name = m.get("menu_name")
        t = _menu_text(m, recipes)
        tg = []
        if limit and any(y in t for y in limit):
            tg.append({"kind": "limit", "label": "나트륨 개선안: 제한 메뉴"})
        else:
            for iid, kws in src_kws.items():
                if iid in item_ids and kws and any(x in t for x in kws):
                    tg.append({"kind": "prefer", "label": f"{SRC_LABEL[iid]} (선호)"})
            cut = k_cut.get(m.get("category"))
            if cut is not None and float(m.get("potassium") or 0) >= cut:
                tg.append({"kind": "prefer", "label": "칼륨 많은 메뉴 (선호)"})
        if tg:
            tags[name] = tg
            counts[name] = counts.get(name, 0) + 1
    for e in effects:
        lab = SRC_LABEL.get(e["id"])
        if lab:
            e["examples"] = sorted(((n, k) for n, k in counts.items() if any(g["label"].startswith(lab) for g in tags[n])), key=lambda x: -x[1])[:6]
        elif e["id"] == "F_NUT_SODIUM":
            e["examples"] = sorted(((n, k) for n, k in counts.items() if any(g["kind"] == "limit" for g in tags[n])), key=lambda x: -x[1])[:6]
            e["examples_label"] = "그래도 들어간 제한 메뉴"

    na = [sum(float(m.get("sodium") or 0) for m in mm) for mm in meals]
    out = {   # 이전 화면 호환
        "끼니": len(meals),
        "나트륨_끼니평균_mg": round(sum(na) / len(na)) if na else None,
        "나트륨_기준이내_끼니_%": round(100 * sum(v <= (c.sodium_max or 1e9) for v in na) / len(na), 1) if na else None,
        "칼륨_끼니평균_mg": round(avg(A, "potassium")),
        "제한_메뉴_횟수": A["limit"],
        "개선안_부합도_평균": round(sum(m.get("plan_score", 0.5) for m in menus) / len(menus), 3) if menus else None,
    }
    return {"items": plan.get("items") or [], "outside": plan.get("outside") or [],
            "weights": plan.get("nutrient_weight") or {}, "targets": plan.get("targets") or {},
            "pref_mult": plan.get("pref_mult"),
            "texture_mult": plan.get("texture_mult"), "pool": pool_log or {}, "result": out,
            "effects": effects, "menu_tags": tags, "baseline": f"같은 후보 메뉴에서 칸마다 무작위로 고른 {N_BASE}끼(28일로 환산)"}
