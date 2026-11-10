# -*- coding: utf-8 -*-
"""약물-식품 규칙(diet/data/drug_food_rules.json) → 근거 문서 care/knowledge/docs/DRUG_FOOD.md

    python -m scripts.build_drug_food_doc
    python scripts/ingest_guidelines.py --only DRUG_FOOD --replace     # 다시 적재 (기존 문단 교체)
규칙을 고치면 이 스크립트로 문서를 다시 만들어 근거 검색 내용과 규칙이 어긋나지 않게 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
ACT = {"avoid": "해당 식재료가 든 반찬은 대체찬·제품에서 제외한다",
       "limit": "해당 식재료가 한 반찬에 기준량 이상 들어간 경우만 제외한다(조금 들어간 반찬은 허용)",
       "timing": "식재료를 빼지 않고 복약 시간·식사 방법을 안내한다",
       "check": "약 종류만 알고 이름을 모르면 식재료를 빼지 않고 '약 이름 확인 필요'로 표시한다"}


def main():
    d = json.load(open(BACKEND / "diet/data/drug_food_rules.json", encoding="utf-8"))
    L = ["<!-- 출처: 공개 의약품 허가사항(약품설명서)·식품의약품안전처 의약품안전나라 복약정보 수준의 일반 지식을",
         "     식단 설계용 규칙(diet/data/drug_food_rules.json)으로 정리한 내부 문서다. 규칙 파일과 같은 내용이며",
         "     scripts/build_drug_food_doc.py 로 만든다. 문단마다 해당 약의 허가사항 원문(사용상 주의사항)과 대조해",
         "     쪽번호를 붙이는 작업이 남아 있다. 현장 적용 전 약사·의사 확인을 전제로 한다. 약 용량·처방은 다루지 않는다. -->", "",
         "## 약물-식품 상호작용 규칙의 원칙", "",
         "약물과 식품의 상호작용은 **약 이름(성분명·상품명)이 확인된 경우에만** 식재료 제외 같은 강한 조치를 한다. 기초조사의 '복용 약물 종류'만 알 때는 같은 종류 안에서도 해당하지 않는 약이 많으므로 식재료를 빼지 않고 약 이름 확인을 요청한다. 예외로 자몽처럼 피하기 쉬운 식품은 종류만 알아도 제외한다.", "",
         "조치는 네 가지다: **제외(avoid)** — 해당 식재료가 든 반찬을 뺀다, **제한(limit)** — 한 반찬에 기준량 이상 들어간 경우만 뺀다, **복약 안내(timing)** — 복약 시간과 식사 방법을 안내한다, **확인(check)** — 약 이름 확인을 요청한다. 약물 관련 제한은 안전성 문제로 분류해 다른 영양 판단보다 먼저 적용하며 다른 판단이 덮어쓸 수 없다.", ""]
    for r in d["rules"]:
        L += [f"## 약물-식품 {r['title']}", ""]
        names = ", ".join(r["match_names"][:8]) or "(약 이름 없음 — 종류로만 확인)"
        cats = ", ".join(r["match_categories"])
        L += [f"해당 약: {names}" + (f" (기초조사 약 종류: {cats})" if cats else "") + f". 상호작용: **{r['effect']}**.", ""]
        s2 = f"조치: {ACT[r['action']]}."
        if r.get("ingredients"):
            s2 += f" 대상 식재료: {', '.join(r['ingredients'])}" + (f" (한 반찬에 {r['min_g']:g} g 이상)" if r.get("min_g") else "") + "."
        L += [s2 + f" 근거: {r['source']}.", ""]
    L += ["## 알레르기 식재료 제외 원칙", "",
          "어르신 기록에 알레르기가 등록되면 알레르기 그룹(예: 갑각류, 대두, 밀)에 속한 식재료를 모두 찾아 **해당 식재료가 든 반찬을 대체찬·제품 후보에서 제외**한다. 반응 정도(가벼움·중간·심함)에 따라 심각도를 정하지만, 제외 조치 자체는 정도와 관계없이 적용한다. 알레르기는 안전성 문제로 분류해 다른 영양 판단보다 항상 먼저 확인한다.", ""]
    groups = "; ".join(f"{g['group']}({', '.join(g['ingredients'][:6])}{' 등' if len(g['ingredients']) > 6 else ''})" for g in d["allergens"])
    L += [f"그룹별 대표 식재료: {groups}.", ""]
    (BACKEND / "care/knowledge/docs/DRUG_FOOD.md").write_text("\n".join(L), encoding="utf-8")
    print("DRUG_FOOD.md 생성:", len(d["rules"]), "개 규칙")


if __name__ == "__main__":
    main()
