# -*- coding: utf-8 -*-
"""검증용 시나리오 정의 → diet/data/validation_scenarios.json

    python -m scripts.make_scenarios

  · 합성 어르신 (식별정보 없음). 기본값에서 시나리오마다 바꾼 값만 적는다.
  · expected = 지침·규칙표에서 정한 '정답' (시스템 실행 결과를 보고 정한 값이 아님)
      issues_present  반드시 나와야 할 문제 코드        issues_absent  나오면 안 되는 문제 코드 (오탐 점검)
      avoid_kw        피할 식재료에 들어가야 할 키워드
      menu_check      최종 식단(대체찬·식사형태 반영)에 남으면 안 되는 식재료 — group(규칙표 알레르기 묶음) 또는 rule(약물 규칙)
      conflicts       탐지돼야 할 지침 충돌 (정확히 이 집합)
      overrides       적용돼야 할 약물·질환 강제 제약       removed     최종 기준에서 빠져야 할 항목
      porridge        모든 끼니 밥 칸이 죽이어야 함          cook        대체 제품 조리법 (다지기·갈기)
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "diet" / "data" / "validation_scenarios.json"

BASE = {"age": 82, "female": 1, "height_cm": 155, "weight_kg": 52, "diseases": [], "medications": [],
        "mna_sf": 12, "kmbi_score": 80, "kmbi_max": 100, "sbp": 122, "dbp": 74, "mmse": 26, "gds": 3,
        "chewing_difficulty": 0, "swallowing_difficulty": 0, "eating_dependence": 0, "intake_rate": 85}

# 알레르기 확장 점검 키워드 (식약처 알레르기 유발물질 표시 대상 기준, 규칙표 묶음과 별개로 사람이 검토할 후보)
EXTRA = {
    "갑각류": ["새우", "게", "크랩", "랍스터", "새우젓"],
    "달걀": ["달걀", "계란", "난백", "난황", "메추리알", "마요네즈", "에그"],
    "우유": ["우유", "분유", "치즈", "버터", "크림", "연유", "요구르트", "유청"],
    "대두": ["대두", "두부", "두유", "유부", "된장", "청국장", "간장", "고추장", "콩"],
    "밀": ["밀가루", "소맥", "부침가루", "튀김가루", "빵가루", "국수", "만두", "라면", "우동", "수제비", "간장", "고추장"],
    "땅콩": ["땅콩", "피넛"],
    "조개류": ["조개", "바지락", "홍합", "굴", "전복", "모시", "꼬막", "가리비", "굴소스"],
    "고등어·생선": ["고등어", "생선", "멸치", "액젓", "어묵", "참치", "명태", "황태", "북어", "동태", "가자미", "삼치", "꽁치", "조기"],
    "돼지고기": ["돼지", "돈육", "햄", "베이컨", "소시지", "삼겹", "목살", "앞다리", "스팸", "동그랑땡"],
    "메밀": ["메밀"],
}


def S(sid, domain, title, f=None, form="일반밥/일반찬", meds=None, allergies=None, **exp):
    return {"id": sid, "domain": domain, "title": title, "features": {**BASE, **(f or {})}, "meal_form": form,
            "ehr": {"medications": [{"name": n, "is_active": True} for n in (meds or [])],
                    "allergies": [{"allergen": a, "severity": "severe", "reaction": "두드러기"} for a in (allergies or [])]},
            "expected": {"issues_present": [], "issues_absent": [], "avoid_kw": [], "menu_check": [], "conflicts": [],
                         "overrides": [], "removed": [], "porridge": False, "cook": None, **exp}}


UNDER = {"weight_kg": 42}              # BMI 17.5
OBESE = {"weight_kg": 72}              # BMI 30.0
DM, HTN, KID = {"diseases": ["당뇨병"]}, {"diseases": ["고혈압"]}, {"diseases": ["신장질환"]}


def allergy(sid, allergen, group, kw):
    return S(sid, "알레르기", f"{allergen} 알레르기", allergies=[allergen],
             issues_present=["allergy"], avoid_kw=[kw],
             menu_check=[{"label": f"알레르기 {group}", "group": group, "extra": EXTRA.get(group, [])}])


SCEN = [
    # ── 알레르기 (10) ──
    allergy("A01", "새우", "갑각류", "새우"),
    allergy("A02", "달걀", "달걀", "달걀"),
    allergy("A03", "우유", "우유", "우유"),
    allergy("A04", "대두", "대두", "두부"),
    allergy("A05", "밀", "밀", "밀가루"),
    allergy("A06", "땅콩", "땅콩", "땅콩"),
    allergy("A07", "조개", "조개류", "조개"),
    allergy("A08", "고등어", "고등어·생선", "고등어"),
    allergy("A09", "돼지고기", "돼지고기", "돼지"),
    allergy("A10", "메밀", "메밀", "메밀"),
    # ── 약물-식품 상호작용 (8) ──
    S("D01", "약물-식품", "와파린 복용", meds=["와파린정 2mg"], issues_present=["warfarin_vitk"], avoid_kw=["시금치"],
      menu_check=[{"label": "와파린-비타민 K 잎채소", "rule": "warfarin_vitk"}], conflicts=["warfarin_vs_vegetables"]),
    S("D02", "약물-식품", "칼륨 보존 이뇨제(스피로노락톤) 복용", meds=["알닥톤정 25mg"], issues_present=["k_sparing"],
      avoid_kw=["바나나"], menu_check=[{"label": "칼륨 보존 이뇨제-고칼륨 식품", "rule": "k_sparing"}],
      overrides=["k_sparing_potassium"], removed=["potassium_min"]),
    S("D03", "약물-식품", "MAO-B 억제제(셀레길린) 복용", meds=["셀레길린정 5mg"], issues_present=["mao_b_tyramine"],
      avoid_kw=["청국장"], menu_check=[{"label": "MAO-B 억제제-티라민 식품", "rule": "mao_b_tyramine"}]),
    S("D04", "약물-식품", "스타틴(심바스타틴) 복용", meds=["심바스타틴정 20mg"], issues_present=["grapefruit_statin_ccb"],
      avoid_kw=["자몽"], menu_check=[{"label": "스타틴-자몽", "rule": "grapefruit_statin_ccb"}]),
    S("D05", "약물-식품", "디곡신 복용", meds=["디곡신정 0.25mg"], issues_present=["digoxin_fiber"], avoid_kw=["감초"],
      menu_check=[{"label": "디곡신-감초", "rule": "digoxin_fiber"}]),
    S("D06", "약물-식품", "레보도파 복용 (복용 시점 안내만)", meds=["마도파정"], issues_present=["levodopa_protein"]),
    S("D07", "약물-식품", "당뇨 + 인슐린 + 섭취율 45% (저혈당 위험)", {**DM, "medications": ["당뇨병약"], "intake_rate": 45},
      meds=["인슐린"], issues_present=["sugar_control", "hypoglycemia_risk"], conflicts=["energy_vs_sugar"],
      overrides=["hypoglycemia_energy"]),
    S("D08", "약물-식품", "철분제 복용 (복용 간격 안내만)", meds=["훼로바유정"], issues_present=["iron_tea"]),
    # ── 식사형태 (8) ──
    S("T01", "식사형태", "연하곤란인데 일반식", {"swallowing_difficulty": 1},
      issues_present=["aspiration_risk", "texture_mismatch"]),
    S("T02", "식사형태", "연하곤란 + 죽/갈찬", {"swallowing_difficulty": 1}, form="죽/갈찬",
      issues_present=["aspiration_risk"], issues_absent=["texture_mismatch"], porridge=True, cook="갈기"),
    S("T03", "식사형태", "저작곤란인데 일반찬", {"chewing_difficulty": 1},
      issues_present=["chewing"], issues_absent=["aspiration_risk", "texture_mismatch"]),
    S("T04", "식사형태", "저작곤란 + 밥/다진찬", {"chewing_difficulty": 1}, form="일반밥/다진찬",
      issues_present=["chewing"], issues_absent=["aspiration_risk", "texture_mismatch"], cook="다지기"),
    S("T05", "식사형태", "죽식 (곤란 없음)", form="죽/일반찬", issues_absent=["aspiration_risk", "texture_mismatch"],
      porridge=True),
    S("T06", "식사형태", "연하곤란인데 밥/다진찬", {"swallowing_difficulty": 1}, form="일반밥/다진찬",
      issues_present=["aspiration_risk", "texture_mismatch"]),
    S("T07", "식사형태", "정상 일반식 (대조군)",
      issues_absent=["aspiration_risk", "chewing", "texture_mismatch", "allergy", "hypoglycemia_risk"]),
    S("T08", "식사형태", "연하곤란 + 저작곤란 + 죽/갈찬", {"swallowing_difficulty": 1, "chewing_difficulty": 1}, form="죽/갈찬",
      issues_present=["aspiration_risk", "chewing"], issues_absent=["texture_mismatch"], porridge=True, cook="갈기"),
    # ── 질환별 기준 충돌 (10) ──
    S("K01", "기준 충돌", "당뇨 + 저체중(BMI 17.5)", {**DM, **UNDER}, issues_present=["sugar_control", "underweight"],
      conflicts=["energy_vs_sugar"]),
    S("K02", "기준 충돌", "연하곤란(갈찬) + 영양불량(MNA-SF 6)", {"swallowing_difficulty": 1, "mna_sf": 6}, form="죽/갈찬",
      issues_present=["aspiration_risk", "malnutrition_risk"], conflicts=["dysphagia_vs_protein"], porridge=True),
    S("K03", "기준 충돌", "고혈압 + 영양불량 위험(MNA-SF 9)", {**HTN, "mna_sf": 9},
      issues_present=["sodium_control", "malnutrition_risk"], conflicts=["sodium_vs_low_intake"]),
    S("K04", "기준 충돌", "비만(BMI 30) + 일상생활 기능 저하(K-MBI 30%)", {**OBESE, "kmbi_score": 30},
      issues_present=["obesity", "sarcopenia_risk"], conflicts=["obesity_vs_muscle"]),
    S("K05", "기준 충돌", "와파린 + 고혈압", HTN, meds=["와파린정 2mg"], issues_present=["warfarin_vitk", "sodium_control"],
      conflicts=["warfarin_vs_vegetables"], menu_check=[{"label": "와파린-비타민 K 잎채소", "rule": "warfarin_vitk"}]),
    S("K06", "기준 충돌", "칼륨 보존 이뇨제 + 고혈압", HTN, meds=["알닥톤정 25mg"], issues_present=["k_sparing", "sodium_control"],
      conflicts=["k_sparing_vs_potassium"], overrides=["k_sparing_potassium"], removed=["potassium_min"],
      menu_check=[{"label": "칼륨 보존 이뇨제-고칼륨 식품", "rule": "k_sparing"}]),
    S("K07", "기준 충돌", "신장질환 + 저체중", {**KID, **UNDER}, issues_present=["underweight"],
      conflicts=["protein_vs_kidney"], overrides=["kidney_potassium"], removed=["potassium_min"]),
    S("K08", "기준 충돌", "당뇨만 (충돌 없음 대조군)", DM, issues_present=["sugar_control"]),
    S("K09", "기준 충돌", "고혈압만 (충돌 없음 대조군)", HTN, issues_present=["sodium_control"]),
    S("K10", "기준 충돌", "저체중만 (충돌 없음 대조군)", UNDER, issues_present=["underweight"]),
    # ── 복합 사례 (6) ──
    S("X01", "복합", "당뇨 + 고혈압 + 새우 알레르기 + 연하곤란(일반식) + 영양불량(MNA-SF 7)",
      {"diseases": ["당뇨병", "고혈압"], "swallowing_difficulty": 1, "mna_sf": 7}, allergies=["새우"],
      issues_present=["allergy", "aspiration_risk", "texture_mismatch", "sugar_control", "sodium_control", "malnutrition_risk"],
      avoid_kw=["새우"], menu_check=[{"label": "알레르기 갑각류", "group": "갑각류", "extra": EXTRA["갑각류"]}],
      conflicts=["energy_vs_sugar", "dysphagia_vs_protein", "sodium_vs_low_intake"]),
    S("X02", "복합", "와파린 + 고혈압 + 저체중(BMI 17.8)", {**HTN, "weight_kg": 42.8}, meds=["와파린정 2mg"],
      issues_present=["warfarin_vitk", "sodium_control", "underweight"],
      menu_check=[{"label": "와파린-비타민 K 잎채소", "rule": "warfarin_vitk"}],
      conflicts=["warfarin_vs_vegetables", "sodium_vs_low_intake"]),
    S("X03", "복합", "신장질환 + 칼륨 보존 이뇨제 + 고혈압", {"diseases": ["신장질환", "고혈압"]}, meds=["알닥톤정 25mg"],
      issues_present=["k_sparing", "sodium_control"], conflicts=["k_sparing_vs_potassium", "protein_vs_kidney"],
      overrides=["k_sparing_potassium", "kidney_potassium"], removed=["potassium_min"],
      menu_check=[{"label": "칼륨 보존 이뇨제-고칼륨 식품", "rule": "k_sparing"}]),
    S("X04", "복합", "당뇨 + 고혈압 + 인슐린 + 섭취율 45%", {"diseases": ["당뇨병", "고혈압"], "medications": ["당뇨병약"],
                                                  "intake_rate": 45}, meds=["인슐린"],
      issues_present=["sugar_control", "hypoglycemia_risk", "sodium_control", "slot_low_intake"],
      conflicts=["energy_vs_sugar", "sodium_vs_low_intake"], overrides=["hypoglycemia_energy"]),
    S("X05", "복합", "치매 + 저작곤란 + 우유 알레르기 + 식사 도움 필요",
      {"diseases": ["치매"], "chewing_difficulty": 1, "eating_dependence": 1, "mmse": 15}, form="일반밥/다진찬",
      allergies=["우유"], issues_present=["brain_food", "chewing", "allergy", "eating_assist"],
      issues_absent=["aspiration_risk", "texture_mismatch"], avoid_kw=["우유"],
      menu_check=[{"label": "알레르기 우유", "group": "우유", "extra": EXTRA["우유"]}], cook="다지기"),
    S("X06", "복합", "당뇨 + 비만(BMI 30) + 일상생활 기능 저하(K-MBI 30%)", {**DM, **OBESE, "kmbi_score": 30},
      issues_present=["sugar_control", "obesity", "sarcopenia_risk"], conflicts=["obesity_vs_muscle"]),
]


def main():
    OUT.write_text(json.dumps({"_설명": __doc__.strip(), "base": BASE, "scenarios": SCEN}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    from collections import Counter
    print(f"{len(SCEN)}개 시나리오 → {OUT}")
    print(dict(Counter(s["domain"] for s in SCEN)))


if __name__ == "__main__":
    main()
