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


def _pct(c, k):
    """권장 섭취 기준 대비 % (ctx['nutrition_pct'] 에서 읽는다)."""
    return (c.get("nutrition_pct") or {}).get(k)


def _below(c, k, cut):
    v = _pct(c, k)
    return v is not None and v < cut


def _above(c, k, cut):
    v = _pct(c, k)
    return v is not None and v > cut


def _dx(f, *keywords):
    """진단 질환 목록(기초조사표)에 키워드가 들어 있는지"""
    names = f.get("diseases")
    if not isinstance(names, list):
        return False
    joined = " ".join(str(x) for x in names)
    return any(k in joined for k in keywords)


def _low_component(c, *keys):
    """잔반이 특히 많은 음식군 (ctx['low_components'])"""
    lows = c.get("low_components") or ()
    return any(k in lows for k in keys)


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
    dict(id="R_NUT_ENERGY", category="영양(섭취량)",
         when=lambda f, c: _below(c, "energy", 75),
         staff="실제 섭취 열량이 권장량의 3/4에 못 미쳐 영양사와 식사 계획을 다시 검토합니다. 끼니별 섭취 기록에서 어느 끼니가 특히 적은지 확인합니다.",
         meal="적은 양으로도 열량이 높아지도록 조리법을 조정하고(들기름·달걀·두부 등), 끼니 사이 간식을 추가하는 방안을 검토합니다.",
         monitor="체중을 주 1회 측정하고 2주 뒤 섭취 열량을 다시 계산합니다.",
         guardian="드신 양을 계산해 보니 필요량보다 적으셔서, 조금씩 자주 드실 수 있도록 식사와 간식을 조정하고 있습니다."),
    dict(id="R_NUT_PROTEIN", category="영양(섭취량)",
         when=lambda f, c: _below(c, "protein", 80),
         staff="단백질 섭취가 권장량에 못 미쳐 식사 시 주찬을 먼저 권하고, 남기는 이유(질감·맛·양)를 확인합니다.",
         meal="두부, 달걀찜, 부드러운 생선살, 다진 고기처럼 드시기 쉬운 단백질 반찬을 늘립니다.",
         monitor="주찬 잔반을 끼니마다 기록해 2주 뒤 비교합니다.",
         guardian="근력 유지에 필요한 단백질 반찬을 더 드실 수 있도록 메뉴를 조정하고 있습니다."),
    dict(id="R_NUT_CALCIUM", category="영양(섭취량)",
         when=lambda f, c: _below(c, "ca", 70),
         staff="칼슘 섭취가 낮아 유제품·두부·뼈째 먹는 생선 등 급원 식품의 제공 빈도를 영양사와 검토합니다.",
         meal="간식으로 우유·두유·요구르트를 제공하는 방안을 검토합니다.",
         monitor="간식 섭취 여부를 기록합니다.",
         guardian="뼈 건강에 필요한 칼슘이 부족하지 않도록 유제품 간식 등을 늘려 드리고 있습니다."),
    dict(id="R_NUT_FIBER", category="영양(섭취량)",
         when=lambda f, c: _below(c, "fiber", 70),
         staff="식이섬유 섭취가 낮아 배변 상태를 함께 확인합니다.",
         meal="부드럽게 익힌 채소·나물과 과일을 끼니마다 제공하고, 필요 시 다진 형태로 드립니다.",
         monitor="배변 횟수와 복부 불편감을 기록합니다.",
         guardian="변비가 생기지 않도록 채소와 과일을 부드럽게 조리해 함께 드리고 있습니다."),
    # 나트륨 과다는 섭취율로 나눈다.
    #   잘 드시는 경우  → 배식량을 줄여도 총 섭취가 무너지지 않는다
    #   적게 드시는 경우 → 총량을 줄이면 영양불량 위험이 커진다(ESPEN R11 / 치매 권고 13).
    #                     조리 단계에서 염도를 낮추고 국물 대신 건더기로 바꾸는 방식만 쓴다.
    dict(id="R_NUT_SODIUM", category="영양(섭취량)",
         when=lambda f, c: _above(c, "na", 130) and (_v(f, "intake_total") or 100) >= 75,
         staff="나트륨 섭취가 기준보다 높고 식사량은 유지되고 있어, 국·찌개 국물 제공량과 김치·젓갈류 반찬 배식량을 영양사와 조정합니다. 고혈압·신장 관련 지병이 있으면 의료진과 상의합니다.",
         meal="국은 건더기 위주로 담고 국물 양을 줄입니다. 절임·젓갈 반찬은 소량만 제공합니다.",
         monitor="혈압을 주 1회 측정하고, 조정 후 식사 섭취율이 떨어지지 않는지 함께 확인합니다.",
         guardian="짠 음식이 많지 않도록 국물 양과 절임 반찬을 조절해 드리고 있습니다."),
    dict(id="R_NUT_SODIUM_LOWEAT", category="영양(섭취량)",
         when=lambda f, c: _above(c, "na", 130) and (_v(f, "intake_total") or 100) < 75,
         staff="나트륨 섭취는 높지만 식사량 자체가 적어, 배식량을 줄이는 대신 조리 단계에서 염도를 낮추는 방향으로 영양사와 조정합니다. 드시는 양을 더 줄이지 않는 것이 우선입니다.",
         meal="국은 국물을 덜고 건더기 위주로 담되 반찬 가짓수와 양은 유지합니다. 간을 줄이는 대신 식초·깨·참기름·채소 향으로 풍미를 살립니다.",
         monitor="혈압과 함께 식사 섭취율·체중을 2주 간격으로 확인합니다.",
         guardian="드시는 양이 줄지 않도록 반찬은 그대로 두고, 조리할 때 간을 덜어 드리고 있습니다."),
    dict(id="R_NUT_MEAL_GAP", category="영양(섭취량)",
         when=lambda f, c: c.get("low_meal") is not None,
         staff="특정 끼니의 섭취 열량이 뚜렷하게 낮아 그 시간대의 컨디션·식사 도움·메뉴를 점검합니다.",
         meal="해당 끼니에는 좋아하시는 메뉴를 배치하고 식사 도움을 늘립니다.",
         monitor="해당 끼니의 섭취량을 1주간 매일 기록합니다.",
         guardian="특정 끼니에 덜 드시는 편이라 그 시간대 식사를 더 살펴 드리고 있습니다."),
    # ── 질환 기반 ──────────────────────────────────────────
    dict(id="R_DX_DIABETES", category="질환 관리",
         when=lambda f, c: not _flag(f, "dx_diabetes") and _dx(f, "당뇨"),
         staff="당뇨가 있어 식사 시간과 간식 시간을 일정하게 유지하고, 식사량이 갑자기 줄거나 늘면 기록합니다. 혈당·약 조절은 의료진과 상의합니다.",
         meal="단 음료·과자 대신 우유·두유·과일 같은 간식을 배치하고, 국물과 절임 반찬은 적당량으로 제공합니다.",
         monitor="식사량과 간식 섭취를 매 끼니 기록하고, 저혈당 의심 증상(식은땀·기운 없음)을 관찰합니다.",
         guardian="당뇨가 있으셔서 식사·간식 시간을 규칙적으로 지켜 드리고 있습니다."),
    dict(id="R_DX_HTN", category="질환 관리",
         when=lambda f, c: ((_flag(f, "dx_hypertension") or _dx(f, "고혈압"))
                            and not _below(c, "na", 80) and (_v(f, "intake_total") or 100) >= 75),
         staff="고혈압이 있어 국물·절임 반찬 배식량을 조절하고 혈압 기록을 유지합니다.",
         meal="국은 건더기 위주로 담고 국물은 적게, 김치·젓갈류는 소량만 제공합니다.",
         monitor="혈압을 주 1회 측정하고 부종 여부를 확인합니다.",
         guardian="혈압 관리를 위해 국물과 짠 반찬 양을 조절해 드리고 있습니다."),
    dict(id="R_DX_HTN_LOWEAT", category="질환 관리",
         when=lambda f, c: ((_flag(f, "dx_hypertension") or _dx(f, "고혈압"))
                            and (_v(f, "intake_total") or 100) < 75),
         staff="고혈압이 있지만 식사량이 적어, 배식량을 줄이는 방식의 저염 관리는 피하고 조리 염도 조정으로 접근합니다. 혈압 기록은 유지하고 필요 시 의료진과 상의합니다.",
         meal="반찬 가짓수와 양은 유지하면서 조리 단계에서 간을 낮춥니다. 국물은 덜어 내고 건더기 위주로 담습니다.",
         monitor="혈압과 함께 체중·식사 섭취율을 2주 간격으로 확인합니다.",
         guardian="혈압을 살피면서도 드시는 양이 줄지 않도록 간만 덜어 드리고 있습니다."),
    dict(id="R_DX_DEMENTIA", category="질환 관리",
         when=lambda f, c: _flag(f, "dx_dementia") or _dx(f, "치매"),
         staff="식사에 집중하기 어려울 수 있어 조용한 자리, 익숙한 식기, 한 번에 한 가지씩 권하기를 적용합니다.",
         meal="반찬을 한꺼번에 놓기보다 순서대로 드리고, 손으로 집어 드실 수 있는 형태를 함께 냅니다.",
         monitor="식사 시간, 남긴 양, 식사 중 자리 이탈을 기록합니다.",
         guardian="식사에 집중하기 편한 환경을 만들어 천천히 도와 드리고 있습니다."),
    dict(id="R_DX_KIDNEY", category="질환 관리",
         when=lambda f, c: _dx(f, "신장", "신부전", "투석"),
         staff="신장 질환이 있어 단백질·칼륨·나트륨 조절이 필요한지 담당 의료진과 반드시 확인한 뒤 식단을 조정합니다.",
         meal="의료진 지시 전에는 임의로 단백질·칼륨 식품을 늘리거나 줄이지 않습니다.",
         monitor="부종, 소변량 변화, 체중 변화를 기록합니다.",
         guardian="신장 상태에 맞춰 의료진과 상의하며 식사를 조정하고 있습니다."),
    dict(id="R_DX_ANEMIA", category="질환 관리",
         when=lambda f, c: _dx(f, "빈혈") or _below(c, "fe", 70),
         staff="철 섭취가 부족하거나 빈혈 이력이 있어 급원 식품 제공 빈도를 영양사와 확인합니다.",
         meal="살코기·간·달걀·해조류 같은 철 급원을 늘리고, 비타민 C가 있는 채소·과일을 같이 냅니다.",
         monitor="어지럼·기운 없음·창백함을 관찰합니다.",
         guardian="철분이 부족하지 않도록 반찬 구성을 조정하고 있습니다."),
    dict(id="R_DX_OSTEO", category="질환 관리",
         when=lambda f, c: _dx(f, "골다공증", "골절") or (_below(c, "ca", 70) and _below(c, "vd", 50)),
         staff="뼈 건강 관리가 필요해 칼슘·비타민 D 급원 제공과 낮 시간 활동을 함께 검토합니다.",
         meal="우유·두유·요구르트·뼈째 먹는 생선·두부를 간식과 반찬에 배치합니다.",
         monitor="낙상 위험과 보행 상태를 함께 확인합니다.",
         guardian="뼈 건강을 위해 유제품과 칼슘이 많은 반찬을 늘려 드리고 있습니다."),
    dict(id="R_DX_CONSTIPATION", category="질환 관리",
         when=lambda f, c: _dx(f, "변비") or (_below(c, "fiber", 70) and _below(c, "k", 70)),
         staff="배변 상태를 매일 기록하고, 수분 섭취량을 함께 확인합니다.",
         meal="부드럽게 익힌 채소·해조류·과일을 끼니마다 제공하고 수분을 자주 권합니다.",
         monitor="배변 횟수와 복부 팽만을 기록합니다.",
         guardian="변비가 생기지 않도록 채소·과일과 물을 자주 챙겨 드리고 있습니다."),
    # ── 잔반(음식군) 기반 ───────────────────────────────────
    dict(id="R_LEFT_SOUP", category="잔반 대응",
         when=lambda f, c: _low_component(c, "국·탕"),
         staff="국·탕을 특히 많이 남겨 온도·간·양이 맞는지 식사 관찰로 확인합니다.",
         meal="국물 양을 줄이고 건더기 위주로 담아 드립니다. 삼키기 어려우면 점도 조절을 검토합니다.",
         monitor="국·탕 잔반을 1주간 따로 기록합니다.",
         guardian="국을 많이 남기셔서 건더기 위주로 담아 드리고 있습니다."),
    dict(id="R_LEFT_SIDE", category="잔반 대응",
         when=lambda f, c: _low_component(c, "부찬"),
         staff="부찬을 많이 남겨 식감·선호를 확인하고, 좋아하시는 반찬으로 교체 가능한지 검토합니다.",
         meal="질긴 나물은 부드럽게 익히거나 잘게 썰어 제공합니다.",
         monitor="어떤 반찬을 남기는지 이름과 함께 기록합니다.",
         guardian="남기시는 반찬을 파악해 좋아하시는 것으로 바꿔 드리고 있습니다."),
    dict(id="R_LEFT_RICE", category="잔반 대응",
         when=lambda f, c: _low_component(c, "밥·죽"),
         staff="주식을 많이 남겨 1회 배식량이 많은지, 식사 형태가 맞는지 확인합니다.",
         meal="한 번에 담는 밥·죽 양을 줄이고, 남기면 간식으로 열량을 보충합니다.",
         monitor="주식 잔반과 체중을 함께 봅니다.",
         guardian="밥을 남기셔서 양을 조절하고 간식으로 보충해 드리고 있습니다."),
    dict(id="R_LEFT_KIMCHI", category="잔반 대응",
         when=lambda f, c: _low_component(c, "김치"),
         staff="김치를 거의 드시지 않아 대체 채소 반찬으로 섬유·비타민을 보완합니다.",
         meal="익힌 나물·샐러드 등 드시기 편한 채소 반찬을 추가합니다.",
         monitor="채소 섭취량을 확인합니다.",
         guardian="김치를 잘 안 드셔서 다른 채소 반찬으로 챙겨 드리고 있습니다."),
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


# [2026-11-24] 돌봄 우선순위 요인 → 그 요인을 다루는 규칙
#   솔루션에는 이 규칙이 후보에 있으면 반드시 들어가야 한다 (solution.validate 가 빠진 것을 채우고, verify 가 확인)
FACTOR_RULES = {
    "mna_malnourished": ["R_MALNUT"], "mna_at_risk": ["R_MALNUT_RISK"], "low_bmi": ["R_LOW_BMI"],
    "intake_very_low": ["R_LOW_INTAKE"], "intake_low": ["R_LOW_INTAKE"], "protein_dish_low": ["R_LOW_PROTEIN", "R_NUT_PROTEIN"],
    "swallowing": ["R_SWALLOW"], "chewing": ["R_CHEW"], "eating_full_help": ["R_DEPEND"], "eating_partial_help": ["R_DEPEND"],
    "depressive": ["R_MOOD"], "depressive_mild": ["R_MOOD"], "weight_loss": ["R_WEIGHT_LOSS"], "intake_drop": ["R_INTAKE_DROP"],
}


def required_rules(priority: dict, candidates: list) -> list[dict]:
    """우선순위 요인마다 솔루션에 꼭 들어갈 규칙 (후보에 있는 것만) → [{factor, rules}]"""
    cand = [c["id"] for c in candidates]
    out = []
    for fx in (priority or {}).get("factors") or []:
        rs = [r for r in FACTOR_RULES.get(fx.get("code"), []) if r in cand]
        if rs and (fx.get("points") or 0) > 0:
            out.append({"factor": fx.get("label"), "code": fx.get("code"), "points": fx.get("points"), "rules": rs})
    return out


# [2026-11-24] 규칙별 근거 지침 조항 (문헌 id, 소제목) — 솔루션 생성 때 이 조항 문단을 먼저 붙이고,
#   조치마다 이 중 실제로 뒷받침하는 조항을 [G#] 로 인용하게 한다 (조치의 근거 = 지침)
EG, ED, LTC, KSH, KDA = "ESPEN_GERIATRIC", "ESPEN_DEMENTIA", "LTC_MEAL_GUIDE", "KSH_HTN_2026", "KDA_DM_2025"
_SALT = (LTC, "길라잡이 삼삼한 조리 전략 (저염)")
_FORT = (LTC, "길라잡이 영양 강화 조리 전략")
_EASY = (LTC, "길라잡이 먹기 쉬운 조리 전략")
_PREF = (ED, "치매 권고 11 개인의 습관과 선호")
RULE_EVIDENCE = {
    "R_SWALLOW": [("IDDSI", "IDDSI 식사형태는 평가로 정한다"), ("IDDSI", "IDDSI 음료 단계와 흐름 검사"), (EG, "R22 식사 형태 조정")],
    "R_CHEW": [_EASY, ("IDDSI", "IDDSI 레벨 6 부드럽고 한입 크기")],
    "R_MALNUT": [(EG, "R6 선별 양성 후 절차"), (EG, "R20 영양 강화식"), (EG, "R21 간식·핑거푸드")],
    "R_MALNUT_RISK": [(EG, "R20 영양 강화식"), (EG, "R21 간식·핑거푸드"), _FORT],
    "R_LOW_BMI": [(EG, "R1 에너지 필요량"), _FORT],
    "R_LOW_INTAKE": [(EG, "R10 저영양·탈수의 원인 제거"), (EG, "R13 식사 환경"), (EG, "R21 간식·핑거푸드")],
    "R_LOW_PROTEIN": [(EG, "R2 단백질 필요량"), ("SARCOPENIA_KR", "근감소증 영양요법 — 단백질 목표량")],
    "R_DISSAT": [_PREF, (LTC, "길라잡이 신메뉴 적용 전략")],
    "R_SEAFOOD_SOFT": [_PREF, _EASY],
    "R_DEPEND": [(EG, "R12 식사 돕기"), (ED, "치매 권고 17 식기와 보조도구")],
    "R_MOOD": [(EG, "R14 함께 먹기"), (EG, "R13 식사 환경")],
    "R_DIABETES": [(KDA, "당뇨 의학영양요법 권고 6 첨가당과 가당음료"), (KDA, "당뇨 의학영양요법 권고 7 단백질을 제한하지 않는다")],
    "R_HTN_TASTE": [_SALT, (KSH, "고혈압 염분감수성 — 고령자에서 더 높다")],
    "R_DEMENTIA_ENV": [(ED, "치매 권고 6 식사 환경"), (ED, "치매 권고 16 식사 돕기")],
    "R_WEIGHT_LOSS": [(EG, "R10 저영양·탈수의 원인 제거"), (EG, "R6 선별 양성 후 절차")],
    "R_INTAKE_DROP": [(EG, "R10 저영양·탈수의 원인 제거"), (ED, "치매 권고 12 원인 확인과 관리")],
    "R_NUT_ENERGY": [(EG, "R1 에너지 필요량"), (EG, "R20 영양 강화식"), _FORT],
    "R_NUT_PROTEIN": [(EG, "R2 단백질 필요량"), ("SARCOPENIA_KR", "근감소증 영양요법 — 단백질 목표량")],
    "R_NUT_CALCIUM": [(LTC, "길라잡이 칼슘 급원 식품")],
    "R_NUT_FIBER": [(EG, "R3 식이섬유"), (EG, "R61 수분 섭취")],
    "R_NUT_SODIUM": [_SALT, (KSH, "고혈압 권고 21 소금 섭취 제한"), (KSH, "고혈압 염분감수성 — 고령자에서 더 높다")],
    "R_NUT_SODIUM_LOWEAT": [_SALT, (EG, "R11 불필요한 식사 제한 금지")],
    "R_NUT_MEAL_GAP": [(LTC, "길라잡이 식생활지침 3·4·5 규칙적인 식사, 수분, 활동량"), (EG, "R21 간식·핑거푸드")],
    "R_DX_DIABETES": [(KDA, "당뇨 의학영양요법 권고 1 개별화된 의학영양요법"), ("DRUG_FOOD", "약물-식품 당뇨약 · 저혈당")],
    "R_DX_HTN": [(KSH, "고혈압 권고 21 소금 섭취 제한"), _SALT],
    "R_DX_HTN_LOWEAT": [(EG, "R11 불필요한 식사 제한 금지"), _SALT],
    "R_DX_DEMENTIA": [(ED, "치매 권고 6 식사 환경"), (ED, "치매 권고 17 식기와 보조도구"), (ED, "치매 권고 19 음료·간식·핑거푸드")],
    "R_DX_KIDNEY": [("MFDS_MEAL_STD", "식품규격 신장질환자용 식단형 식품"), ("DRUG_FOOD", "약물-식품 칼륨 보존 이뇨제 · 고칼륨 식품")],
    "R_DX_ANEMIA": [(EG, "R4 미량영양소"), ("DRUG_FOOD", "약물-식품 철분제 · 차·커피·우유")],
    "R_DX_OSTEO": [(LTC, "길라잡이 칼슘 급원 식품"), (EG, "R4 미량영양소")],
    "R_DX_CONSTIPATION": [(EG, "R3 식이섬유"), (EG, "R61 수분 섭취")],
    "R_LEFT_SOUP": [_SALT, _PREF],
    "R_LEFT_SIDE": [_PREF, (ED, "치매 권고 7 음식 선택권"), _EASY],
    "R_LEFT_RICE": [(EG, "R20 영양 강화식"), (EG, "R21 간식·핑거푸드")],
    "R_LEFT_KIMCHI": [(LTC, "길라잡이 식품군별 권장 섭취 횟수"), (ED, "치매 권고 7 음식 선택권")],
    "R_REASSESS": [(EG, "R5 저영양 선별")],
    "R_MAINTAIN": [(EG, "R8 개별화된 포괄적 돌봄")],
}

# 규칙별 '식사로 해결하는 방법' 예시 — 숫자는 넣지 않는다 (양·횟수는 근거 지침 문단이나 입력 자료에 있는 숫자만 쓴다)
MEAL_HINTS = {
    "R_SWALLOW": "평가된 단계에 맞춰 식사형태(다진찬·갈찬)와 국·음료 점도를 맞추고, 상체를 세운 자세로 한 숟가락씩 천천히",
    "R_CHEW": "고기·채소는 잘게 다지거나 찜·조림으로 무르게. 질긴 나물·마른반찬은 달걀찜·두부조림·호박나물 같은 무른 반찬으로 교체",
    "R_MALNUT": "끼니 사이 간식(두유·요구르트·삶은 달걀·카스텔라 등)을 더하고, 죽·밥·국에 기름·깨·달걀 등으로 영양을 강화",
    "R_MALNUT_RISK": "잘 드시는 메뉴를 더 담고, 끼니 사이에 단백질 간식(두유·삶은 달걀·연두부 등)을 더함",
    "R_LOW_BMI": "밥 양은 유지하고 죽·국에 들기름·깨, 반찬에 두부·달걀을 더해 같은 양으로 열량을 높임",
    "R_LOW_INTAKE": "한 번에 담는 양을 줄여 자주 드리고(소량 다회), 잘 드시는 메뉴 위주로 담고 남기는 메뉴는 대체",
    "R_LOW_PROTEIN": "주찬을 부드럽게(다진 고기찜·생선살·두부·달걀찜) 바꾸고 식사 때 주찬부터 권함",
    "R_DISSAT": "불편 사항(간·조리법·메뉴)을 여쭤 좋아하는 메뉴를 식단에 넣도록 조리팀과 조정",
    "R_SEAFOOD_SOFT": "가시를 뺀 생선찜·생선살조림을 식단에 넣음",
    "R_DEPEND": "한입 크기로 자르고 손잡이 숟가락·미끄럼 방지 식판 사용, 손으로 집는 메뉴(주먹밥·전) 활용",
    "R_MOOD": "좋아하시는 음식을 식단에 넣고, 다른 어르신과 함께 드시는 자리 배치",
    "R_DIABETES": "단 간식·가당음료(떡·과자·주스) 대신 우유·두부·삶은 달걀, 과일은 한 번에 조금씩. 단백질은 제한하지 않음",
    "R_HTN_TASTE": "소금 대신 식초·레몬·들기름·깨·마늘·파로 풍미를 내고, 한 메뉴에 간을 집중",
    "R_DEMENTIA_ENV": "한 번에 한두 가지씩 순서대로, 대비되는 색 식기, 조용한 자리",
    "R_WEIGHT_LOSS": "보고와 함께 끼니 사이 간식과 영양 강화(죽에 참기름, 두유)를 바로 시작",
    "R_INTAKE_DROP": "원인 확인과 함께 부드럽고 좋아하는 메뉴를 소량씩 자주 제공",
    "R_NUT_ENERGY": "적게 드시는 끼니에 간식을 더하고, 밥·죽·국에 기름·깨로 영양 강화",
    "R_NUT_PROTEIN": "끼니마다 단백질 반찬(두부·달걀·생선·살코기)을 넣고, 간식으로 우유·두유",
    "R_NUT_CALCIUM": "우유·요구르트, 멸치·두부·뱅어포·무청 등 칼슘 급원 반찬을 자주",
    "R_NUT_FIBER": "나물·버섯·해조류 반찬, 고구마·잡곡, 충분한 물",
    "R_NUT_SODIUM": "국과 찌개는 양을 줄여 건더기 위주로, 젓갈·장아찌·가공식품은 줄이고, 소금 대신 향신채로 풍미. 간은 약간 식은 뒤에 맞춤",
    "R_NUT_SODIUM_LOWEAT": "배식량은 그대로 두고 조리 단계에서 염도를 낮춤(한 메뉴에 간 집중, 향신채 활용)",
    "R_NUT_MEAL_GAP": "적게 드시는 끼니 뒤에 간식을 더하고, 그 끼니엔 좋아하는 메뉴",
    "R_DX_DIABETES": "식사·간식 시간을 일정하게, 단 음식 대신 단백질 간식",
    "R_DX_HTN": "국물·절임 반찬을 줄이고 저염 조리",
    "R_DX_HTN_LOWEAT": "배식량은 유지하고 조리 염도만 낮춤",
    "R_DX_DEMENTIA": "익숙한 식기, 한 가지씩, 손으로 집는 메뉴",
    "R_DX_KIDNEY": "의료진 확인 전에는 칼륨 많은 과일·채소나 단백질을 늘리지 않음",
    "R_DX_ANEMIA": "살코기·달걀·두부·시금치 반찬, 철분 반찬은 비타민 C 과일과 함께, 식사 직후 차·커피는 피함",
    "R_DX_OSTEO": "우유·멸치·두부와 등푸른생선·달걀·표고",
    "R_DX_CONSTIPATION": "나물·고구마·잡곡과 충분한 물",
    "R_LEFT_SOUP": "국은 양을 줄여 건더기 위주로 따뜻하게, 좋아하는 국으로 교체",
    "R_LEFT_SIDE": "남기는 반찬은 좋아하는 반찬으로 교체, 질감은 부드럽게",
    "R_LEFT_RICE": "밥 양을 줄이고 간식을 더하거나, 죽·누룽지로 바꿔 제공",
    "R_LEFT_KIMCHI": "배추김치 대신 백김치·물김치·나물무침·생채소",
}
NON_MEAL_RULES = {"R_REASSESS", "R_MAINTAIN", "R_DX_KIDNEY"}   # 식사로 해결하는 조치가 아닌 규칙 (구체성·식사 해결 검사에서 예외)
