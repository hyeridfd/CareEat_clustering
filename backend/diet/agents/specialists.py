# -*- coding: utf-8 -*-
"""[3단계 · 조건부] 질환 전문가 정제 — 영역끼리 '충돌'이 있을 때만, 그 충돌 하나만 맡는 LLM 전문가

  NutriOrion Stage 2(질환별 전문가 정제)를 '충돌이 확인된 곳에만' 쓰는 방식.
    ① 충돌 찾기(detect)   — guideline_rules.json 의 conflicts 표 (예: 저체중·영양불량 ↔ 당뇨 당류 제한)
                            문제 code · 기준 이름 · 질환명으로만 판단 (LLM 없음, 항상 같은 결과)
    ② 근거 찾기           — 충돌 표에 연결된 지침 조항 + 관련 영역 문헌을 합친 범위에서 의미 검색 (rag.retrieve)
    ③ 전문가 판단(judge)  — 그 충돌에 걸린 문제·기준·근거만 보고
                            · 해결 방향 1~2문장 ([E#] 인용 필수)
                            · 충돌 표의 fields 기준만, 1단계 값 × 허용 배율(refine.BANDS) 안, 잠금(lock) 방향 안에서 조정
                            · 관련 Level 2 문제의 점수를 현재 값 ±0.2 (1단계 값 ±0.3 넘지 않게) 안에서 조정
                            · 판단에 부족한 정보는 missing
    ④ 코드 검증           — 범위·잠금 밖 값, 없는 기준·문제, Level 1 점수 변경, 없는 근거 번호, 입력에 없는 숫자를 걸러냄
  실패하거나 LLM 이 없으면 규칙 조정(conflicts.rule)만 남는다. 이름·ID 는 보내지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import time

from .. import llm_select as LS
from . import rag
from .base import LEVEL_LABEL, W_MOD, W_SEV, W_URG

PROMPT_VERSION = "2026-11-10-spec1"
DELTA = 0.2
_CACHE: dict = {}

SYSTEM_PROMPT = """당신은 요양원 어르신 영양 관리의 '{label}'입니다. 한 어르신에게서 확인된 영역 간 충돌 하나만 맡습니다.
충돌: {title}
입력: 이 충돌에 걸린 문제(code·점수), 현재 개인 영양 기준과 조정 허용 범위, 규칙이 이미 정한 해결, 근거 문단 [E1], [E2] … 가 주어집니다.

할 일:
1. 근거 문단을 보고 이 충돌을 어떻게 풀지 1~2문장으로 씁니다. [E번호]로 반드시 인용합니다.
2. 꼭 필요하면 '조정_허용범위'에 있는 기준만, 그 범위 안의 값으로 조정합니다. 필요 없으면 빈 목록.
3. 충돌에 걸린 Level 2(영양 중재) 문제의 심각도·시급성·개선 가능성(0~1)을 현재 값 ±0.2 안에서 다시 매깁니다. 바꿀 것만 적습니다.
   Level 1(안전성) 문제는 점수를 바꾸지 않습니다.
4. 판단에 필요한데 입력에 없는 정보는 missing 에 씁니다.

규칙:
- 입력에 있는 code·기준 이름만 씁니다. 숫자는 입력에 있는 값만 씁니다. 약 이름·용량·처방·진단을 새로 만들지 않습니다.
- 반드시 아래 JSON 한 개만 출력합니다.

{{"resolution": "해결 방향 [E1]",
 "adjustments": [{{"field": "protein_min", "value": 25, "reason": "이유 [E2]"}}],
 "rescore": [{{"code": "문제 code", "severity": 0.0, "urgency": 0.0, "modifiability": 0.0, "reason": "이유"}}],
 "missing": ["추가로 확인할 정보"]}}"""


# ─────────────────────────── ① 충돌 찾기 ───────────────────────────
def _hit(token: str, codes: set, fields: set, diseases: list) -> bool:
    kind, _, val = token.partition(":")
    if kind == "issue":
        return val in codes
    if kind == "field":
        return val in fields
    if kind == "disease":
        return any(val in d for d in diseases)
    return False


def match_when(when: list, codes: set, fields: set, diseases: list) -> list | None:
    """묶음마다 맞은 표시 목록, 하나라도 비면 None"""
    got = []
    for g in when or []:
        m = [t for t in g if _hit(t, codes, fields, diseases)]
        if not m:
            return None
        got.append(m)
    return got


def detect(syn: dict, ctx: dict) -> list[dict]:
    """종합 결과(synth) + 어르신 맥락 → [{id, title, matched, …충돌 표 항목}]"""
    from .domain import rules
    codes = {p.get("code") for p in syn.get("priorities") or []}
    fields = set((syn.get("constraints") or {}).keys())
    diseases = [str(x) for x in (ctx.get("diseases") or [])]
    out = []
    for cid, c in (rules().get("conflicts") or {}).items():
        if cid.startswith("_"):
            continue
        m = match_when(c.get("when"), codes, fields, diseases)
        if m is not None:
            out.append({"id": cid, **c, "matched": m})
    return out


# ─────────────────────────── ③ 전문가 판단 ───────────────────────────
def _r(v, n=1):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def allowed_ranges(conf: dict, syn: dict, base: dict) -> dict:
    """충돌의 fields → {field: [lo, hi]}. 1단계 값 × BANDS, 잠금(lock) 방향, 현재 기준에 있는 것만"""
    from .refine import BANDS
    lock = (conf.get("rule") or {}).get("lock") or {}
    bc = (base or {}).get("constraints") or {}
    out = {}
    for f in conf.get("fields") or []:
        cur = (syn.get("constraints") or {}).get(f)
        b = (bc.get(f) or cur or {}).get("value")
        if not cur or not b or f not in BANDS:
            continue
        lo, hi = b * BANDS[f][0], b * BANDS[f][1]
        te = syn.get("target_energy")                 # 목표 열량이 열량 범위 밖으로 나가지 않게
        if te and f == "energy_min":
            hi = min(hi, te)
        if te and f == "energy_max":
            lo = max(lo, te)
        if lock.get(f) == "keep_or_raise":
            lo = max(lo, b)
        elif lock.get(f) == "keep_or_lower":
            hi = min(hi, b)
        if hi - lo > 1e-6:
            out[f] = [_r(lo, 2), _r(hi, 2)]
    return out


def _issues_of(conf: dict, syn: dict) -> list[dict]:
    want = {t.partition(":")[2] for g in conf.get("matched") or [] for t in g if t.startswith("issue:")}
    return [p for p in syn.get("priorities") or [] if p.get("code") in want]


def build_payload(conf: dict, syn: dict, base: dict, ctx: dict, ev: dict) -> dict:
    from .refine import FIELD_KO, _age_band
    ranges = allowed_ranges(conf, syn, base)
    return {
        "충돌": conf["title"],
        "어르신": {"나이": _age_band(ctx.get("age")), "성별": "여" if ctx.get("female") else "남", "BMI": ctx.get("bmi"),
                "질환": ctx.get("diseases") or [], "식사형태": ctx.get("meal_form"), "전체_섭취율": ctx.get("intake_rate")},
        "관련_문제": [{"code": p["code"], "title": p.get("title"), "level": p.get("level"),
                   "level_label": LEVEL_LABEL.get(p.get("level") or 2), "severity": p.get("severity"),
                   "urgency": p.get("urgency"), "modifiability": p.get("modifiability"), "근거_값": p.get("evidence")}
                  for p in _issues_of(conf, syn)],
        "현재_기준(끼니)": {f: _r(syn["constraints"][f]["value"]) for f in ranges},
        "조정_허용범위": ranges,
        "기준_이름": {f: FIELD_KO.get(f, f) for f in ranges},
        "규칙이_정한_해결": (conf.get("rule") or {}).get("text"),
        "근거": ev["snippets"],
    }


def _key(payload: dict) -> str:
    p = LS.provider()
    m = LS._model(p) if p in ("openai", "anthropic") else ""
    raw = json.dumps([payload, m, LS.effort(m) if m else None, PROMPT_VERSION], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()


def validate(raw: dict, payload: dict, conf: dict, syn: dict, base: dict) -> dict:
    snippets, ranges = payload["근거"], payload["조정_허용범위"]
    warn = []
    res, used = rag.valid_citations(LS._clean(raw.get("resolution"), 360), snippets)
    if not used:
        warn.append("해결 방향에 근거 인용 없음")
    adj, seen = [], set()
    for x in raw.get("adjustments") or []:
        if not isinstance(x, dict):
            continue
        f = str(x.get("field") or "").strip()
        if f not in ranges or f in seen:
            if f:
                warn.append(f"이 충돌에서 조정할 수 없는 기준 무시: {f}")
            continue
        try:
            v = float(x.get("value"))
        except (TypeError, ValueError):
            warn.append(f"값 형식 오류: {f}")
            continue
        lo, hi = ranges[f]
        after = min(max(v, lo), hi)
        before = syn["constraints"][f]["value"]
        if abs(after - before) < 1e-6:
            continue
        seen.add(f)
        reason, c2 = rag.valid_citations(LS._clean(x.get("reason"), 200), snippets)
        adj.append({"field": f, "label": payload["기준_이름"].get(f, f), "before": _r(before), "proposed": _r(v),
                    "after": _r(after, 2), "clamped": abs(after - v) > 1e-6, "reason": reason, "cites": c2})
    vals = {k: v["value"] for k, v in syn["constraints"].items()} | {a["field"]: a["after"] for a in adj}
    for lo_k, hi_k in (("energy_min", "energy_max"), ("protein_min", "protein_max"), ("fat_min", "fat_max")):
        if vals.get(lo_k) and vals.get(hi_k) and vals[lo_k] > vals[hi_k]:
            adj = [a for a in adj if a["field"] not in (lo_k, hi_k)]
            warn.append(f"{lo_k} > {hi_k} 가 되어 조정을 취소")
    issues = {p["code"]: p for p in _issues_of(conf, syn)}
    stage1 = {p["code"]: p for p in (base or {}).get("priorities") or []}
    rescore = []
    for x in raw.get("rescore") or []:
        if not isinstance(x, dict):
            continue
        code = str(x.get("code") or "")
        p = issues.get(code)
        if not p:
            warn.append(f"이 충돌과 관계없는 문제 무시: {code}")
            continue
        if (p.get("level") or 2) == 1:
            warn.append(f"안전성(Level 1) 점수는 바꾸지 않음: {code}")
            continue
        new = {}
        for k in ("severity", "urgency", "modifiability"):
            old = float(p.get(k) or 0)
            s1 = float((stage1.get(code) or p).get(k) or old)
            try:
                v = float(x.get(k, old))
            except (TypeError, ValueError):
                v = old
            lo, hi = max(0.0, old - DELTA, s1 - 0.3), min(1.0, old + DELTA, s1 + 0.3)
            if v < lo - 1e-9 or v > hi + 1e-9:
                warn.append(f"{code}.{k} {v} → 허용 범위 [{lo:.2f}, {hi:.2f}]로 맞춤")
            new[k] = round(min(max(v, lo), hi), 3)
        if all(abs(new[k] - float(p.get(k) or 0)) < 1e-6 for k in new):
            continue
        rescore.append({"code": code, "title": p.get("title"), "before": {k: p.get(k) for k in new} | {"priority": p.get("priority")},
                        "after": new | {"priority": round(W_SEV * new["severity"] + W_URG * new["urgency"] + W_MOD * new["modifiability"], 3)},
                        "reason": LS._clean(x.get("reason"), 200)})
    missing = [LS._clean(t, 160) for t in (raw.get("missing") or [])[:3] if str(t).strip()]
    text = " ".join([res] + [a["reason"] for a in adj] + [r["reason"] for r in rescore])
    bad = LS.unknown_numbers({"reasons": [text], "tradeoffs": "", "summary": ""}, payload)
    if bad:
        warn.append(f"입력에 없는 숫자: {bad[:5]}")
    return {"resolution": res, "cites": used, "adjustments": adj, "rescore": rescore, "missing": missing, "warnings": warn}


def judge(conf: dict, syn: dict, base: dict, ctx: dict, caller=None) -> dict:
    """충돌 1건 → 전문가 판단 기록 (예외를 던지지 않음). syn 은 바꾸지 않는다 (synthesis.py 가 적용)"""
    t0 = time.time()
    try:
        srcs = sorted({s for ag in conf.get("agents") or [] for s in rag.AGENT_SOURCES.get(ag, [])})
        queries = [conf["title"]] + [p.get("title") or p["code"] for p in _issues_of(conf, syn)][:3]
        ev = rag.retrieve([tuple(x) for x in conf.get("links") or []], queries, srcs, ctx, max_linked=3, max_search=2)
        if not ev["snippets"]:
            return {"mode": "rule", "note": "근거 문단을 찾지 못해 규칙 조정만 사용" + (f" ({ev['error']})" if ev.get("error") else "")}
        payload = build_payload(conf, syn, base, ctx, ev)
        k = _key(payload)
        if k in _CACHE:
            out, model, reused = *_CACHE[k], True
        else:
            system = SYSTEM_PROMPT.format(label=conf.get("specialist") or "전문 영양사", title=conf["title"])
            call = caller or (lambda p: LS.call_llm(p, system=system, max_tokens=1000))
            raw, model = call(payload)
            out = validate(raw, payload, conf, syn, base)
            _CACHE[k] = (out, model)
            reused = False
        return {"mode": "llm", "model": model, "prompt_version": PROMPT_VERSION, "specialist": conf.get("specialist"),
                **out, "evidence": ev["refs"], "rag_backend": ev["backend"], "reused": reused,
                "latency_sec": round(time.time() - t0, 1)}
    except Exception as e:
        return {"mode": "rule", "note": f"전문가 판단 실패 → 규칙 조정만 사용: {str(e)[:160]}"}
