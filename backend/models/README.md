# 유형 모델 폴더

`models/<버전>/` 마다 아래 파일이 있어야 합니다. `python -m care.train` 이 자동으로 만듭니다.

| 파일 | 내용 |
|---|---|
| `model.joblib` | 표준화 기준·결측 대치기·유형 중심점 |
| `type_meta.json` | 유형 코드별 이름 · 보호자용 표현 · 위험가중(risk_weight) · 설명 — **직접 검토·수정** |
| `report/` | (재학습 시) k 선택 지표·프로파일·민감도 결과 |

활성 모델은 Supabase `type_models.is_active` 로 정하며, 환경변수 `CARE_ACTIVE_MODEL` 로 강제 지정할 수 있습니다.
