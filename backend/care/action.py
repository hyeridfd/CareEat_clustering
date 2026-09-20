# -*- coding: utf-8 -*-
"""
Care-Eat Action — 관리 우선순위를 '실행 가능한 개선안'으로 바꾼다.

  Scan(facility.py)      시설에서 무엇이 어떤 규모로 일어나고 있는가
  Insight(facility_rules) 무엇부터 손대야 하는가 (점수 = 규모 × 심각도)
  Action(이 파일)         그래서 다음 주 식단을 어떻게 바꾸는가   ← 여기

세 갈래를 한 우선순위에 묶어 준다.
  ① 공식 지침 근거   retrieval.context_for(규칙의 query) → 문헌·쪽수까지
  ② 메뉴 후보       graph.py → 859개 요리 중 목표 영양소를 올릴 수 있는 것
  ③ 교체 대상       시설 잔반 데이터의 최하위 메뉴 → 같은 자리(밥/국/주찬/부찬) 후보

1인분 실측으로 말한다
  HAS_INGREDIENT 관계에 제공 중량(weight)과 가식부 중량(nutri_weight)이 둘 다 있어서
  "이 메뉴 한 그릇에 단백질 20.4 g, 나트륨 482 mg"을 실제로 계산한다.
  영양은 반드시 nutri_weight 기준이다 — 뼈·껍질·육수를 빼야 코다리조림 단백질이
  51 g(잘못)이 아니라 20 g(맞음)으로 나온다.

남아 있는 자료 한계 (화면에도 표기한다)
  · 국 198개 중 125개는 육수가 재료로 등록돼 있지 않다 → 중량이 건더기뿐이다.
  · 멸치액젓·참치액·명란·건새우 등은 나트륨 값이 비어 있다 → 그 요리의 나트륨은
    실제보다 낮게 나온다. 저염 후보에서는 아예 제외한다(틀릴 거면 짜게 틀린다).
  · 레시피 분량이 의심스러운 건은 하루 기준치 초과로 표시만 하고 거르지 않는다.
"""
from __future__ import annotations

import logging

from . import graph
from . import retrieval as rag

log = logging.getLogger("care.action")

# 우선순위 규칙 → 메뉴 후보를 어떤 축으로 찾을지
#   nutrient : graph에서 올릴 목표 영양소, cats : 어느 자리(끼니 구성)를 바꿀지
#   by       : "density"(100 kcal당) / "amount"(100 g당)
#   mode     : "boost"(급원 늘리기) / "lowsalt"(염도 낮추기) / None(지침만)
PLAN = {
    "F_NUT_PROTEIN":  dict(mode="boost", nutrient="protein", cats=["주찬", "부찬"],
                           purpose="단백질 급원 재료로 구성된 주찬·부찬"),
    "F_NUT_CALCIUM":  dict(mode="boost", nutrient="ca", cats=["국", "부찬"],
                           purpose="칼슘 급원 재료가 들어가는 국·부찬"),
    "F_NUT_FIBER":    dict(mode="boost", nutrient="fiber", cats=["부찬"],
                           purpose="식이섬유 급원 재료가 많은 부찬"),
    "F_NUT_VITD":     dict(mode="boost", nutrient="vitd", cats=["주찬"],
                           purpose="비타민 D 급원(등푸른생선·버섯)이 들어가는 주찬"),
    "F_NUT_ENERGY":   dict(mode="boost", nutrient="energy", cats=["간식", "부찬"],
                           purpose="한 그릇 열량이 높은 간식·부찬"),
    "F_NUT_SODIUM":   dict(mode="lowsalt", cats=["국", "부찬"],
                           purpose="염도 부담이 낮은 구성의 국·부찬"),
    "F_MALNUT":       dict(mode="boost", nutrient="protein", cats=["주찬", "간식"],
                           purpose="위험군 강화식·간식에 쓸 단백질 급원 메뉴"),
    "F_UNDERWEIGHT":  dict(mode="boost", nutrient="energy", cats=["간식", "주찬"],
                           purpose="저체중군 추가 간식으로 쓸 고열량 메뉴"),
    "F_MENU_WORST":   dict(mode="replace", purpose="잔반이 많은 메뉴의 같은 자리 대체 후보"),
    "F_COMPONENT_LOW": dict(mode="replace", purpose="반복해서 남기는 음식군의 대체 후보"),
    "F_LOW_INTAKE":   dict(mode="replace", purpose="섭취율이 낮은 메뉴의 대체 후보"),
    # 식형태·돌봄 프로세스·데이터 품질은 메뉴 교체로 풀 문제가 아니다 → 지침 근거만 붙인다.
}

# 시설 질환 prevalence → 그래프 Disease 노드
DISEASE_MAP = {
    "고혈압": "고혈압", "당뇨": "당뇨병", "당뇨병": "당뇨병",
    "신장": "신장질환", "신장질환": "신장질환", "만성신부전": "신장질환",
    "치매": "치매", "근감소증": "근감소증", "연하장애": "연하장애",
}
DISEASE_MIN_PCT = 20      # 이 비율 이상인 질환만 금기 검증에 건다


def _facility_diseases(profile: dict) -> list[str]:
    out = []
    for d in profile.get("diseases") or []:
        if (d.get("pct") or 0) < DISEASE_MIN_PCT:
            continue
        name = str(d.get("name") or "")
        for k, v in DISEASE_MAP.items():
            if k in name and v not in out:
                out.append(v)
    return out


def _worst_menus(profile: dict, limit: int = 3) -> list[dict]:
    return [m for m in ((profile.get("menus") or {}).get("worst") or [])[:limit]
            if m.get("menu")]


def _menu_block(pr: dict, profile: dict, avoid: list[str]) -> dict | None:
    """우선순위 하나에 붙일 메뉴 후보."""
    cfg = PLAN.get(pr["id"])
    if not cfg or not graph.available():
        return None
    mode = cfg.get("mode")

    if mode == "replace":
        swaps = []
        for m in _worst_menus(profile):
            r = graph.alternatives_for(m["menu"], limit=4, avoid=avoid)
            swaps.append({
                "current": m["menu"], "current_rate": m.get("rate"),
                "current_n": m.get("n"), "matched": r["matched"],
                "meal_cat": r["meal_cat"], "candidates": r["candidates"],
                "note": None if r["matched"] else "식품 DB에 같은 이름의 요리가 없습니다. 유사 메뉴로 직접 찾아야 합니다.",
            })
        return {"purpose": cfg["purpose"], "kind": "replace", "swaps": swaps} if swaps else None

    if mode == "lowsalt":
        items = []
        for cat in cfg["cats"]:
            items += graph.low_salt_candidates(meal_cat=cat, limit=4)
        items.sort(key=lambda x: x["sodium_mg"])
        return {"purpose": cfg["purpose"], "kind": "lowsalt", "items": items,
                "basis": "1인분 나트륨 실측(mg) · 나트륨 값이 비어 있는 재료가 든 요리는 제외"}

    if mode == "boost":
        items = []
        for cat in cfg["cats"]:
            items += graph.food_candidates(
                cfg["nutrient"], meal_cat=cat, avoid=avoid, limit=4)
        return {"purpose": cfg["purpose"], "kind": "boost",
                "nutrient": cfg["nutrient"], "items": items,
                "basis": "1인분 실측 함량 순 · 나트륨·포화지방 상한을 함께 적용"}
    return None


def build(profile: dict, top: int = 5, use_rag: bool = True) -> dict:
    """시설 프로파일 → 상위 우선순위별 개선안."""
    priorities = profile.get("priorities") or []
    avoid = _facility_diseases(profile)
    plans, refs_all, tag_no = [], [], 0

    for pr in priorities[:top]:
        # ① 지침 근거
        snippets, refs = ([], [])
        if use_rag and pr.get("query"):
            snippets, refs = rag.context_for([pr["query"]])
            # 우선순위마다 새로 검색하므로 번호가 겹치지 않게 통째로 다시 매긴다
            fixed_s, fixed_r = [], []
            for s, r in zip(snippets, refs):
                tag_no += 1
                tag = f"G{tag_no}"
                fixed_s.append({**s, "id": tag})
                fixed_r.append({**r, "tag": tag})
            snippets, refs = fixed_s, fixed_r
            refs_all += refs

        # ②③ 메뉴 후보 / 교체 대상
        menus = None
        try:
            menus = _menu_block(pr, profile, avoid)
        except Exception as e:
            log.warning("[care] 메뉴 후보 생략 %s: %r", pr.get("id"), e)

        plans.append({
            "rank": pr.get("rank"), "id": pr.get("id"), "title": pr.get("title"),
            "area_label": pr.get("area_label"), "severity_label": pr.get("severity_label"),
            "score": pr.get("score"), "impact": pr.get("impact"),
            "detail": pr.get("detail"), "basis": pr.get("basis"),
            "action": pr.get("action"),
            "guidelines": [{"tag": s["id"], "source": s["출처"], "text": s["내용"]} for s in snippets],
            "references": refs,
            "menus": menus,
        })

    return {
        "facility_id": profile.get("facility_id"),
        "n_assessed": profile.get("n_assessed"),
        "diseases_applied": avoid,
        "graph": (graph.stats() if graph.available() else None),
        "rag_enabled": bool(use_rag and rag.enabled()),
        "plans": plans,
        "references": refs_all,
        "limits": [
            "영양량은 가식부 중량(뼈·껍질·육수 제외) 기준의 1인분 실측값입니다. 실제 배식량이 다르면 비례해 달라집니다.",
            "국 198개 중 125개는 육수가 재료로 등록돼 있지 않아 중량이 건더기뿐입니다.",
            "멸치액젓·참치액·명란·건새우 등은 나트륨 값이 비어 있어 해당 요리의 나트륨이 실제보다 낮게 나옵니다. 저염 후보에서는 제외했습니다.",
            "질환 금기는 시설 내 유병률 20% 이상인 질환에만 적용했습니다.",
            "식형태(연하) 관련 근거는 식품 DB가 아니라 공식 지침에서만 가져옵니다.",
        ],
    }
