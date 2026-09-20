# -*- coding: utf-8 -*-
"""
Care-Eat Insight — 시설 문제 탐지와 관리 우선순위

  개인 규칙(care_rules)과 다른 점
    개인: "이 어르신이 X면 Y하라"
    시설: "X에 해당하는 어르신이 N% 이상이면, 식단·조리·배식을 바꿔라"
          → 핵심 조건은 prevalence(규모)다. 3명이면 개인 대응, 30명이면 운영 문제다.

  점수 = 규모(impact 0~100) × 심각도(severity 1~3) ÷ 3
    담당자가 "왜 이게 1순위인가"를 숫자로 확인할 수 있어야 하므로
    산식을 숨기지 않고 근거(basis)와 함께 그대로 돌려준다.

  각 규칙은 RAG 질의(query)를 갖는다 → Action 단계에서 지침 근거를 붙인다.
"""
from __future__ import annotations

AREA = {
    "nutrition": "영양",
    "meal": "식사 운영",
    "texture": "식형태",
    "menu": "메뉴",
    "process": "돌봄 프로세스",
    "data": "데이터",
}

SEVERITY_LABEL = {3: "시급", 2: "주의", 1: "관찰"}


# ─────────────────────────── 프로파일 조회 헬퍼 ───────────────────────────

def _risk(p, key):
    for r in p.get("risks") or []:
        if r["key"] == key:
            return r
    return {}


def _nut(p, key):
    for r in p.get("nutrients") or []:
        if r["key"] == key:
            return r
    return {}


def _comp(p, key):
    for c in (p.get("intake") or {}).get("components") or []:
        if c["key"] == key:
            return c
    return {}


def _nut_denom(p) -> int:
    return max([(r.get("denom") or 0) for r in (p.get("nutrients") or [])] or [0])


# ─────────────────────────── 규칙 ───────────────────────────
# make(p) → None 이면 해당 없음, dict 면 {impact, detail, basis, action, query}
RULES = []


def rule(id, area, severity, title, needs_nutrition=False):
    def deco(fn):
        RULES.append({"id": id, "area": area, "severity": severity, "title": title,
                      "needs_nutrition": needs_nutrition, "make": fn})
        return fn
    return deco


# ── 데이터 품질: 진단의 신뢰도가 먼저다 ──
@rule("F_DATA_COVERAGE", "data", 3, "평가가 끝나지 않아 시설 진단을 신뢰하기 어렵습니다")
def _f_cov(p):
    cov = p.get("coverage_pct")
    if cov is None or cov >= 80:
        return None
    n_miss = (p.get("n_residents") or 0) - (p.get("n_assessed") or 0)
    return {"impact": 100 - cov,
            "detail": f"어르신 {p['n_residents']}명 중 {p['n_assessed']}명만 평가 완료 ({cov}%)",
            "basis": f"미평가 {n_miss}명",
            "action": "미평가 어르신의 조사를 마치고 평가를 실행합니다. 그 전까지 아래 비율은 일부만 반영된 값입니다.",
            "query": None}


@rule("F_DATA_NUTRITION", "data", 2, "섭취 영양소가 계산된 어르신이 적습니다")
def _f_nut_cov(p):
    den, n = _nut_denom(p), p.get("n_assessed") or 0
    if not n or den >= n * 0.8:
        return None
    return {"impact": round(100 * (n - den) / n, 1),
            "detail": f"평가 {n}명 중 {den}명만 영양소 계산됨",
            "basis": "식사(잔반) 조사 미완 또는 평가가 조사보다 앞섬",
            "action": "식사 조사를 마친 뒤 전체 재평가를 실행하면 영양소 지표가 채워집니다.",
            "query": None}


# ── 영양 ──
@rule("F_NUT_ENERGY", "nutrition", 3, "에너지 섭취가 기준에 못 미치는 어르신이 많습니다", True)
def _f_energy(p):
    r = _nut(p, "energy")
    if not r.get("pct") or r["pct"] < 30:
        return None
    return {"impact": r["pct"],
            "detail": f"에너지 기준 80% 미만 {r['n']}/{r['denom']}명 ({r['pct']}%)",
            "basis": "2025 한국인 영양소 섭취기준 대비",
            "action": "같은 양으로 열량이 높아지도록 조리를 강화하고, 끼니 사이 간식을 정규 운영에 넣습니다.",
            "query": "노인 저체중 영양불량 영양 강화 조리 에너지 단백질 보충 간식 추가"}


@rule("F_NUT_PROTEIN", "nutrition", 3, "단백질 섭취가 부족한 어르신이 많습니다", True)
def _f_protein(p):
    r = _nut(p, "protein")
    if not r.get("pct") or r["pct"] < 30:
        return None
    return {"impact": r["pct"],
            "detail": f"단백질 기준 80% 미만 {r['n']}/{r['denom']}명 ({r['pct']}%)",
            "basis": "근감소증 예방 권고는 체중 1kg당 1.2g 이상",
            "action": "매 끼니에 단백질 반찬을 배치하고(한 끼에 몰지 않음), 부드러운 단백질 급원을 늘립니다.",
            "query": "근감소증 예방 단백질 체중 1kg당 1.2g 세 끼 나누어 섭취"}


@rule("F_NUT_CALCIUM", "nutrition", 2, "칼슘 섭취가 부족한 어르신이 많습니다", True)
def _f_ca(p):
    r = _nut(p, "ca")
    if not r.get("pct") or r["pct"] < 50:
        return None
    return {"impact": r["pct"],
            "detail": f"칼슘 기준 80% 미만 {r['n']}/{r['denom']}명 ({r['pct']}%)",
            "basis": "노인급식시설 이용자의 50% 이상이 칼슘 섭취 부족",
            "action": "우유·유제품 제공 횟수를 늘리고, 생선조림에 우유를 쓰는 등 조리로 칼슘을 강화합니다.",
            "query": "칼슘 급원 식품 우유 유제품 뼈째 먹는 생선 영양 강화 조리"}


@rule("F_NUT_SODIUM", "nutrition", 3, "나트륨 섭취가 기준을 넘는 어르신이 많습니다", True)
def _f_na(p):
    r = _nut(p, "na")
    if not r.get("pct") or r["pct"] < 30:
        return None
    low = _risk(p, "low_intake").get("pct") or 0
    act = ("국물 제공량과 절임 반찬 배식량을 조정합니다."
           if low < 25 else
           "저섭취군이 함께 많으므로 배식량을 줄이기보다 조리 단계에서 염도를 낮춥니다(총량 유지).")
    return {"impact": r["pct"],
            "detail": f"나트륨 기준 130% 초과 {r['n']}/{r['denom']}명 ({r['pct']}%)",
            "basis": f"저섭취군 {low}% · 염분감수성은 고령자에서 더 높음",
            "action": act,
            "query": "삼삼한 조리 전략 국물 줄이기 천연조미료 향신채 염도 저감"}


@rule("F_NUT_FIBER", "nutrition", 2, "식이섬유 섭취가 부족한 어르신이 많습니다", True)
def _f_fiber(p):
    r = _nut(p, "fiber")
    if not r.get("pct") or r["pct"] < 40:
        return None
    return {"impact": r["pct"],
            "detail": f"식이섬유 기준 80% 미만 {r['n']}/{r['denom']}명 ({r['pct']}%)",
            "basis": "2025 기준 50세 이상 남 30g / 여 25g",
            "action": "잡곡·나물·생과일 제공 빈도를 늘립니다. 씹기 어려운 분께는 익힌 나물로 대체합니다.",
            "query": "노인 식이섬유 섭취 늘리는 방법 통곡류 채소 생과일"}


@rule("F_NUT_VITD", "nutrition", 1, "비타민 D 섭취가 거의 채워지지 않습니다", True)
def _f_vd(p):
    r = _nut(p, "vd")
    if not r.get("pct") or r["pct"] < 60:
        return None
    return {"impact": r["pct"],
            "detail": f"비타민 D 기준 80% 미만 {r['n']}/{r['denom']}명 ({r['pct']}%)",
            "basis": "식품만으로 채우기 어려운 영양소 — 낮 시간 활동과 함께 관리",
            "action": "버섯·등푸른생선 제공을 늘리고, 낮 시간 실외 활동 시간을 프로그램에 넣습니다. 보충 필요 여부는 의료진과 상의합니다.",
            "query": "노인 비타민D 부족 햇빛 식품 골다공증 칼슘"}


# ── 위험군 ──
@rule("F_MALNUT", "nutrition", 3, "영양불량 위험군 비율이 높습니다")
def _f_malnut(p):
    r = _risk(p, "malnutrition_risk")
    if not r.get("pct") or r["pct"] < 25:
        return None
    bad = _risk(p, "malnourished")
    return {"impact": r["pct"],
            "detail": f"MNA-SF 11점 이하 {r['n']}/{p['n_assessed']}명 ({r['pct']}%) · 영양불량 {bad.get('n', 0)}명",
            "basis": "선별 도구 일반 기준 (0–7 영양불량 / 8–11 위험)",
            "action": "위험군 체중을 월 2회 이상 측정하고, 강화식·간식을 정규 운영에 포함합니다.",
            "query": "노인 저영양 선별 체계적 평가 개별 중재 모니터링 체중 측정"}


@rule("F_UNDERWEIGHT", "nutrition", 3, "저체중 어르신 비율이 높습니다")
def _f_under(p):
    r = _risk(p, "underweight")
    if not r.get("pct") or r["pct"] < 15:
        return None
    return {"impact": r["pct"],
            "detail": f"BMI 18.5 미만 {r['n']}/{p['n_assessed']}명 ({r['pct']}%)",
            "basis": "저체중은 에너지 필요량이 오히려 큰 구간(32~38 kcal/kg)",
            "action": "저체중군에 고열량·고단백 간식을 별도 운영하고 체중 변화를 2주 간격으로 확인합니다.",
            "query": "노인 저체중 에너지 필요량 경구영양보충 간식"}


@rule("F_TEXTURE_NEED", "texture", 2, "식형태 조정이 필요한 어르신이 많습니다")
def _f_tex(p):
    r = _risk(p, "texture_need")
    if not r.get("pct") or r["pct"] < 20:
        return None
    chew = _risk(p, "chewing").get("pct") or 0
    swal = _risk(p, "swallowing").get("pct") or 0
    return {"impact": r["pct"],
            "detail": f"식형태 조정 필요 {r['n']}/{p['n_assessed']}명 ({r['pct']}%) · 씹기 {chew}% · 삼킴 {swal}%",
            "basis": "형태 조정식은 섭취량과 영양이 함께 줄기 쉬움",
            "action": "부드러운 단백질 반찬을 늘리고, 형태 조정식에는 영양 강화를 함께 적용합니다. 식형태 단계 기준을 문서로 정합니다.",
            "query": "먹기 쉬운 조리 전략 부드럽게 연육 다진 식재료 촉촉하게 형태 조정식 영양 강화"}


@rule("F_EATING_HELP", "process", 2, "식사 도움이 필요한 어르신이 많습니다")
def _f_help(p):
    r = _risk(p, "eating_help")
    if not r.get("pct") or r["pct"] < 30:
        return None
    return {"impact": r["pct"],
            "detail": f"식사 도움 필요 {r['n']}/{p['n_assessed']}명 ({r['pct']}%)",
            "basis": "식사 돕기는 하루 에너지·단백질 섭취를 유의하게 개선",
            "action": "끼니마다 도움 인력 배치를 고정하고 식사 시간을 충분히 확보합니다. 식사 환경(조용한 자리, 함께 먹기)을 함께 조정합니다.",
            "query": "노인 식사 돕기 식사 보조 식사 환경 함께 먹기"}


@rule("F_DEPRESS", "process", 1, "우울 의심 어르신 비율이 높습니다")
def _f_dep(p):
    r = _risk(p, "depressed")
    if not r.get("pct") or r["pct"] < 20:
        return None
    return {"impact": r["pct"],
            "detail": f"GDS-SF 6점 이상 {r['n']}/{p['n_assessed']}명 ({r['pct']}%)",
            "basis": "우울은 식욕 저하와 섭취량 감소로 이어짐",
            "action": "함께 식사하는 자리와 식사 분위기를 개선하고, 프로그램 참여를 늘립니다.",
            "query": "노인 우울 식욕 저하 식사 환경 함께 식사"}


# ── 식사 운영 ──
@rule("F_LOW_INTAKE", "meal", 3, "시설 평균 식사 섭취율이 낮습니다")
def _f_intake(p):
    v = (p.get("intake") or {}).get("total")
    if v is None or v >= 80:
        return None
    return {"impact": 100 - v,
            "detail": f"평균 섭취율 {v}% (기록 {p['intake'].get('n')}명)",
            "basis": "80% 미만이면 제공량이 아니라 섭취량 기준으로 영양을 다시 봐야 함",
            "action": "섭취율이 낮은 끼니와 음식군을 먼저 손봅니다. 제공량을 늘리는 것보다 먹는 양을 늘리는 쪽이 우선입니다.",
            "query": "노인 식사 섭취량 늘리기 식사 환경 간식 영양 강화"}


@rule("F_MEAL_GAP", "meal", 2, "끼니 사이 섭취율 차이가 큽니다")
def _f_meal_gap(p):
    meals = [m for m in ((p.get("menus") or {}).get("by_meal") or []) if m.get("rate") is not None]
    if len(meals) < 2:
        return None
    lo = min(meals, key=lambda m: m["rate"])
    hi = max(meals, key=lambda m: m["rate"])
    gap = round(hi["rate"] - lo["rate"], 1)
    if gap < 10:
        return None
    return {"impact": min(100, gap * 4),
            "detail": f"{lo['label']} {lo['rate']}% vs {hi['label']} {hi['rate']}% (차이 {gap}%p)",
            "basis": f"가장 낮은 끼니: {lo['label']}",
            "action": f"{lo['label']} 메뉴 구성과 제공량을 조정하고, 그 시간대 식사 도움·배식 순서를 점검합니다.",
            "query": "노인 끼니 섭취 저조 조식 메뉴 구성 간식 배치"}


@rule("F_COMPONENT_LOW", "menu", 2, "특정 음식군을 반복적으로 남깁니다")
def _f_comp(p):
    comps = [c for c in ((p.get("intake") or {}).get("components") or []) if c.get("value") is not None]
    low = [c for c in comps if c["value"] < 70]
    if not low:
        return None
    worst = min(low, key=lambda c: c["value"])
    names = ", ".join(f"{c['label']} {c['value']}%" for c in sorted(low, key=lambda c: c["value"]))
    return {"impact": 100 - worst["value"],
            "detail": f"섭취율 70% 미만 음식군: {names}",
            "basis": f"가장 낮은 음식군: {worst['label']}",
            "action": f"{worst['label']}의 조리법·크기·간·배식량을 바꾸거나 대체 반찬을 마련합니다. 선호도 재조사도 함께 합니다.",
            "query": "남기는 반찬 대체 제공 음식 선택권 다양한 반찬 조리법 개선"}


@rule("F_MENU_WORST", "menu", 2, "잔반이 특히 많은 메뉴가 반복됩니다")
def _f_menu(p):
    worst = [m for m in ((p.get("menus") or {}).get("worst") or []) if (m.get("rate") or 100) < 60]
    if len(worst) < 2:
        return None
    top = worst[:3]
    names = ", ".join(f"{m['menu']}({m['rate']}%, {m['cells']}회)" for m in top)
    return {"impact": min(100, len(worst) * 12 + (100 - top[0]["rate"])),
            "detail": f"섭취율 60% 미만 메뉴 {len(worst)}종 — {names}",
            "basis": "메뉴 단위 시설 평균 (같은 메뉴는 제공 횟수를 합산)",
            "action": "해당 메뉴를 식단 개편 후보로 올려 조리법 변경 또는 교체를 검토합니다.",
            "query": "급식 메뉴 개선 선호도 조사 신메뉴 적용 조리법 변경"}


@rule("F_TEXTURE_GAP", "texture", 2, "식형태군 간 섭취율 차이가 큽니다")
def _f_tex_gap(p):
    gs = [g for g in ((p.get("groups") or {}).get("by_texture") or []) if g.get("n", 0) >= 3]
    if len(gs) < 2:
        return None
    lo = min(gs, key=lambda g: g["rate"])
    hi = max(gs, key=lambda g: g["rate"])
    gap = round(hi["rate"] - lo["rate"], 1)
    if gap < 10:
        return None
    return {"impact": min(100, gap * 4),
            "detail": f"{lo['label']} {lo['rate']}%({lo['n']}명) vs {hi['label']} {hi['rate']}%({hi['n']}명)",
            "basis": f"차이 {gap}%p",
            "action": f"{lo['label']} 대상 메뉴의 맛·질감·영양밀도를 점검합니다. 형태만 바꾸고 영양 강화가 빠지지 않았는지 확인합니다.",
            "query": "형태 조정식 영양 강화 섭취량 모니터링 식사 형태 단계"}


@rule("F_SATISFACTION", "meal", 1, "급식 만족도가 낮은 어르신이 많습니다")
def _f_sat(p):
    r = _risk(p, "low_satisfaction")
    if not r.get("pct") or r["pct"] < 20:
        return None
    return {"impact": r["pct"],
            "detail": f"급식 만족 3점 이하 {r['n']}/{p['n_assessed']}명 ({r['pct']}%)",
            "basis": "만족도는 섭취량과 함께 움직임",
            "action": "선호도 조사를 다시 하고, 매 끼니 한 가지는 기호에 맞는 음식을 배치합니다. 신메뉴를 주기적으로 넣습니다.",
            "query": "급식 만족도 선호도 조사 신메뉴 적용 전략 음식 선택권"}


# ─────────────────────────── 실행 ───────────────────────────

def analyze(profile: dict, min_nutrition_denom: int = 5) -> list:
    """시설 프로파일 → 관리 우선순위 목록 (점수 내림차순)."""
    den = _nut_denom(profile)
    out = []
    for r in RULES:
        if r["needs_nutrition"] and den < min_nutrition_denom:
            continue                      # 표본이 너무 적으면 영양소 기반 문제는 판단하지 않는다
        try:
            hit = r["make"](profile)
        except Exception:
            hit = None
        if not hit:
            continue
        impact = round(float(hit["impact"]), 1)
        score = round(impact * r["severity"] / 3, 1)
        out.append({
            "id": r["id"], "area": r["area"], "area_label": AREA.get(r["area"], r["area"]),
            "title": r["title"], "severity": r["severity"],
            "severity_label": SEVERITY_LABEL[r["severity"]],
            "impact": impact, "score": score,
            "detail": hit["detail"], "basis": hit.get("basis"),
            "action": hit.get("action"), "query": hit.get("query"),
        })
    out.sort(key=lambda x: -x["score"])
    for i, x in enumerate(out, 1):
        x["rank"] = i
    return out
