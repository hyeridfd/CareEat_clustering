"""
sodium_config.py  ─  나트륨 기준 · 양념 감량 · 고염 메뉴 제외 설정
===================================================================
[기준] KDRI 2025 만성질환위험감소섭취량(CDRR)
       65~74세 1,900 mg/일 · 75세 이상 1,800 mg/일 → 시설 기준은 엄격한 1,800 채택

[양념 감량률]  ← 2026-10-12 도입 (기존 '저염 계수'를 대체)
  메뉴 나트륨 = 식재료 나트륨 + 양념 나트륨 × (1 − 양념 감량률)
  · 후보 메뉴 나트륨의 약 80%가 양념(소금·간장·된장·고추장·젓갈·소스류)에서 나옴
  · 예) 양념 감량 0.4 = 양념을 40% 줄이거나, 저염 장류로 바꿔 같은 효과를 낸 경우
  · 김치는 재료 자체가 짠 음식이므로 감량률 대신 배식 비율(portion_config.py)로 조절
  · 감량률별 결과는 seasoning_sensitivity.py 로 확인

[고염 메뉴 제외]
  레시피 1인분 원본 나트륨이 HIGH_SODIUM_EXCLUDE 이상이면 후보에서 제외 (None이면 제외 안 함)
"""

DAILY_SODIUM_MAX = 1800                         # mg/일
MEAL_SODIUM_MAX  = round(DAILY_SODIUM_MAX / 3)  # 600 mg/끼

# ── 양념 감량률 (0 = 레시피 그대로, 0.4 = 양념 나트륨 40% 감량) ─────────
# [2026-10-12] 선택지 B 적용: 국·주찬·부찬 양념 40% 감량 (저염 장류 대체 등)
SEASONING_REDUCTION = {
    "밥":   0.0,
    "국":   0.4,
    "주찬": 0.4,
    "부찬": 0.4,
    "김치": 0.0,   # 김치는 배식 비율로 조절 권장
}

# Recipe.title에 아래 단어가 들어가면 '양념'으로 분류 (candidate_agent 쿼리에서 사용)
SEASONING_KEYWORDS = ["소금", "간장", "된장", "고추장", "쌈장", "굴소스", "젓",
                      "맛술", "다시다", "스톡", "조미료", "춘장", "소스", "케첩", "미소"]

# ── (구버전) 메뉴 나트륨 전체에 곱하는 계수 ─ 양념 감량률과 중복 적용되므로 1.0 유지 권장
SODIUM_FACTOR = {"밥": 1.0, "국": 1.0, "주찬": 1.0, "부찬": 1.0, "김치": 1.0}

# ── 개인 나트륨 기준 (KDRI 2025 만성질환위험감소섭취량, 성별 공통) ─────────
#   (최소 나이, 최대 나이, 하루 mg)  → 끼니 기준은 1/3
SODIUM_CDRR_BY_AGE = [
    (19, 64, 2300),
    (65, 74, 1900),
    (75, 200, 1800),
]


def daily_sodium_max_for_age(age: int) -> float:
    for lo, hi, mg in SODIUM_CDRR_BY_AGE:
        if lo <= age <= hi:
            return mg
    return DAILY_SODIUM_MAX


def meal_sodium_max_for_age(age: int) -> float:
    return round(daily_sodium_max_for_age(age) / 3)


HIGH_SODIUM_EXCLUDE = 800              # mg/접시 (레시피 1인분 원본 기준)
EXCLUDE_CATS        = ("국", "주찬", "부찬")   # 밥·김치(화이트리스트)는 제외 대상 아님

SEASONING_SHARE_FALLBACK = 0.8   # 양념 나트륨 정보가 없는 구버전 pool_dump용 추정 비율

_DEFAULT = object()


def apply_sodium_adjustment(pool: dict, factor: dict = None,
                            exclude=_DEFAULT, verbose: bool = True,
                            portion: dict = None, reduction: dict = None) -> dict:
    """
    나트륨 보정(양념 감량) + 표준 배식 비율(portion_config.py)을 함께 적용합니다.

    각 메뉴에 대해
      - _raw       : Neo4j에서 가져온 원본 수치 (최초 1회 보존 → 반복 적용해도 중복되지 않음)
      - sodium_raw : 레시피 1인분 원본 나트륨
      - portion    : 적용된 배식 비율
      - 수치 항목  : 원본 × 배식 비율
      - sodium     : (식재료 + 양념 × (1 − 감량률)) × 구버전 계수 × 배식 비율
    고염 메뉴 제외는 '레시피 1인분 원본 나트륨' 기준입니다.
    """
    from .portion_config import PORTION, SCALED_KEYS

    factor    = factor    or SODIUM_FACTOR
    portion   = portion   or PORTION
    reduction = reduction or SEASONING_REDUCTION
    exclude   = HIGH_SODIUM_EXCLUDE if exclude is _DEFAULT else exclude

    out, removed, fallback = {}, [], 0
    for cat, menus in pool.items():
        kept = []
        f = factor.get(cat, 1.0)
        p = portion.get(cat, 1.0)
        r = reduction.get(cat, 0.0)
        for m in menus:
            raw = m.get("_raw")
            if raw is None:   # 최초 적용: 현재 값을 원본으로 보존
                raw = {k: (m.get(k, 0) or 0) for k in SCALED_KEYS}
                raw["sodium"] = m.get("sodium_raw", raw["sodium"])
            if "sodium_seasoning" not in raw:
                if m.get("sodium_seasoning") is not None:
                    raw["sodium_seasoning"] = m["sodium_seasoning"]
                else:
                    raw["sodium_seasoning"] = raw["sodium"] * SEASONING_SHARE_FALLBACK
                    fallback += 1
            if exclude and cat in EXCLUDE_CATS and raw["sodium"] >= exclude:
                removed.append((cat, m["menu_name"], raw["sodium"]))
                continue

            seas = min(raw["sodium_seasoning"], raw["sodium"])
            na   = (raw["sodium"] - seas) + seas * (1 - r)
            adj  = {k: round(raw[k] * p, 2) for k in SCALED_KEYS}
            adj["sodium"]           = round(na * f * p, 2)
            adj["sodium_seasoning"] = round(seas * (1 - r) * f * p, 2)
            kept.append({**m, **adj, "_raw": raw, "sodium_raw": raw["sodium"], "portion": p})
        out[cat] = kept

    if verbose:
        print(f"  [나트륨 보정] 양념 감량률 {reduction} | 고염 제외 기준 {exclude}")
        if any(v != 1.0 for v in factor.values()):
            print(f"  [나트륨 보정] (구버전) 전체 계수 {factor}  ※ 양념 감량과 중복 적용 중")
        print(f"  [배식 비율]   {portion}")
        if removed:
            print(f"  [나트륨 보정] 고염 메뉴 {len(removed)}개 제외: "
                  + ", ".join(f"{n}({r:.0f})" for _, n, r in removed))
        if fallback:
            print(f"  [나트륨 보정] ⚠ 양념 나트륨 정보 없는 메뉴 {fallback}개 → "
                  f"{SEASONING_SHARE_FALLBACK:.0%}로 추정 (diagnose_f1.py로 pool_dump 재생성 권장)")
    return out
