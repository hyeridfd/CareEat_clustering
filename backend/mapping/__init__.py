# -*- coding: utf-8 -*-
"""공급사 식자재 가격 매핑 파이프라인.

매일 크롤러 직후:
  ① 새 상품 감지 → ② 상품명 정리 → ③ 후보 찾기 → ④ 판정 → ⑤ 자동 승인/검수 대기열
  → ⑥ 오늘 가격 결정 → ⑦ 앱·그래프 반영

    python -m mapping.run --date 2026-11-27          # 하루치 (Supabase)
    python -m mapping.run --source csv --date 2026-11-26 --store local   # 크롤러 CSV + 로컬 저장 (오프라인 시험)
    python -m mapping.evaluate --labels mapping/eval/평가세트_라벨링.xlsx

자세한 내용은 mapping/README.md.
"""
__version__ = "0.1.0"
