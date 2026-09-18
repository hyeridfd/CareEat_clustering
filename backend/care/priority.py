# -*- coding: utf-8 -*-
"""
돌봄 우선순위 점수 (0–100, 설명 가능한 가산식)

  점수 = 유형 위험가중 + 현재 상태 위험요인 + 최근 변화(직전 평가 대비) + 유형 전이 + 경계 사례
  → 시설 내 정렬, 등급(high/medium/low) 부여. 각 요인은 factors 로 저장해 화면·솔루션·보호자 안내에 사용.

임계값은 선별도구 일반 기준을 따름: MNA-SF 0–7 영양불량 / 8–11 영양불량 위험, BMI < 18.5 저체중.
배점은 운영 데이터(결과 기록)가 쌓이면 재보정하는 것을 전제로 한 초기값.
"""
from __future__ import annotations

LEVEL_HIGH = 45
LEVEL_MEDIUM = 20


def _v(f, k):
    x = (f or {}).get(k)
    return None if x is None else float(x)


def compute(features: dict, prev_features: dict | None, type_info: dict, transition: dict, is_borderline: bool):
    f = features
    factors = []

    def add(code, label, points, value=None, kind="status"):
        factors.append({"code": code, "label": label, "points": points, "value": value, "kind": kind})

    rw = float(type_info.get("risk_weight", 0) or 0)
    if rw:
        add("type_risk", f"유형: {type_info.get('name')}", rw, type_info.get("code"), "type")

    mna = _v(f, "mna_sf")
    if mna is not None:
        if mna <= 7:
            add("mna_malnourished", "영양불량 (MNA-SF 0–7)", 25, mna)
        elif mna <= 11:
            add("mna_at_risk", "영양불량 위험 (MNA-SF 8–11)", 12, mna)
    bmi = _v(f, "bmi")
    if bmi is not None and bmi < 18.5:
        add("low_bmi", "저체중 (BMI < 18.5)", 10, round(bmi, 1))

    it = _v(f, "intake_total")
    if it is not None:
        if it < 50:
            add("intake_very_low", "식사 섭취율 50% 미만", 20, round(it))
        elif it < 75:
            add("intake_low", "식사 섭취율 50–75%", 10, round(it))
    im = _v(f, "intake_main")
    if im is not None and im < 50 and (it is None or it >= 50):
        add("protein_dish_low", "주찬(단백질 반찬) 섭취 50% 미만", 5, round(im))

    if _v(f, "swallowing_difficulty") == 1:
        add("swallowing", "삼킴 어려움", 12, 1)
    if _v(f, "chewing_difficulty") == 1:
        add("chewing", "씹기 어려움", 6, 1)
    dep = _v(f, "eating_dependence")
    if dep is not None and dep >= 2:
        add("eating_full_help", "식사 전적 도움 필요", 6, dep)
    elif dep is not None and dep >= 1:
        add("eating_partial_help", "식사 부분 도움 필요", 3, dep)
    gds = _v(f, "gds")
    if gds is not None and gds >= 8:
        add("depressive", "우울 척도 높음 (GDS-SF ≥ 8)", 8, round(gds, 1))
    kmbi = _v(f, "kmbi_pct")
    if kmbi is not None and kmbi < 40:
        raw, mx = _v(f, "kmbi_score"), _v(f, "kmbi_max")
        detail = f"{round(kmbi)}% (원점수 {round(raw)}/{round(mx)}점)" if raw is not None and mx else round(kmbi)
        add("adl_low", "일상생활 수행 크게 저하 (K-MBI < 40%)", 5, detail)

    # 최근 변화 (직전 평가 지표 대비)
    p = prev_features or {}
    w0, w1 = _v(p, "weight_kg"), _v(f, "weight_kg")
    if w0 and w1 and (w0 - w1) / w0 >= 0.05:
        add("weight_loss", "체중 5% 이상 감소", 15, f"{w0:.1f}→{w1:.1f}kg", "trend")
    m0 = _v(p, "mna_sf")
    if m0 is not None and mna is not None and m0 - mna >= 2:
        add("mna_drop", "MNA-SF 2점 이상 하락", 8, f"{m0:.0f}→{mna:.0f}", "trend")
    i0 = _v(p, "intake_total")
    if i0 is not None and it is not None and i0 - it >= 15:
        add("intake_drop", "섭취율 15%p 이상 감소", 10, f"{i0:.0f}→{it:.0f}%", "trend")
    k0 = _v(p, "kmbi_pct")
    if k0 is not None and kmbi is not None and k0 - kmbi >= 10:
        add("adl_drop", "K-MBI 10%p 이상 저하", 5, f"{k0:.0f}→{kmbi:.0f}%", "trend")

    if transition.get("kind") == "state_change":
        add("type_transition", f"유형 변화 ({transition.get('prev_type')}→{type_info.get('code')})", 8, None, "trend")
    if is_borderline:
        add("borderline", "유형 경계 사례 (담당자 확인 필요)", 3, None, "review")
    if _v(f, "has_nutrition") == 0:
        add("no_nutrition", "영양(잔반) 조사 미완료 — 섭취 지표 추정값", 0, None, "review")

    score = min(100.0, sum(x["points"] for x in factors))
    level = "high" if score >= LEVEL_HIGH else "medium" if score >= LEVEL_MEDIUM else "low"
    factors.sort(key=lambda x: -x["points"])
    return round(score, 1), level, factors


LEVEL_LABEL = {"high": "우선 관리", "medium": "주의 관찰", "low": "정기 관리"}
