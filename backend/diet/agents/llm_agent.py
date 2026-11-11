# -*- coding: utf-8 -*-
"""[Stage 1 + RAG] LLM 영역 전문가 — 규칙 선별 결과를 임상 근거 문단과 함께 보고 판단을 정제

  NutriOrion Stage 1(병렬 독립 평가)의 '전문가 에이전트'에 해당. 영역마다 독립적으로 실행된다.
    ① 규칙 선별(domain.py)   — 문제 목록·영양 기준·피할 식재료 (숫자는 guideline_rules.json)
    ② 근거 검색(rag.py)      — 그 영역 문헌에서만: 문제·기준에 연결된 조항 + 의미 검색
    ③ LLM 판단(여기)         — 그 영역 맥락(CONTEXT_KEYS)과 ①②만 보고
                               · 문제마다 판단 근거를 [E1] 인용과 함께 1~2문장
                               · 이 어르신에 맞게 심각도·시급성·개선 가능성 조정 (규칙 점수 ±0.2 안에서만)
                               · 근거와 맞지 않는 기준·판단은 '우려'로, 판단에 부족한 정보는 '추가 확인'으로
                               · 영역 요약 1~2문장
    ④ 코드 검증              — 없는 문제·범위 밖 점수·안전성(Level 1) 점수 변경·없는 근거 번호·입력에 없는 숫자를 걸러냄
                               기준 숫자와 피할 식재료는 바꾸지 않는다 (그건 Stage 2·3 와 규칙표의 몫)
  실패하면 규칙 결과를 그대로 쓴다. 이름·ID 는 보내지 않는다 (sub 맥락에는 원래 없음).

  켜기: run_design(..., agent_mode="llm")  /  화면 'AI 영역 전문가(근거 검색)'
"""
from __future__ import annotations

import hashlib
import json
import time

from .. import llm_select as LS
from . import rag
from .base import LEVEL_LABEL

PROMPT_VERSION = "2026-11-10-agent1"
DELTA = 0.2                      # 규칙 점수에서 움직일 수 있는 폭
_CACHE: dict = {}

SYSTEM_PROMPT = """당신은 요양원 어르신 영양 평가의 '{label}' 영역 전문가입니다. 이 영역의 정보만 보고 독립적으로 판단합니다.
입력: 이 영역의 어르신 정보, 규칙 기반 선별 결과(문제·기준), 그리고 근거 문단 [E1], [E2] … 가 주어집니다.

할 일:
1. 각 문제(code)마다 판단 근거를 1~2문장으로 씁니다. 근거 문단을 [E번호]로 반드시 인용합니다. 근거 문단에 없는 내용은 근거처럼 쓰지 않습니다.
2. 이 어르신 정보에 맞게 심각도(severity)·시급성(urgency)·개선 가능성(modifiability)을 0~1로 다시 매깁니다.
   규칙 점수에서 ±0.2 안에서만 움직입니다. level 1(안전성) 문제는 점수를 바꾸지 않고 근거만 씁니다.
3. 규칙의 기준값이나 판단이 근거 문단과 맞지 않아 보이면 concerns 에 씁니다(숫자를 바꾸지는 않습니다).
4. 판단에 필요한데 입력에 없는 정보(예: 신장 기능 검사, 체중 변화)는 missing 에 씁니다.
5. 이 영역 요약을 1~2문장으로 씁니다(인용 포함).

규칙:
- 숫자는 입력에 있는 값만 씁니다. 약 용량·처방·진단을 새로 만들지 않습니다.
- 새 문제를 만들지 않습니다. 입력에 있는 code 만 씁니다.
- 반드시 아래 JSON 한 개만 출력합니다.

{{"summary": "영역 요약 [E1]",
 "issues": [{{"code": "문제 code", "severity": 0.0, "urgency": 0.0, "modifiability": 0.0, "rationale": "판단 근거 [E2]"}}],
 "concerns": ["근거와 맞지 않는 점 [E3]"],
 "missing": ["추가로 확인할 정보"]}}"""


def _payload(agent, sub: dict, a, ev: dict) -> dict:
    return {
        "영역": a.label,
        "어르신_정보": {k: v for k, v in sub.items() if v not in (None, "", [], {})},
        "규칙_선별": {
            "요약": a.summary,
            "문제": [{"code": i.code, "title": i.title, "level": i.level, "level_label": LEVEL_LABEL[i.level],
                    "severity": i.severity, "urgency": i.urgency, "modifiability": i.modifiability,
                    "조치": i.action, "판단_값": i.evidence} for i in a.issues],
            "기준": [{"영양소": c.nutrient, "구분": "상한" if c.bound == "max" else "하한",
                    "값": c.value, "단위": "열량 비율" if c.unit == "pctE" else "끼니 절대량", "근거_문헌": c.source}
                   for c in a.constraints],
            "피할_식재료": [x.reason for x in a.avoid],
        },
        "근거": ev["snippets"],
    }


def _key(payload: dict) -> str:
    p = LS.provider()
    m = LS._model(p) if p in ("openai", "anthropic") else ""
    raw = json.dumps([payload, m, LS.effort(m) if m else None, PROMPT_VERSION], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()


def validate(raw: dict, a, ev: dict, payload: dict) -> tuple[dict, list]:
    """LLM 응답 → (정리된 판단, 경고). 점수는 규칙 ±DELTA, 안전성은 규칙 그대로, 인용은 실제 근거 번호만"""
    warn, snippets = [], ev["snippets"]
    issues = {i.code: i for i in a.issues}
    out = {"summary": "", "issues": {}, "concerns": [], "missing": []}
    s, _ = rag.valid_citations(LS._clean(raw.get("summary"), 400), snippets)
    out["summary"] = s
    for x in raw.get("issues") or []:
        if not isinstance(x, dict):
            continue
        code = str(x.get("code") or "")
        i = issues.get(code)
        if not i:
            warn.append(f"없는 문제 무시: {code}")
            continue
        rat, used = rag.valid_citations(LS._clean(x.get("rationale"), 360), snippets)
        if not used:
            warn.append(f"{code}: 근거 인용 없음")
        new = {}
        for k in ("severity", "urgency", "modifiability"):
            base = getattr(i, k)
            try:
                v = float(x.get(k, base))
            except (TypeError, ValueError):
                v = base
            if i.level == 1:
                if abs(v - base) > 1e-6:
                    warn.append(f"{code}: 안전성(Level 1) 점수는 바꾸지 않음")
                v = base
            lo, hi = max(0.0, base - DELTA), min(1.0, base + DELTA)
            if v < lo or v > hi:
                warn.append(f"{code}.{k} {v} → 허용 범위 [{lo:.2f}, {hi:.2f}]로 맞춤")
                v = min(hi, max(lo, v))
            new[k] = round(v, 2)
        out["issues"][code] = {**new, "rationale": rat, "cites": used}
    for k, lim in (("concerns", 4), ("missing", 4)):
        for t in (raw.get(k) or [])[:lim]:
            txt, _ = rag.valid_citations(LS._clean(t, 240), snippets)
            if txt:
                out[k].append(txt)
    text = " ".join([out["summary"]] + [v["rationale"] for v in out["issues"].values()] + out["concerns"])
    bad = LS.unknown_numbers({"reasons": [text], "tradeoffs": "", "summary": ""}, payload)
    if bad:
        warn.append(f"입력에 없는 숫자: {bad[:5]}")
    return out, warn


def apply(a, res: dict):
    """검증된 판단을 Assessment 에 반영 (규칙 점수는 scores_rule 에 보존)"""
    for i in a.issues:
        r = res["issues"].get(i.code)
        if not r:
            continue
        i.scores_rule = {"severity": i.severity, "urgency": i.urgency, "modifiability": i.modifiability,
                         "priority": i.priority}
        i.severity, i.urgency, i.modifiability = r["severity"], r["urgency"], r["modifiability"]
        i.rationale, i.cites = r["rationale"], r["cites"]


def gather(agent, sub: dict, a, ctx: dict | None = None) -> dict | None:
    """[근거 검색] 이 영역 문헌에서 근거 문단을 찾아 Assessment 에 붙인다. 근거가 없으면 None (규칙 결과 유지).
    LangGraph 경로에서는 <영역>_rag 노드 (agents/graph.py)"""
    t0 = time.time()
    try:
        ev = rag.evidence_for(a, ctx)
    except Exception as e:
        a.llm = {"mode": "rule", "note": f"근거 검색 실패 → 규칙 결과 사용: {str(e)[:160]}"}
        return None
    a.evidence = ev["refs"]
    if not ev["snippets"]:
        a.llm = {"mode": "rule", "note": "근거 문단을 찾지 못해 규칙 결과 사용" + (f" ({ev['error']})" if ev.get("error") else "")}
        return None
    return {**ev, "_t0": t0}


def decide(agent, sub: dict, a, ev: dict, caller=None) -> None:
    """[LLM 영역 전문가] 근거 문단을 보고 판단을 정제 → 코드 검증 → Assessment 에 반영. 예외를 밖으로 던지지 않는다.
    LangGraph 경로에서는 <영역>_expert 노드"""
    t0 = ev.get("_t0") or time.time()
    try:
        payload = _payload(agent, sub, a, ev)
        k = _key(payload)
        if k in _CACHE:
            res, warn, model = _CACHE[k]
            reused = True
        else:
            call = caller or (lambda p: LS.call_llm(p, system=SYSTEM_PROMPT.format(label=a.label), max_tokens=1400))
            raw, model = call(payload)
            res, warn = validate(raw, a, ev, payload)
            _CACHE[k] = (res, warn, model)
            reused = False
        apply(a, res)
        a.llm = {"mode": "llm", "model": model, "prompt_version": PROMPT_VERSION, "summary": res["summary"],
                 "concerns": res["concerns"], "missing": res["missing"], "warnings": warn, "reused": reused,
                 "rag_backend": ev["backend"], "latency_sec": round(time.time() - t0, 1)}
    except Exception as e:
        a.llm = {"mode": "rule", "note": f"AI 영역 판단 실패 → 규칙 결과 사용: {str(e)[:160]}"}


def judge(agent, sub: dict, a, ctx: dict | None = None, caller=None) -> None:
    """manager.assess_residents(judge=...) 훅 — 근거 검색(gather) + LLM 판단(decide)을 한 번에"""
    ev = gather(agent, sub, a, ctx)
    if ev is not None:
        decide(agent, sub, a, ev, caller)


def make_judge(caller=None):
    """LLM 이 설정돼 있지 않으면 None (규칙만). LangGraph 경로는 .caller 를 읽어 gather/decide 노드로 나눠 실행"""
    if caller is None and not LS.status().get("ready"):
        return None
    f = lambda ag, sub, a, ctx=None: judge(ag, sub, a, ctx, caller=caller)
    f.caller = caller
    return f
