# 영양 분석 (5일치 식단 → 섭취 영양소)

CAN Pro 산출 결과와 조사 앱의 식단표·배식량·목측법 잔반을 결합해
어르신별 실제 섭취 영양소를 계산합니다.

```
섭취 영양소 = 메뉴 1인분 영양소 × 배식계수 × 섭취율
배식계수    = 실제 배식량(g) ÷ 1인 제공량(g)
섭취율      = 1 − 잔반등급/4      (0 다먹음 · 1 25% · 2 50% · 3 75% · 4 모두 남김)
```

## 파일

| 파일 | 역할 |
|---|---|
| `nutrition_core.py` | 계산 코어 — 메뉴 영양성분 합산, 식단표 매핑, 배식계수, 섭취율 |
| `menu_plan.json` | 5일 식단표와 식사형태 9종별 기본 배식량 (`NutritionSurveyPage.jsx`에서 추출) |
| `juk_override.json` | 1·2일차 점심·저녁 '영양죽'의 실제 메뉴명 |
| `build_serving_nutrition.py` | 식사형태별 제공 영양량(잔반 반영 전) 엑셀 생성 — DB 불필요 |
| `build_intake_nutrition.py` | 어르신별 섭취 영양소 엑셀 생성 — Supabase 조사 데이터 사용 |
| `build_compare_AC.py` | 배식계수 A·C 두 방식을 한 파일에 나란히 산출 (비교용) |

## 실행

```bash
cd analysis
# 1) 식사형태별 제공 영양량
python build_serving_nutrition.py data/MemoryResultAll_5일치.csv ../식사형태별_제공영양량.xlsx

# 2) 어르신별 섭취 영양소 (backend/.env 의 SUPABASE_URL·KEY 자동 사용)
python build_intake_nutrition.py data/MemoryResultAll_5일치.csv ../어르신별_섭취영양소.xlsx NH001
#   요양원ID를 빼면 전체 시설. 뒤에 A 또는 C를 붙이면 배식계수 방식을 바꿉니다 (생략 시 A).
python build_intake_nutrition.py data/MemoryResultAll_5일치.csv ../어르신별_섭취영양소_C.xlsx NH001 C

# 3) A·C 비교표
python build_compare_AC.py data/MemoryResultAll_5일치.csv ../식사형태별_제공영양량_A대C.xlsx
```

필요 패키지: `pandas`, `openpyxl` (backend 가상환경에 이미 있음)

## 배식계수 산정 방식

`nutrition_core.METHOD` 로 바꿉니다.

- **A (기본값)** — 각 식사형태의 기본 배식량을 그 메뉴 1인분으로 본다.
  조사 기본값대로 배식했으면 계수 1, 조사원이 실제 무게를 고쳐 입력했으면 그 비율만 반영.
- **C** — 밥/죽·국/탕은 A와 같고, 주찬·부찬·김치는 **레시피 총량**을 1인 제공량으로 본다.
  찬류는 조리 수율이 1에 가까워 `배식량 ÷ 레시피 총량`이 실제 제공 비율에 가깝다.
  밥/죽(생쌀 기준)과 국(물 미포함)은 레시피 총량을 분모로 쓸 수 없어 A를 유지한다.

## 자료 주의점

- CAN Pro 의 `재료량(g)` 합계는 **조리 전 재료 중량**입니다. 조사에서 입력하는 배식량(조리 후 실측)과 단위가 다릅니다.
- 같은 음식이 여러 끼니에 중복 입력된 행 28개는 1회만 반영합니다.
- 4·5일차 밥/죽은 HS09·HS29 어르신만 흰죽으로 대체됩니다 (식단표 표기 반영).
- 간식은 CAN Pro 자료가 없어 계산에서 제외했습니다 (아침·점심·저녁만).
