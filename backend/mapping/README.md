# 공급사 식자재 가격 매핑 (`backend/mapping/`)

> **핵심 산출물:** 매일 Neo4j Aura 의 `(:Recipe)` 노드(식재료 1,622개, id·title 은 `scripts/load_graph.py` 와 같음)에
> 현대그린푸드·사조푸디스트 **공급사별 kg당 가격**(`price_per_kg_hgreenfood`, `price_per_kg_sajo`)과 그 상품명,
> 두 공급사 최저가(`price_per_kg`)와 참고용 28일 중앙값(`price_per_kg_28d`)이 갱신된다. 아래 3-⑦ 참고.
> **식단 최적화는 오늘 최저가(`price_per_g`)를 쓴다** (`config.OPTIMIZE_PRICE = "today"`, `"median28"`로 바꾸면 28일 중앙값).

레시피 DB의 식재료 1,622개(식품코드 단위)에 현대그린푸드·사조푸디스트의 **매일 바뀌는 크롤링 가격**을 연결한다.
매일 크롤러 직후 **새로 생긴 상품만** 판정하고, 승인된 상품 중 **오늘 g당 가장 싼 것**을 식재료 가격으로 정한다.
식단 최적화(f2)는 그 가격의 **28일 중앙값**을 쓴다. 가격을 못 찾으면 비워 둔다 (중앙값 대체 없음).

```
① 새 상품 감지 → ② 상품명 정리 → ③ 후보 찾기 → ④ 판정 → ⑤ 자동 승인 / 검수 대기열 → ⑥ 오늘 가격 → ⑦ 앱·그래프
```

## 1. 처음 설정

1. Supabase SQL Editor에서 `backend/sql/ingredient_mapping.sql`을 실행한다. 테이블 6개와 뷰 4개가 생긴다.
2. `backend/main.py`에 검수 API가 등록돼 있는지 확인한다 (이미 추가함).
   ```python
   from routers import mapping_review
   app.include_router(mapping_review.router, prefix="/api/prices/mapping", tags=["가격 매핑 검수"])
   ```
3. 첫 실행: 전체 상품(약 2만 개)을 판정하고 그래프까지 반영한다. **반드시 `backend` 폴더에서** 실행한다.
   판정은 약 20초, Supabase 업로드 몇 분, LLM 을 켜면 약 260회 호출(10쌍씩 묶음)이 더 걸린다.
   ```bat
   cd C:\dev\survey-app\backend
   venv-win\Scripts\python -m mapping.run --full --graph
   ```
4. 매일 실행을 등록한다: `mapping\register_mapping_task.bat`을 더블클릭한다.
   - 매일 08:15에 실행된다. 크롤러 `CareEatPriceCrawler`는 07:30~07:55 사이에 시작한다.
   - 오늘 단가표가 아직 없으면(종료 코드 3) 15분 간격으로 최대 4번 다시 시도하고, 그래도 실패하면 알림을 띄운다.
   - 로그는 `mapping\_logs\YYYYMMDD.log`, 실행 요약은 `mapping\_reports\YYYY-MM-DD.json`에 남는다.

## 2. 자주 쓰는 명령

| 명령 | 하는 일 |
|---|---|
| `python -m mapping.run` | 오늘(KST) 하루치. 새 상품만 판정하고 오늘 가격을 계산 |
| `python -m mapping.run --date 2026-11-27` | 특정 날짜 |
| `python -m mapping.run --full` | 본 상품도 다시 판정. 사람이 내린 판정(approved/rejected)은 그대로 둔다 |
| `python -m mapping.run --price-only` | 검수 직후 판정은 건너뛰고 오늘 가격만 다시 계산 |
| `python -m mapping.run --graph` | 위 작업에 더해 Neo4j `Recipe` 노드에 공급사별 kg당 가격, `Product`·`MAPPED_TO` 반영 (매일 실행은 이 옵션 포함) |
| `python -m mapping.run --graph-dry-run` | 그래프에 쓸 내용 개수만 확인 |
| `python -m mapping.vocab` | 1월~오늘 월별 단가표로 브랜드·제조사 어휘 다시 배우기 (`data/learned_vocab.json`, 한 달에 한 번 권장) |
| `python -m mapping.run --no-llm` | LLM 끄기 |
| `python -m mapping.run --source csv --store local --date 2026-11-26` | 오프라인 시험. 크롤러 CSV를 읽고 `mapping/_local/*.csv`에 저장 |
| `python -m mapping.run --source csv --backfill` | 크롤러 CSV 스냅샷 날짜마다 실행해서 가격 이력(28일 중앙값)을 채움 |
| `python -m mapping.eval.build_eval_set` | 평가 세트 라벨링 엑셀 만들기 |
| `python -m mapping.evaluate --tune` | 평가 지표 계산, 자동 승인 기준 추천 |
| `python -m pytest tests/test_mapping_traps.py -q` | 함정 사례 시험 (38개) |

## 3. 판정 방법

**② 이름 정리** (`normalize.py`)
- 상품명은 첫 괄호 앞을 핵심 이름으로 쓴다. 브랜드·인증·등급 접두어, `(C)`·`[하림]` 같은 표기, 끝의 숫자·영문은 지운다.
  - 예: `전처리청양고추(국내산)어슷/A타입` → `청양고추`
  - 예: `2배사과식초` → `사과식초`
- 상태(생·손질 / 썰기 / 냉동 / 말린 / 조리 / 통조림 / 가루 / 절임), 육류 동물·부위, 고령친화 태그를 따로 뽑는다.
- 식재료 쪽은 대표 원재료명, 같은 코드의 레시피 이름, 식약처 식품명으로 이름 형태 사전을 만든다.
  - 예: `마늘(다진것)` → 마늘, 다진마늘, 마늘다진것 …

**③ 후보 찾기** (`candidates.py`): 아래 셋을 합친다.
- 이름 관계: 상품 이름이 식재료 이름과 같은지, 그 이름으로 끝나는지, 그 이름으로 시작하는지
- 글자 1–3gram TF-IDF 상위 후보 (식재료별·공급사별 10개, 상품별 3개)
- 육류는 같은 동물이면 모두 후보로 두고, 부위로 판정한다.
- 선택 기능: `MAPPING_EMBED_MODEL=intfloat/multilingual-e5-small`과 sentence-transformers가 있으면 임베딩 유사도를 더한다.

**④ 판정** (`features.py`, `judge.py`): 한국어 복합명사는 **뒤가 중심**이라는 점을 쓴다.
- 상품 이름이 식재료 이름으로 끝나면 같은 재료일 가능성이 높다 (앞부분은 품종·상태·브랜드). 예: 대추방울토마토 = 방울토마토
- 식재료 이름 뒤에 다른 말이 붙으면 가공품이다. 예: 고추장진미채무침, 배추김치, 새우젓
- 더 길게 일치하는 다른 식재료가 있으면 그쪽이 주인이다. 예: 청양고추 상품은 홍고추 후보에서 빠진다.
- 같은 이름을 대표 이름으로 가진 식재료가 여럿이면 대표 원재료명이 그 이름인 쪽이 주인이다. 예: `달걀` → 달걀 (달걀(난황) 아님). 주인이 없으면 자동 승인하지 않는다. 예: `고추` ⊂ 홍고추·풋고추
- 상태: 썰기·냉동 차이는 같은 재료로 본다. 말린 것 / 조리 / 통조림 / 절임 / 가루는 달라야 다른 재료다.
  - 식약처 식품명이 `생것`이면 그 코드는 생것만 인정한다 (건미역 ≠ 생미역).
  - 대표 이름 괄호에 상태가 있으면 그 상태가 필요하다 (꽁치(통조림) ≠ 냉동 꽁치).
- 육류: 부위가 같아야 한다 (목살 ≠ 삼겹살, 채끝 ≠ 등심). 대표 이름이 '다진것'이면 분쇄·다짐육 상품을 부위와 상관없이 인정하고, 지방·뼈는 뺀다.
- 분류 대응표(`lexicon.CATEGORY_SEED` + `category_map` 테이블), 공급사 세분류 일치, g당 가격 범위도 판정에 쓴다.
- 처음에는 규칙 점수로 판정한다. 사람 검수가 200건 이상 쌓이면 `judge.train()`이 로지스틱 회귀로 바꾸고, 정밀도 98% 기준을 함께 저장한다(`models/judge_latest.json`).

**⑤ 승인 정책**
- 자동 승인: 점수 0.90 이상이고, 분류·상태·가공·가격이 모두 맞고, 대표 이름으로 일치하고, 품종 표시와 간편식 표시가 없을 때
- 자동 거절: 확정 불일치(가공품·더 긴 이름의 다른 주인·부위·동물·분류)이거나 점수 0.25 미만일 때
- 나머지는 검수로 간다. 대기열은 식재료 사용 중량 순이다.
- LLM은 0.45–0.90 구간의 검수 건 중 이름 관련 사유로 막힌 것에만 묻는다. 기존 `diet/llm_select.call_llm`과 `.env`의 `LLM_PROVIDER`를 쓰고, 하루 300회가 상한이다.
- 사람이 내린 판정은 `--full`로 다시 돌려도 덮어쓰지 않는다.

**⑥ 오늘 가격** (`pricing.py`, `units.py`)
- 대상: 승인된 상품 중 오늘 판매 중(`last_seen` = 기준일)인 것
- g당 가격 = 세금 포함 단가 ÷ 포장 g
  - 부피 단위는 밀도로, 개수 단위는 개당 중량으로 환산한다 (`units.py` 기본표 + `unit_conversions` 테이블).
  - 사조는 세금 포함가가 없어서 과세 상품이면 ×1.1을 한다.
- 이상값: 그 식재료 중앙값과 식품대분류 중앙값 **둘 다**에서 1/3–5배를 벗어나면 빼고, 자동 승인이었던 쌍은 검수로 돌린다.
- 두 공급사를 통틀어 g당 가장 싼 상품을 그날 가격으로 정하고, 28일 중앙값을 최적화용으로 쓴다.

**⑦ 지식그래프** (`graph_export.py`): 기존 `(:Recipe {id})`는 MATCH만 한다 (노드를 새로 만들지 않음).

| 위치 | 속성 |
|---|---|
| `(:Recipe)` | `price_per_kg` (오늘 두 공급사 최저, 원/kg, 세금 포함), `price_per_kg_28d` (최적화용), `price_per_kg_hgreenfood` · `price_item_hgreenfood` · `price_n_hgreenfood`, `price_per_kg_sajo` · `price_item_sajo` · `price_n_sajo`, `price_supplier`, `price_date`, `price_status` (ok / missing / not_product) |
| `(:Product {supplier, item_cd})` | `supplier_label`, `item_nm`, `spec`, `unit`, `pack_g`, `unit_price_tax`, `price_per_kg`, `price_date`, `on_sale` |
| `(:Recipe)-[:MAPPED_TO]->(:Product)` | `score`, `status`, `method`, `selected` (그날 식재료 가격으로 뽑힌 상품), `selected_in_supplier` (공급사 안 최저가) |

- 승인이 취소된 관계와 어디에도 이어지지 않은 Product는 지운다.
- `scripts/load_graph.py --wipe`로 그래프를 다시 적재했다면 `python -m mapping.run --price-only --graph`를 한 번 실행한다.

Cypher 예시:
```cypher
MATCH (r:Recipe {title:'양파'}) RETURN r.price_per_kg_hgreenfood, r.price_item_hgreenfood, r.price_per_kg_sajo, r.price_item_sajo
MATCH (r:Recipe)-[m:MAPPED_TO {selected_in_supplier:true}]->(p:Product) WHERE r.title='두부' RETURN p.supplier_label, p.item_nm, p.price_per_kg
```

**월별 이력으로 배운 어휘** (`vocab.py`): 1월~11월 단가표 상품명 약 2만 개에서 배운다.
- 여러 식재료 앞에 두루 붙는 말은 브랜드·제품군으로 본다 (크레잇·애니쿡·굿프랜즈·신송·코다노 …).
- 사조 상품명 끝의 제조사명도 배운다 (씨제이·오뚜기·풀잎새 …).
- 브랜드로 배운 말 앞에 붙은 상품은 품종 차이가 아니라고 보고 자동 승인 후보가 된다.
- 품종·맛 표시(미니·홍·매콤·불고기 …)는 배우지 않고, 앞에 있으면 검수로 보낸다.
- 원물 식재료가 음료·유제품·제과 상품 이름 끝에 오면 맛 상품으로 보고 거절한다 (환타오렌지 ≠ 오렌지).

## 4. 식단 시스템 연결 (이쪽에서 할 일)

`backend/diet/build_pool.py`의 `load_prices()`·`price_per_g()`를 아래로 바꾸면 된다.

```python
from mapping.client import load_price_table, purchase_cost
prices = load_price_table()                      # {식재료ID: 오늘 최저 g당 가격}  (config.OPTIMIZE_PRICE)
cost = purchase_cost(prices, ingredient_id, use_g, discard_pct)   # 실사용량 ÷ (1 − 폐기율) × g당 가격, 없으면 None
```

`None`이면 `cost_coverage()`가 '가격 없는 식재료'로 표시하고 0원으로 둔다. 식재료 키는 `scripts/load_graph.py`와 같은 식재료ID다.

## 5. 검수 API (`routers/mapping_review.py`, 접두어 `/api/prices/mapping`)

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/queue?limit=&offset=&q=` | 검수 대기 식재료 (사용 중량 순): 대기 수·승인 수·최고 점수·현재 가격 |
| GET | `/ingredient/{id}?include_rejected=` | 후보 상품 목록 + 근거(이름 관계·상태·가공·분류·가격) + 현재 단가 + 최근 28일 가격 |
| POST | `/review` | `{ingredient_id, supplier, item_cd, decision: approve\|reject, reason}` (관리자) |
| POST | `/review/bulk` | `{items: [...]}` 최대 200건 (관리자) |
| POST | `/ingredient/{id}/status` | `{product_status: product\|not_product}` 육수처럼 상품이 아닌 재료 표시 (관리자) |
| GET | `/stats` | 상태별 건수, 대기 식재료 수, 최근 가격 연결률 |
| GET | `/missing?limit=` | 가격 없는 식재료 (사용 중량 순) |

화면 제안: 왼쪽에 대기열(식재료명, 사용 중량, 대기 수), 오른쪽에 후보 카드를 둔다. 카드에는 상품명·규격·원/kg·공급사·근거 칩·승인/거절 버튼을 넣고, 키보드 A/R로 승인·거절할 수 있게 한다. 승인·거절은 `category_map` 통계에도 반영된다.

## 6. 평가

1. `python -m mapping.eval.build_eval_set`을 실행하면 `eval/평가세트_라벨링.xlsx`가 만들어진다. 상위 300개와 무작위 100개, 함정 사례가 표시된다.
2. '라벨' 시트의 `정답(O/X)` 열을 채운다. 목록에 없는 정답 상품은 '누락' 시트에 적는다.
3. `python -m mapping.evaluate --tune`을 실행하면 `eval/평가결과_<날짜>.md`가 나온다.
   - 지표: 후보 재현율, 자동 승인 정밀도·비율, 가격 연결률, 선택 정확도, 함정 오승인, 추천 기준
4. 검수가 쌓이면 `python -m mapping.evaluate --reviews --tune`으로 사람 판정을 기준으로 다시 맞춘다.

## 6-0. 가격 상품 확인 (정확도에 가장 효과가 큼)

식재료 가격은 승인 상품 중 가장 싼 것이다. 틀린 매핑은 싸게 보여 뽑히기 쉬우므로, 실제로 뽑힌 상품부터 사람이 확인한다.

```bat
venv-win\Scripts\python -m mapping.eval.build_price_check     :: eval\가격상품확인_<날짜>.xlsx (식재료×공급사: 오늘 가격 상품 + 다음 후보 2개)
:: '정답(O/X)' 채우기 — 사용 중량 순이라 위에서부터
venv-win\Scripts\python -m mapping.eval.apply_labels          :: O=사람 승인, X=사람 거절 저장 → 가격·그래프 다시 계산
```

- X로 거절한 자리에는 다음 상품이 올라온다. 확인표를 다시 만들어 새로 '오늘 가격'이 된 행만 보면 된다.
- `미승인(더 쌈)`: 검수 대기 상품 중 오늘 가격보다 싼 것. 같은 재료면 O → 새 최저가. **틀린 상품일수록 싸게 보이니 꼭 확인.**
- `미승인(가격 없음)`: 가격이 없는 식재료(사용량 500위 이내)의 검수 대기 후보. 맞는 것에 O → 가격이 생긴다.
- 같은 날짜 파일이 있으면 `_2`, `_3`을 붙여 새로 만든다 (엑셀에서 열어 둔 파일을 덮어쓰지 않음).
- 여기서 채운 O/X는 `mapping.train`의 학습 데이터로도 쓰인다.

## 6-1. 판정 모델 학습 (사람이 O/X 확인 → 로지스틱 회귀)

1. 전체 실행(`run --full --graph`)이 끝난 뒤 학습용 라벨링 파일을 만든다.
   ```bat
   venv-win\Scripts\python -m mapping.eval.build_label_set
   ```
   - `eval/학습세트_라벨링.xlsx`가 생긴다. 약 1,300쌍이고 식재료 335개를 담는다 (상위 100개는 더 많이, 사조 상품 섞음).
   - 모델이 배우기 좋은 쌍 위주로 뽑는다: 자동 승인 일부, 검수 대기(애매한 쌍), 아깝게 거절된 쌍
   - **이 파일을 다시 만들면 적어 둔 O/X가 사라진다.** 라벨링을 시작한 뒤에는 다시 만들지 않는다.
2. '라벨' 시트의 `정답(O/X)` 열을 채운다 (노란 칸, O/X 드롭다운).
   - 옆에 '판정 근거'와 '시스템 제안'이 있다. 동의하는 구간은 제안을 복사해 붙이고 한 번 훑어보면 된다.
   - 애매하면 비워 둔다. 빈칸은 학습에서 빠진다.
3. 학습한다. 200쌍 이상이면 돌아가고, 일부만 채워도 된다.
   ```bat
   venv-win\Scripts\python -m mapping.train            :: 성능 비교 후 규칙보다 나으면 저장
   venv-win\Scripts\python -m mapping.train --dry-run  :: 저장하지 않고 성능만
   ```
   - 식재료 단위로 나눈 5겹 교차검증으로 '지금 규칙'과 '학습 모델'의 자동 승인 정밀도·비율을 비교한다.
   - 모델이 정밀도 98%를 지키면서 자동 승인을 더 많이 할 때만 `models/judge_latest.json`을 저장한다. 다음 실행부터 자동으로 쓰인다.
   - 이미 판정한 상품에도 적용하려면 `python -m mapping.run --full --graph`를 실행한다 (사람 판정은 유지).
   - 학습에 쓰는 라벨: 학습세트·평가세트 엑셀의 O/X, 검수 화면에서 승인·거절한 쌍. `--with-llm 0.3`을 주면 LLM 판정도 낮은 가중치로 섞는다.
   - 결과는 `eval/학습결과_<날짜>.json`에 남는다.

## 7. 파일

| 파일 | 내용 |
|---|---|
| `config.py` | 기준값 (자동 승인 0.90, LLM 구간, 이상값 1/3–5배, 28일) |
| `lexicon.py` | 단어 사전: 상태·가공 표지·같은 말·육류 부위·품종 표시·분류 대응. **규칙을 고칠 때는 여기만** 고치면 된다 |
| `normalize.py` | 상품명 정리, 식재료 이름 사전 |
| `candidates.py` | 후보 찾기 |
| `features.py` · `judge.py` | 특징 계산, 판정, 학습 모델 |
| `matching.py` | ②~⑤ 묶음 |
| `units.py` · `pricing.py` | g 환산, 오늘 가격 |
| `llm.py` | 애매한 구간 LLM 판정 |
| `store.py` | Supabase / 로컬 CSV 저장소 |
| `run.py` | CLI |
| `graph_export.py` | Neo4j 반영 |
| `client.py` | 식단 시스템용 가격 읽기 |
| `evaluate.py` · `eval/build_eval_set.py` | 평가 (전체 후보 O/X → 시스템 지표) |
| `train.py` · `eval/build_label_set.py` | 판정 모델 학습 (표본 O/X → 로지스틱 회귀) |
| `eval/build_price_check.py` · `eval/apply_labels.py` | 가격으로 뽑힌 상품 확인표, 엑셀 O/X를 사람 판정으로 저장 |
| `vocab.py` · `data/learned_vocab.json` | 월별 이력으로 배운 브랜드·제조사 어휘 |
| `run_daily.bat` · `register_mapping_task.bat` | 스케줄 |
| `data/공급사매핑_대상_식재료.xlsx` | 매핑 대상. 레시피 DB가 바뀌면 교체한다 |

## 8. 알아 둘 점

- **규격 환산은 한 곳(`mapping/units.py`)에서 관리한다.** 식자재 단가 화면(`routers/prices.py`)도 이 함수를 불러 쓴다 (11/27 통일). 곱셈 표기(`250g*10pk/Box`), 오차 표기(`200±20g`), 박스 중량(`10Kg/Box`), 닭 호수(`16호`), 상품명 속 중량(`_500G`)을 읽는다.
- **식품코드와 대표 이름이 어긋나는 재료:** 쇠고기(다진것)는 코드가 안심이고, 햄(통조림)은 코드가 스모크햄이다. 다진것은 위 규칙으로 처리했다. 햄(통조림)은 대표 이름을 따라 통조림만 자동 승인하므로, 일반 햄은 검수에서 정한다.
- **부피 상품:** 밀도표에 없는 액체(일부 음료·소스)는 가격에서 빠진다. `unit_conversions`에 추가하면 다음 실행부터 반영된다.
- **사조 분류:** 사조 상품은 분류가 품목명으로 추정한 값이라(`자동분류`) 분류가 맞지 않아도 거절하지 않고 중립으로 둔다.
