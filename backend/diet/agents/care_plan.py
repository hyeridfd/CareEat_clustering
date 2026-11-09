# -*- coding: utf-8 -*-
"""[Stage 3] 어르신별 영양 관리 계획 (ADIME) — LLM 보고서 에이전트

  NutriOrion Stage 3 의 보고서 에이전트에 해당. 다만 NutriOrion 은 계획을 글로만 쓰지만,
  여기서는 시스템이 이미 실행한 조치(대체찬·배식량·식사형태·안전 확인)를 근거로 '무엇을 했고 무엇을 지켜볼지' 를 쓴다.
    A 평가  — 영역 평가·종합 판단 요약
    D 영양 진단 — 문제 · 원인 · 근거 (PES 형식), 우선순위 순
    I 중재  — 식단에서 실제로 한 조치와 연결 (대체찬 n건, 배식 조정, 식사형태)
    M 모니터링 — 다음 평가 때 볼 지표
  요청할 때만 만든다 (개인 배식표 화면의 버튼). 이름·ID 는 보내지 않는다.
"""
from __future__ import annotations

import time
from collections import Counter

from .. import llm_select as LS

PROMPT_VERSION = "2026-11-09-plan1"

SYSTEM_PROMPT = """당신은 요양원 임상 영양사입니다. 어르신 1명의 평가 결과와, 식단 설계 시스템이 이미 실행한 조치가 주어집니다.
이를 바탕으로 영양 관리 계획을 ADIME 형식으로 씁니다. 요양원 영양사·간호사가 읽습니다.

규칙:
- 영양 진단(diagnosis)은 우선순위가 높은 문제부터 최대 4개, 'P(문제) — E(원인) — S(근거)' 한 문장씩.
- 중재(intervention)는 시스템이 실제로 한 조치(대체찬, 배식량 조정, 식사형태, 피할 식재료 확인)와 연결해서 씁니다.
  시스템이 하지 않은 조치를 했다고 쓰지 않습니다. 추가로 권하는 것은 '권장:' 으로 시작합니다.
- 모니터링은 다음 평가 때 확인할 지표 3~5개 (체중, 섭취율, 혈압 등).
- 숫자는 입력에 있는 값만 씁니다. 약 이름·용량·처방·진단명을 새로 붙이지 않습니다.
- 반드시 아래 JSON 한 개만 출력합니다.

{"assessment": "평가 요약 2~3문장",
 "diagnosis": ["P — E — S"],
 "intervention": [{"goal": "목표", "action": "시스템이 한 조치 또는 '권장: …'"}],
 "monitoring": ["지표와 확인 주기"],
 "staff_summary": "담당자에게 한 문장"}"""


def build_payload(result: dict, eid: str) -> dict:
    """설계 결과(diet_runs.result) → 어르신 1명 입력 (이름·ID 제외)"""
    a = (result.get("assessments") or {}).get(eid) or {}
    syn = a.get("synth") or {}
    res = next((r for r in result.get("residents") or [] if r.get("elderly_id") == eid), {})
    subs = [s for s in result.get("substitutions") or [] if s.get("elderly_id") == eid]
    flags = [f for f in result.get("safety_flags") or [] if f.get("elderly_id") == eid]
    ref = a.get("refine") or {}
    srv = res.get("serving") or {}
    return {
        "어르신": {k: res.get(k) for k in ("type", "texture", "diseases", "age", "sex", "bmi", "no_spicy")},
        "영역_평가": [{"영역": g.get("label"), "요약": g.get("summary")} for g in a.get("agents") or [] if g.get("active")],
        "우선순위_문제": [{"문제": i.get("title"), "S": i.get("priority"), "조치_유형": i.get("action"),
                      "근거": i.get("evidence")} for i in (syn.get("priorities") or [])[:6]],
        "개인_영양기준(끼니)": {k: round(v.get("value"), 1) for k, v in (syn.get("constraints") or {}).items()
                           if v.get("value") is not None},
        "목표_열량(끼니)": syn.get("target_energy"),
        "임상영양사_종합판단": {"요약": ref.get("summary"), "충돌": ref.get("conflicts"),
                         "기준_조정": [f"{x['label']} {x['before']}→{x['after']}" for x in ref.get("adjustments") or []]}
        if ref.get("mode") == "llm" else None,
        "피할_식재료": [x.get("reason") for x in syn.get("avoid") or []],
        "시스템이_한_조치": {
            "대체찬_건수(28일)": len(subs),
            "대체찬_사유별": dict(res.get("reasons") or {}),
            "대체찬_예시": [f"{s['day']} {s['meal']} {s['slot']}: {s['orig']} → {s['product']} ({s['reason']})" for s in subs[:5]],
            "배식": {"끼니": srv.get("끼니"), "열량_기준_충족": srv.get("열량OK"), "단백질_기준_충족": srv.get("단백질OK"),
                   "나트륨_기준_충족": srv.get("나트륨OK"), "조정불가": srv.get("조정불가")},
            "식사형태": res.get("texture"),
            "안전_확인_필요_끼니": len(flags),
            "안전_확인_사유": dict(Counter(f.get("reason") for f in flags)),
        },
    }


def generate(result: dict, eid: str, caller=None) -> dict:
    payload = build_payload(result, eid)
    t0 = time.time()
    call = caller or (lambda p: LS.call_llm(p, system=SYSTEM_PROMPT, max_tokens=1800))
    raw, model = call(payload)
    plan = {
        "assessment": LS._clean(raw.get("assessment"), 500),
        "diagnosis": [LS._clean(x, 220) for x in raw.get("diagnosis") or [] if str(x).strip()][:4],
        "intervention": [{"goal": LS._clean(x.get("goal"), 120), "action": LS._clean(x.get("action"), 240)}
                         for x in raw.get("intervention") or [] if isinstance(x, dict)][:6],
        "monitoring": [LS._clean(x, 160) for x in raw.get("monitoring") or [] if str(x).strip()][:5],
        "staff_summary": LS._clean(raw.get("staff_summary"), 200),
    }
    text = " ".join([plan["assessment"], plan["staff_summary"]] + plan["diagnosis"] + plan["monitoring"]
                    + [x["action"] for x in plan["intervention"]])
    bad = LS.unknown_numbers({"reasons": [text], "tradeoffs": "", "summary": ""}, payload)
    return {**plan, "model": model, "prompt_version": PROMPT_VERSION, "latency_sec": round(time.time() - t0, 1),
            "warnings": [f"입력에 없는 숫자: {bad[:5]}"] if bad else [],
            "created_at": time.strftime("%Y-%m-%d %H:%M")}
