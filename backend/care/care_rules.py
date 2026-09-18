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
    dict(id="R_NUT_SODIUM", category="영양(섭취량)",
         when=lambda f, c: _above(c, "na", 130),
         staff="나트륨 섭취가 기준보다 높아 국·찌개 국물 제공량과 김치·젓갈류 반찬 배식량을 영양사와 조정합니다. 고혈압·신장 관련 지병이 있으면 의료진과 상의합니다.",
         meal="국은 건더기 위주로 담고 국물 양을 줄입니다. 절임·젓갈 반찬은 소량만 제공합니다.",
         monitor="혈압을 주 1회 측정하고 부종 여부를 관찰합니다.",
         guardian="짠 음식이 많지 않도록 국물 양과 절임 반찬을 조절해 드리고 있습니다."),
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
         when=lambda f, c: (_flag(f, "dx_hypertension") or _dx(f, "고혈압")) and not _below(c, "na", 80),
         staff="고혈압이 있어 국물·절임 반찬 배식량을 조절하고 혈압 기록을 유지합니다.",
         meal="국은 건더기 위주로 담고 국물은 적게, 김치·젓갈류는 소량만 제공합니다.",
         monitor="혈압을 주 1회 측정하고 부종 여부를 확인합니다.",
         guardian="혈압 관리를 위해 국물과 짠 반찬 양을 조절해 드리고 있습니다."),
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
