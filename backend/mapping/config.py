# -*- coding: utf-8 -*-
"""경로·기준값. 숫자는 평가 세트로 다시 맞춘다 (mapping/evaluate.py --tune)."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
REPO = os.path.dirname(BACKEND)

# 입력
TARGETS_XLSX = os.path.join(HERE, "data", "공급사매핑_대상_식재료.xlsx")
CRAWLER_DATA = os.getenv("MAPPING_CRAWLER_DATA") or os.path.join(REPO, "price-crawler", "price-crawler", "data")   # <공급사>/<공급사>_prices_YYYYMMDD.csv
LOCAL_STORE = os.path.join(HERE, "_local")       # --store local 일 때 테이블을 CSV 로 저장
MODEL_DIR = os.path.join(HERE, "models")

SUPPLIERS = ("hgreenfood", "sajo")
NON_FOOD_MCLS = {"생활용품", "세제류", "포장용품"}          # routers/prices.py 와 같음

RULE_VERSION = "rule-2026.11.27"

# ③ 후보 찾기
TOPK_PER_INGREDIENT = 10          # 식재료마다 공급사별 상위 후보 수
TOPK_PER_PRODUCT = 3              # 상품마다 상위 식재료 수 (새 상품이 어느 식재료의 후보인지)
MIN_SIM = 0.20                    # 이보다 낮은 글자 유사도는 후보로 두지 않음 (이름 관계가 있으면 예외)

# ⑤ 승인 정책 (확률 0–1)
AUTO_APPROVE = 0.90               # 이상 + 분류·상태·가공·가격 모두 맞음 → auto_approved
AUTO_REJECT = 0.25                # 미만, 또는 확정 불일치(가공품·부위·다른 식재료 소유) → auto_rejected
LLM_BAND = (0.45, 0.90)           # 이 구간의 pending 만 LLM 에 묻는다
LLM_APPROVE_MIN = 0.55            # LLM 이 같다고 해도 규칙 점수가 이 이상일 때만 자동 승인
                                  # (0.60 = 대표 이름 앞에 모르는 말이 붙은 경우: '옛날국수소면' — 브랜드인지 LLM 이 판단)
LLM_MAX_CALLS = 300               # 하루 상한 (비용 보호)

# 학습 모델로 바꾸는 시점
MIN_LABELS_FOR_MODEL = 200
TARGET_PRECISION = 0.99          # 정확도 우선 (11/27 사용자 결정): 학습 모델은 교차검증 정밀도 99% 이상일 때만 자동 승인

# ⑥ 가격
OUTLIER_LOW = 1 / 3               # 기준 중앙값의 1/3 보다 싸면 규격 해석 오류 의심
OUTLIER_HIGH = 5.0                # 5배보다 비싸면 의심
MEDIAN_WINDOW_DAYS = 28
# 식단 최적화에 쓰는 가격: "today" = 오늘 최저가(price_per_g), "median28" = 최근 28일 최저가 중앙값(price_per_g_28d)
OPTIMIZE_PRICE = "today"
OPTIMIZE_COL = "price_per_g" if OPTIMIZE_PRICE == "today" else "price_per_g_28d"
STALE_DAYS = 3                    # last_seen 이 기준일보다 이만큼 이상 오래되면 '판매 중 아님'
