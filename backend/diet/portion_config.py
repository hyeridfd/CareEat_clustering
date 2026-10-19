"""
portion_config.py  ─  카테고리별 표준 배식 비율
================================================
레시피 1인분(표준량)에 곱하는 배식 비율입니다.
영양소 · 중량(weight) · 비용(cost)이 모두 이 비율만큼 늘거나 줄어듭니다.

  · 나트륨 밀도(mg/kcal)가 높은 국·김치·부찬은 줄이고,
    나트륨이 거의 없는 밥으로 열량을 채우는 방식이 효과적입니다.
      (후보 평균 기준: 밥 0.01 / 주찬 2.1 / 부찬 3.4 / 국 4.1 / 김치 13.7 mg/kcal)
  · 1.0 = 레시피 표준량 그대로
  · 개인별 배식량(serving_agent의 ratio)은 이 표준량 위에 추가로 곱해집니다.
  · 조합별 결과는 portion_sensitivity.py 로 확인

적용 위치: sodium_config.apply_sodium_adjustment() 안에서 나트륨 보정과 함께 적용
           (원본 값은 각 메뉴의 "_raw"에 보존 → 여러 번 적용해도 중복되지 않음)
"""

# [2026-10-12] 선택지 B 적용 (모든 항목 0.5 이상, seasoning_sensitivity.py 결과 기준)
PORTION = {
    "밥":   1.0,
    "국":   0.5,   # 국물 감량·건더기 위주
    "주찬": 0.8,   # 단백질 공급원 → 과도하게 줄이지 않기
    "부찬": 0.5,
    "김치": 0.5,
}

# 비율로 함께 조정되는 수치 항목 (CandidateAgent pool의 키)
SCALED_KEYS = ["energy", "protein", "fat", "sugar", "fiber", "sodium", "carb",
               "sat_fat", "potassium", "vit_d", "cost", "weight"]
