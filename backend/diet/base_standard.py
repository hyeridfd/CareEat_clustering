"""
base_standard.py  ─  기본 일반식 영양 기준 (일반 노인, KDRI)
=============================================================
[구조]  ① 기본 일반식: 시설 전체가 같은 식단 → '일반 노인' 기준으로 최적화 (이 파일)
        ② 질환·식사형태: 입소자별 개인 기준(patient_profile_final.py)으로 점검 후
           고령친화우수식품 대체찬으로 교체 (substitute_agent.py)

[근거]  한국인 영양소 섭취기준(KDRI) 75세 이상
  · 에너지: 끼니 500~800kcal / 하루 1,500~2,400kcal (기존 고령자 범위 유지)
  · 비율 기준 산정용 기준 열량 ENERGY_REF = 2,000kcal/일
      (기존 2,400kcal 기준은 실제 식단 열량보다 높아 지방 하한 등이 과하게 잡혔음)
  · 단백질: 권장섭취량 75세↑ 남 60g · 여 50g → 하루 50g 이상 (끼니 1/3)
  · 지방: 에너지의 15~30%     · 포화지방: 7% 미만     · 총당류: 20% 이하
  · 나트륨: 만성질환위험감소섭취량 1,800mg/일 (sodium_config.py, 모든 고령자 공통)
  · 식이섬유: 충분섭취량 75세↑ 여 20g · 남 25g → 하루 20g 이상
  · 칼륨: 기본 일반식에서는 제약하지 않음 (신장질환자는 오히려 제한 대상)
          → 하루 합계는 보고서에서 모니터링만
※ 모든 값은 아래 상수만 바꾸면 반영됩니다.
"""
from .sodium_config import DAILY_SODIUM_MAX, MEAL_SODIUM_MAX

BASE_MODE = "일반식"        # "일반식" | "최엄격"(기존: 모든 입소자 중 가장 엄격한 기준)

ENERGY_REF        = 2000   # kcal/일 — 비율 기준(지방·포화지방·당류) 환산용
ENERGY_MEAL       = (500, 800)
ENERGY_DAILY      = (1500, 2400)
PROTEIN_DAILY_MIN = 50     # g/일
FAT_RATIO         = (0.15, 0.30)
SAT_FAT_RATIO_MAX = 0.07
SUGAR_RATIO_MAX   = 0.20
FIBER_DAILY_MIN   = 20     # g/일
CARB_DAILY_MAX    = 390    # g/일 (기존 유지)
POTASSIUM_DAILY_MIN = None # 기본 일반식에서는 제약 안 함 (값을 넣으면 적용)


class BaseStandard:
    """MealPlanProblem에 넣는 제약 객체 (FacilityConstraintAdapter와 같은 속성 이름)"""

    def __init__(self):
        E = ENERGY_REF
        fat_lo = E * FAT_RATIO[0] / 9
        fat_hi = E * FAT_RATIO[1] / 9
        sat_hi = E * SAT_FAT_RATIO_MAX / 9
        sug_hi = E * SUGAR_RATIO_MAX / 4

        # ── 끼니 기준 ─────────────────────────
        self.energy_min, self.energy_max = ENERGY_MEAL
        self.protein_min   = round(PROTEIN_DAILY_MIN / 3, 1)
        self.protein_max   = None
        self.fat_min       = round(fat_lo / 3, 1)
        self.fat_max       = round(fat_hi / 3, 1)
        self.sat_fat_max   = round(sat_hi / 3, 1)
        self.sugar_max     = round(sug_hi / 3, 1)
        self.sodium_max    = MEAL_SODIUM_MAX
        self.potassium_min = round(POTASSIUM_DAILY_MIN / 3) if POTASSIUM_DAILY_MIN else None
        self.fiber_min     = round(FIBER_DAILY_MIN / 3, 1)

        # ── 하루 기준 ─────────────────────────
        self.daily_energy_min, self.daily_energy_max = ENERGY_DAILY
        self.daily_protein_min   = PROTEIN_DAILY_MIN
        self.daily_fat_min       = round(fat_lo, 1)
        self.daily_fat_max       = round(fat_hi, 1)
        self.daily_sat_fat_max   = round(sat_hi, 1)
        self.daily_sugar_max     = round(sug_hi, 1)
        self.daily_sodium_max    = DAILY_SODIUM_MAX
        self.daily_potassium_min = POTASSIUM_DAILY_MIN
        self.daily_fiber_min     = FIBER_DAILY_MIN
        self.daily_carb_max      = CARB_DAILY_MAX

    def summary(self) -> str:
        return (f"[기본 일반식 기준] 끼니 열량 {self.energy_min}~{self.energy_max} | 단백질 ≥{self.protein_min}g | "
                f"지방 {self.fat_min}~{self.fat_max}g | 포화지방 ≤{self.sat_fat_max}g | 당류 ≤{self.sugar_max}g | "
                f"나트륨 ≤{self.sodium_max}mg | 식이섬유 ≥{self.fiber_min}g | 칼륨 "
                + (f"≥{self.potassium_min}mg" if self.potassium_min else "제약 없음(모니터링)"))
