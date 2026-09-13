# -*- coding: utf-8 -*-
"""
돌봄 조치 규칙 라이브러리 (솔루션의 근거 목록)
 - LLM 은 여기서 선택된 후보(rule_id)만 근거로 개인화·우선순위화한다.
 - LLM 미사용 시 이 규칙만으로 솔루션을 만든다.
각 규칙: id, category, when(f, ctx) → bool, staff(담당자 조치), meal(식사 지침), monitor(관찰), guardian(보호자용 쉬운 문장)
"""
from __future__ import annotations


def _v(f, k):
    x = f.get(k)
    return None if x is None else float(x)


def _flag(f, k):
    return _v(f, k) == 1


RULES = [
    dict(id="R_SWALLOW", category="식사 형태·안전",
         when=lambda f, c: _flag(f, "swallowing_difficulty"),
         staff="삼킴 단계에 맞는 식사 형태와 국물·음료 점도 조절을 영양사·간호 인력과 함께 확인합니다. 필요 시 의료진에게 삼킴 평가를 요청합니다.",
         meal="식사 때 상체를 세워 앉히고, 한 번에 적은 양을 천천히 드시도록 돕습니다. 식후 30분은 눕지 않도록 합니다.",
         monitor="식사 중 사레·기침, 목소리 변화, 식사 시간 지연을 관찰합니다.",
         guardian="삼키기가 불편하셔서 식사 형태와 자세를 안전하게 맞춰 드리고 있습니다."),
    dict(id="R_CHEW", category="식사 형태·안전",
         when=lambda f, c: _flag(f, "chewing_difficulty") and not _flag(f, "swallowing_difficulty"),
         staff="구강 상태와 의치 착용·불편감을 점검합니다.",
         meal="질긴 음식은 잘게 썰거나 충분히 익혀 부드럽게 제공합니다.",
         monitor="씹기 어려운 반찬을 남기는지 잔반으로 확인합니다.",
         guardian="씹기 편하도록 반찬을 부드럽게 조리해 드리고 있습니다."),
    dict(id="R_MALNUT", category="영양",
         when=lambda f, c: _v(f, "mna_sf") is not None and _v(f, "mna_sf") <= 7,
         staff="영양 상태가 낮게 평가되어 영양사(또는 간호 인력)의 상세 영양 평가를 요청합니다.",
         meal="끼니 사이 열량·단백질을 보충할 수 있는 간식을 추가하는 방안을 영양사와 검토합니다.",
         monitor="체중을 주 1회 측정하고 식사량을 매 끼니 기록합니다.",
         guardian="영양 관리가 더 필요한 상태라 식사와 간식을 세심하게 챙기고 체중을 자주 확인하고 있습니다."),
    dict(id="R_MALNUT_RISK", category="영양",
         when=lambda f, c: _v(f, "mna_sf") is not None and 7 < _v(f, "mna_sf") <= 11,
         staff="영양 위험 단계로 식사량 기록을 강화합니다.",
         meal="좋아하시는 단백질 반찬을 우선 제공합니다.",
         monitor="체중을 월 2회 측정합니다.",
         guardian="영양이 부족해지지 않도록 식사량과 체중을 정기적으로 확인하고 있습니다."),
    dict(id="R_LOW_BMI", category="영양",
         when=lambda f, c: _v(f, "bmi") is not None and _v(f, "bmi") < 18.5,
         staff="저체중 상태로 체중 추이를 기록합니다.",
         meal="같은 양으로도 열량·단백질이 높은 조리법(예: 죽·국에 들기름, 달걀, 두부 더하기)을 영양사와 검토합니다.",
         monitor="체중 변화를 월별로 비교합니다.",
         guardian="체중이 적은 편이라 체중 변화를 꾸준히 살피고 있습니다."),
    dict(id="R_LOW_INTAKE", category="식사 섭취",
         when=lambda f, c: _v(f, "intake_total") is not None and _v(f, "intake_total") < 75,
         staff="잔반이 많은 원인(맛·양·식사 형태·식사 도움 여부)을 식사 관찰로 확인합니다.",
         meal="한 번에 많이 드리기보다 적은 양을 나눠 드리고, 선호 음식을 식단에 반영합니다.",
         monitor="5일간 끼니별 잔반을 다시 기록해 변화를 확인합니다.",
         guardian="식사량이 다소 적으셔서 좋아하시는 음식 위주로 조금씩 자주 드리려고 합니다."),
    dict(id="R_LOW_PROTEIN", category="식사 섭취",
         when=lambda f, c: _v(f, "intake_main") is not None and _v(f, "intake_main") < 60,
         staff="주찬(단백질 반찬) 섭취가 적어 식사 시 주찬부터 권합니다.",
         meal="두부, 달걀찜, 부드러운 생선살처럼 먹기 쉬운 단백질 반찬을 활용합니다.",
         monitor="주찬 잔반을 별도로 확인합니다.",
         guardian="근력 유지를 위해 단백질 반찬을 드시기 쉽게 준비하고 있습니다."),
    dict(id="R_DISSAT", category="급식 만족",
         when=lambda f, c: any(_v(f, k) is not None and _v(f, k) <= 2.5 for k in ("sat_overall", "sat_quality")),
         staff="급식에 대한 불편 사항(간, 조리법, 메뉴)을 직접 여쭤 기록하고 조리팀과 공유합니다.",
         meal="의견을 반영해 간·조리법을 조정할 수 있는지 조리팀과 검토합니다.",
         monitor="다음 만족도 조사에서 변화를 확인합니다.",
         guardian="식사에 대한 의견을 여쭙고 입맛에 맞게 조정하려고 합니다."),
    dict(id="R_SEAFOOD_SOFT", category="선호 반영",
         when=lambda f, c: _flag(f, "pref_seafood") and (_flag(f, "chewing_difficulty") or _flag(f, "swallowing_difficulty")),
         staff="생선·해산물을 좋아하시므로 가시를 제거한 부드러운 생선 요리를 식단에 반영합니다.",
         meal="가시 없는 생선살 조림·찜 등 부드러운 수산물 메뉴를 활용합니다.",
         monitor="해당 메뉴의 잔반을 확인합니다.",
         guardian="좋아하시는 생선 요리를 드시기 편하게 준비해 드리려고 합니다."),
    dict(id="R_DEPEND", category="식사 도움",
         when=lambda f, c: _v(f, "eating_dependence") is not None and _v(f, "eating_dependence") >= 1,
         staff="식사 도움이 필요하므로 식사 시간에 도움 인력을 배치하고 충분한 식사 시간을 확보합니다.",
         meal="식사 속도에 맞춰 천천히 도와드립니다.",
         monitor="도움 제공 후 섭취량 변화를 확인합니다.",
         guardian="식사하실 때 옆에서 도와드리며 충분히 드실 수 있게 하고 있습니다."),
    dict(id="R_MOOD", category="정서",
         when=lambda f, c: _v(f, "gds") is not None and _v(f, "gds") >= 8,
         staff="기분 저하 신호가 있어 말벗·여가 프로그램 참여를 권하고, 필요 시 전문가 상담 연계를 검토합니다.",
         meal="가능하면 다른 어르신들과 함께 식사하도록 권합니다.",
         monitor="식욕·수면·활동 참여 변화를 관찰합니다.",
         guardian="기분이 가라앉아 계실 때가 있어 대화와 프로그램 참여를 늘리고 있습니다. 가족분의 전화·면회도 큰 도움이 됩니다."),
    dict(id="R_DIABETES", category="질환 식사",
         when=lambda f, c: _flag(f, "dx_diabetes"),
         staff="당뇨가 있어 간식 종류와 단 음식 제공을 영양사와 확인합니다.",
         meal="단순당이 많은 간식은 조절하고 규칙적인 식사 시간을 유지합니다.",
         monitor="간호 기록의 혈당 관리 사항과 함께 확인합니다.",
         guardian="당뇨를 고려해 간식과 식사 시간을 조절하고 있습니다."),
    dict(id="R_HTN_TASTE", category="질환 식사",
         when=lambda f, c: _flag(f, "dx_hypertension") and _flag(f, "cmt_seasoning"),
         staff="싱겁다는 의견이 있으나 고혈압이 있어 소금 대신 향신채·깨·들기름 등으로 풍미를 높이는 방안을 조리팀과 검토합니다.",
         meal="염분은 유지하되 향과 식감으로 맛을 보완합니다.",
         monitor="만족도와 섭취율을 함께 확인합니다.",
         guardian="혈압을 고려하면서도 맛있게 드실 수 있도록 조리법을 조정하고 있습니다."),
    dict(id="R_DEMENTIA_ENV", category="식사 환경",
         when=lambda f, c: _flag(f, "dx_dementia") and ((_v(f, "intake_total") or 100) < 75 or (_v(f, "eating_dependence") or 0) >= 1),
         staff="식사에 집중할 수 있도록 조용한 환경과 한두 가지씩 순서대로 제공하는 방식을 시도합니다.",
         meal="음식이 잘 보이도록 식기 색을 대비되게 하고, 한 번에 한두 그릇씩 드립니다.",
         monitor="환경 조정 후 식사 시간·섭취량을 비교합니다.",
         guardian="식사에 집중하실 수 있도록 식사 환경을 편안하게 맞추고 있습니다."),
    dict(id="R_WEIGHT_LOSS", category="변화 대응",
         when=lambda f, c: "weight_loss" in c.get("factor_codes", ()),
         staff="체중이 5% 이상 줄어 간호 인력·의료진에게 보고하고 원인을 확인합니다.",
         meal="식사량과 간식 보충 계획을 다시 세웁니다.",
         monitor="2주 뒤 체중을 재측정합니다.",
         guardian="최근 체중이 줄어 원인을 확인하고 식사 계획을 조정하고 있습니다."),
    dict(id="R_INTAKE_DROP", category="변화 대응",
         when=lambda f, c: "intake_drop" in c.get("factor_codes", ()),
         staff="직전 평가보다 식사량이 크게 줄어 건강 변화(구강 통증, 변비, 컨디션 등)를 확인합니다.",
         meal="선호 메뉴와 식사 형태를 다시 점검합니다.",
         monitor="1주간 섭취량을 매일 기록합니다.",
         guardian="최근 식사량이 줄어 컨디션을 살피며 식사를 조정하고 있습니다."),
    dict(id="R_REASSESS", category="재평가",
         when=lambda f, c: c.get("is_borderline") or _v(f, "has_nutrition") == 0 or _flag(f, "mmse_untested"),
         staff="유형 판정이 경계에 있거나 일부 조사가 비어 있어, 누락 항목(잔반 조사·인지 검사 등)을 보완해 재평가합니다.",
         meal="",
         monitor="보완 조사 후 재평가를 실행합니다.",
         guardian=""),
    dict(id="R_MAINTAIN", category="유지",
         when=lambda f, c: c.get("priority_level") == "low",
         staff="현재 식사와 활동을 유지하고 정기 재평가 일정을 따릅니다.",
         meal="현재 식사 형태와 선호를 유지합니다.",
         monitor="다음 정기 평가 때 지표를 비교합니다.",
         guardian="현재 식사와 건강 상태가 안정적으로 유지되고 있습니다."),
]
RULE_BY_ID = {r["id"]: r for r in RULES}


def select(features: dict, ctx: dict):
    out = []
    for r in RULES:
        try:
            if r["when"](features, ctx):
                out.append({k: r[k] for k in ("id", "category", "staff", "meal", "monitor", "guardian")})
        except Exception:
            continue
    return out
