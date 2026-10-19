"""
ingredient_policy.py  ─  지식그래프 질환-재료 관계의 4단계 분류
================================================================
Neo4j의 (Disease)-[:FORBIDDEN_INGREDIENT]->(Recipe) 관계를 재료별로 나눠 처리합니다.

  금기 (HARD)    : 후보 메뉴에서 제외                     ← 목록에 없는 금기 재료의 기본값
  제한 (LIMIT)   : 제외하지 않음. 영양 기준으로 양을 관리   (나트륨·당류·탄수화물·포화지방 등)
  주의 (CAUTION) : 제외하지 않음. 선호 점수를 낮춰 덜 선택되게
  권장           : (Disease)-[:RECOMMENDED_INGREDIENT] → 후보 조건(1개 이상 포함)

※ 그래프에 새 금기 재료가 추가되면, 여기 등록하기 전까지는 안전하게 '금기'로 처리됩니다.
※ 재료 이름은 Recipe 노드의 title 속성과 정확히 같아야 합니다.
"""

# ── 제한: 양 문제 → 영양 기준으로 관리 ───────────────────────────
LIMIT_INGREDIENTS = {
    "소금":         "나트륨 기준 (sodium_config.py)",
    "백설탕":       "당류 기준",
    "올리고당":     "당류 기준  ※ 그래프의 food_label이 '베리'로 연결됨 → 데이터 확인 필요",
    "백미":         "탄수화물·열량 기준 (식사당 줄인 양)",
    "찹쌀":         "탄수화물·열량 기준 (식사당 줄인 양)",
    "쌀국수":       "탄수화물·열량 기준 (식사당 줄인 양)",
    "감자":         "탄수화물 기준 (당뇨: 곡류처럼 분량 조절)",
    "돼지고기":     "포화지방 기준 (근거 1건, 노인 단백질 공급원)",
    "쇠고기(등심)": "포화지방 기준 (근거 1건, 노인 단백질 공급원)",
}

# ── 주의: 선호 점수 감점 ─────────────────────────────────────────
CAUTION_INGREDIENTS = {
    "고기만두": "가공식품 (나트륨·정제 탄수화물)",
}
CAUTION_PENALTY = 0.2      # 주의 재료가 들어간 메뉴의 preference_score 감점 (최저 0.1)


def non_hard_titles() -> list[str]:
    """금기 필터에서 제외할(=금기로 보지 않을) 재료 목록"""
    return sorted(set(LIMIT_INGREDIENTS) | set(CAUTION_INGREDIENTS))


def caution_titles() -> list[str]:
    return sorted(CAUTION_INGREDIENTS)


def apply_caution_penalty(pool: dict, verbose: bool = True) -> dict:
    """caution_ingredients가 있는 메뉴의 preference_score를 감점"""
    hit = []
    for cat, menus in pool.items():
        for m in menus:
            if m.get("caution_ingredients"):
                base = m.get("preference_score", 0.7)
                m["preference_score"] = round(max(0.1, base - CAUTION_PENALTY), 3)
                hit.append(f"{m['menu_name']}({','.join(m['caution_ingredients'])})")
    if verbose and hit:
        print(f"  [재료 정책] 주의 재료 감점 {len(hit)}개: " + ", ".join(hit))
    return pool
