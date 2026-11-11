# -*- coding: utf-8 -*-
"""[3단계] 종합·안전성 검증 — 고정된 순서로 최종 개인 기준과 우선순위를 정한다

  NutriOrion Stage 3(Synthesis & Safety Verification)에 해당. 순서는 바뀌지 않는다:
    1) 안전성      Level 1 문제(알레르기·연하·약물 상호작용·저혈당)와 피할 식재료를 먼저 확정 — 점수와 무관하게 최우선
    2) 우선순위    Level 2 를 파레토 묶음(심각도·시급성·개선 가능성) → S 순으로 정렬 (base.rank_priorities)
    3) 지침 충돌   conflicts 표로 영역 간 충돌을 찾아
                   · 규칙 조정(잠금 lock · 점수 증감 rescore)은 항상
                   · AI 임상 영양사를 켜면 충돌마다 질환 전문가(specialists.py)가 근거를 보고 허용 범위 안에서 조정
                   · 잠금은 전문가 조정 뒤에 다시 적용 (전문가도 잠금을 넘지 못함)
    4) 약물·질환 강제 제약  hard_overrides 표 — 앞 단계가 무엇을 정했든 마지막에 적용
                   예) 칼륨 보존 이뇨제 → 칼륨 하한 삭제 · 당뇨약+섭취 저하 → 열량 하한을 1단계보다 낮추지 않음
  모든 변경은 synth["synthesis"] 에 단계별로 남긴다 (화면 '종합 단계' · ADIME '추가 확인 정보').
  base = 2단계(AI 임상 영양사) 전 1단계 종합 — 잠금·허용 범위의 기준점.
"""
from __future__ import annotations

import json

from .base import LEVEL_LABEL, W_MOD, W_SEV, W_URG, rank_priorities
from .specialists import detect, judge, match_when

STEP_NAMES = ["안전성 확인", "우선순위 (파레토 → S)", "지침 충돌 조정", "약물·질환 강제 제약"]


def _r(v, n=1):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def _prio(p: dict) -> float:
    return round(W_SEV * float(p.get("severity") or 0) + W_URG * float(p.get("urgency") or 0)
                 + W_MOD * float(p.get("modifiability") or 0), 3)


def _set_scores(p: dict, new: dict, tag: str):
    p.setdefault("scores_before_synthesis", {k: p.get(k) for k in ("severity", "urgency", "modifiability", "priority")})
    for k in ("severity", "urgency", "modifiability"):
        if k in new:
            p[k] = round(max(0.0, min(1.0, float(new[k]))), 3)
    p["priority"] = _prio(p)
    p.setdefault("adjusted_by", [])
    if tag not in p["adjusted_by"]:
        p["adjusted_by"].append(tag)


def _lock(syn: dict, base: dict, field: str, mode: str, tag: str) -> dict | None:
    c = syn["constraints"].get(field)
    b = ((base or {}).get("constraints") or {}).get(field)
    if not c or not b:
        return None
    v, bv = c["value"], b["value"]
    if (mode == "keep_or_raise" and v < bv - 1e-6) or (mode == "keep_or_lower" and v > bv + 1e-6):
        c["value"] = bv
        c["locked_by"] = tag
        return {"field": field, "before": _r(v), "after": _r(bv), "mode": mode}
    return None


def _ranking_text(prios: list) -> list[str]:
    out, l1 = [], [p for p in prios if (p.get("level") or 2) == 1]
    if l1:
        out.append("Level 1 안전성: " + ", ".join(p.get("title", p["code"]).split(" — ")[0] for p in l1))
    fronts = {}
    for p in prios:
        if (p.get("level") or 2) == 2:
            fronts.setdefault(p.get("pareto_rank") or 1, []).append(p)
    for f in sorted(fronts):
        out.append(f"Level 2 · {f}묶음: " + ", ".join(f"{p.get('title', p['code']).split(' — ')[0]}(S {p.get('priority')})"
                                                   for p in fronts[f]))
    return out


# AI 가 낸 '추가 확인' 문장을 주제로 묶는다 (영역마다 표현만 다른 같은 요청이 많음: 실제 결과 109건 중 상당수가 체중·신장 기능)
#   영역별 원문은 각 영역 카드(llm.missing)에 그대로 남는다
CONFIRM_TOPICS = [
    ("신장 기능(eGFR)·혈중 칼륨", r"신장|콩팥|사구체|eGFR|신기능|혈중 칼륨|칼륨 수치"),
    ("체중·최근 체중 변화", r"체중"),
    ("혈당·저혈당 이력", r"혈당"),
    ("삼킴·씹기 평가와 식사형태·음료 점도", r"삼킴|씹기|저작|점도|식사형태|음식 형태"),
    ("반복 측정 혈압", r"혈압의 반복|반복 측정|혈압 측정|혈압 추이|최근 혈압"),
    ("약의 정확한 종류·복용 시간", r"약의|약물|제품명|성분명|복용 (시간|시각|현황|여부)"),
    ("실제 끼니별 섭취량 기록", r"섭취량|섭취 기록|식사 기록|식사량"),
    ("근육량·근력·신체 기능", r"근육|근력|근기능|SARC|종아리|신체 기능|보행"),
]


def _ai_missing(items: list, system: list | None = None) -> list[str]:
    """[(영역 이름, 문장)] → 주제별 한 줄 (많이 나온 주제 먼저) + 주제에 안 맞는 문장. 시스템 확인 항목과 같은 주제는 뺌"""
    import re
    covered = {name for name, pat in CONFIRM_TOPICS for x in system or [] if re.search(pat, x)}
    topics, rest = {}, {}
    for lab, m in items:
        t = next((name for name, pat in CONFIRM_TOPICS if re.search(pat, m)), None)
        (topics.setdefault(t, []) if t else rest.setdefault(m.strip(), [])).append(lab)
    out = [f"[{' · '.join(dict.fromkeys(v))}] {k}" for k, v in sorted(topics.items(), key=lambda kv: -len(kv[1])) if k not in covered]
    return out + [f"[{' · '.join(dict.fromkeys(v))}] {k}" for k, v in rest.items()]


def _data_gaps(ctx: dict) -> list[str]:
    out = []
    if not ctx.get("weight_kg"):
        out.append("[신체] 체중 (단백질 필요량·BMI 계산)")
    if ctx.get("intake_rate") is None and not ctx.get("avg_day"):
        out.append("[섭취] 조사 기간 섭취 기록")
    if any("고혈압" in str(d) for d in ctx.get("diseases") or []) and not (ctx.get("sbp") or ctx.get("dbp")):
        out.append("[고혈압] 최근 혈압")
    return out


def _agent_missing(agents: list) -> list:
    out = []
    for a in agents or []:
        a = a if isinstance(a, dict) else a.to_dict()
        if a.get("active"):
            out += [(a.get("label"), m) for m in ((a.get("llm") or {}).get("missing") or [])]
    return out


MAX_CONFIRM = 8


# ── [2026-11-11] 단계 함수 — LangGraph 노드(agents/graph.py)와 finalize() 가 같은 함수를 쓴다 ──
#   w = 작업 상태 {"syn", "base", "steps", "order0", "conflicts", "pending"} (단계마다 이어 받음)
def s3_start(syn: dict, base: dict | None = None) -> dict:
    syn = json.loads(json.dumps(syn, default=str))
    base = base or json.loads(json.dumps(syn, default=str))
    return {"syn": syn, "base": base, "steps": [{"step": i + 1, "name": n, "items": []} for i, n in enumerate(STEP_NAMES)],
            "order0": [], "conflicts": [], "pending": []}


def _log(w, k, t):
    w["steps"][k - 1]["items"].append(t)


def _by_code(w):
    return {p["code"]: p for p in w["syn"]["priorities"]}


def s3_safety(w: dict) -> dict:
    """1) 안전성 — Level 1 문제와 피할 식재료를 점수와 무관하게 먼저 확정"""
    syn = w["syn"]
    for p in syn.get("priorities") or []:
        if (p.get("level") or 2) == 1:
            _log(w, 1, f"{p.get('title')} — {LEVEL_LABEL[1]} 최우선")
    for a in syn.get("avoid") or []:
        if a.get("hard"):
            kw = ", ".join(a.get("keywords") or [])[:60]
            _log(w, 1, f"피할 식재료 확정: {a.get('reason')} ({kw}" + (f" · {a['min_g']:.0f} g 이상" if a.get("min_g") else "") + ")")
    if not w["steps"][0]["items"]:
        _log(w, 1, "안전성 문제 없음")
    return w


def s3_rank(w: dict) -> dict:
    """2) 우선순위 — Level 2 를 파레토 묶음 → S 순"""
    syn = w["syn"]
    syn["priorities"] = prios = rank_priorities(syn.get("priorities") or [])
    w["order0"] = [p["code"] for p in prios]
    for t in _ranking_text(prios):
        _log(w, 2, t)
    return w


def s3_detect(w: dict, ctx: dict) -> dict:
    """3-a) 충돌 찾기 + 규칙 점수 증감 (LLM 없음)"""
    syn = w["syn"]
    for conf in detect(syn, ctx):
        rule = conf.get("rule") or {}
        rec = {"id": conf["id"], "title": conf["title"], "agents": conf.get("agents"), "matched": conf["matched"],
               "rule_text": rule.get("text"), "source": conf.get("source"), "section": conf.get("section"),
               "locks": [], "rule_rescore": [], "specialist": None, "confirm": list(rule.get("confirm") or [])}
        rs = rule.get("rescore") or {}
        for code in rs.get("codes") or []:
            p = _by_code(w).get(code)
            if not p or (p.get("level") or 2) == 1:
                continue
            before = p.get("priority")
            _set_scores(p, {k: float(p.get(k) or 0) + float(rs[k]) for k in ("severity", "urgency", "modifiability") if k in rs},
                        f"충돌:{conf['id']}")
            rec["rule_rescore"].append({"code": code, "title": p.get("title"), "before": before, "after": p["priority"]})
        w["conflicts"].append(rec)
        w["pending"].append(conf)
    return w


def needs_specialist(w: dict, use_specialists: bool) -> bool:
    return bool(use_specialists) and any(c.get("llm") and c.get("fields") for c in w["pending"])


def s3_specialists(w: dict, ctx: dict, caller=None) -> dict:
    """3-b) 충돌마다 질환 전문가 LLM (AI 임상 영양사를 켰을 때) — 허용 범위 안의 조정만"""
    syn, base = w["syn"], w["base"]
    for conf, rec in zip(w["pending"], w["conflicts"]):
        if not (conf.get("llm") and conf.get("fields")):
            continue
        sp = judge(conf, syn, base, ctx, caller=caller)
        rec["specialist"] = sp
        if sp.get("mode") == "llm":
            for a in sp.get("adjustments") or []:
                c = syn["constraints"][a["field"]]
                c.setdefault("specialist_from", c["value"])
                c["value"] = a["after"]
                c["agent"] = f"specialist:{conf['id']}"
            for x in sp.get("rescore") or []:
                p = _by_code(w).get(x["code"])
                if p:
                    _set_scores(p, x["after"], f"전문가:{conf['id']}")
    return w


def s3_locks(w: dict) -> dict:
    """3-c) 충돌 잠금 — 전문가 조정 뒤에 적용 (넘지 못하게) + 단계 기록"""
    syn, base = w["syn"], w["base"]
    for conf, rec in zip(w["pending"], w["conflicts"]):
        rule = conf.get("rule") or {}
        for f, mode in (rule.get("lock") or {}).items():
            ch = _lock(syn, base, f, mode, f"충돌:{conf['id']}")
            rec["locks"].append({"field": f, "mode": mode, **({"restored": ch} if ch else {})})
        txt = f"{conf['title']} → {rule.get('text')}"
        if rec["rule_rescore"]:
            txt += " · 점수 " + ", ".join(f"{x['code']} {x['before']}→{x['after']}" for x in rec["rule_rescore"])
        sp = rec["specialist"] or {}
        if sp.get("mode") == "llm":
            txt += f" · 전문가: {sp.get('resolution')}"
            txt += "".join(f" · {a['label']} {a['before']}→{a['after']}" for a in sp.get("adjustments") or [])
        _log(w, 3, txt)
    if not w["conflicts"]:
        _log(w, 3, "영역 간 충돌 없음")
    return w


def s3_hard(w: dict, ctx: dict, agents: list | None = None, use_specialists: bool = False) -> dict:
    """4) 약물·질환 강제 제약 — 마지막에, 앞 단계 결과와 무관하게 + 최종 순서·추가 확인 정보 → synth"""
    from .domain import rules
    syn, base, conflicts = w["syn"], w["base"], w["conflicts"]
    overrides = []
    codes = {p["code"] for p in syn["priorities"]}
    diseases = [str(x) for x in ctx.get("diseases") or []]
    for oid, o in (rules().get("hard_overrides") or {}).items():
        if oid.startswith("_") or match_when(o.get("when"), codes, set(syn["constraints"]), diseases) is None:
            continue
        done = []
        for op in o.get("ops") or []:
            f = op.get("field")
            if op["op"] == "remove" and f in syn["constraints"]:
                old = syn["constraints"].pop(f)
                done.append({"op": "remove", "field": f, "before": _r(old["value"]), "after": None})
            elif op["op"] in ("keep_or_raise", "keep_or_lower"):
                ch = _lock(syn, base, f, op["op"], f"강제:{oid}")
                if ch:
                    done.append({"op": op["op"], **ch})
            elif op["op"] == "mute_issue":
                p = _by_code(w).get(op.get("code"))
                if p and p.get("action") != "monitor":
                    p["action_before_override"] = p.get("action")
                    p["action"] = "monitor"
                    p.setdefault("adjusted_by", []).append(f"강제:{oid}")
                    done.append({"op": "mute_issue", "code": p["code"], "title": p.get("title")})
        overrides.append({"id": oid, "label": o["label"], "ops": done, "source": o.get("source"),
                          "section": o.get("section"), "confirm": o.get("confirm") or []})
        _log(w, 4, o["label"] + (": " + ", ".join(
            (f"{d['field']} 삭제 ({d['before']})" if d["op"] == "remove" else
             f"{d.get('title') or d.get('code')} → 관찰로" if d["op"] == "mute_issue" else
             f"{d['field']} {d['before']}→{d['after']}") for d in done) if done else " (바뀐 값 없음)"))
    if not overrides:
        _log(w, 4, "해당 없음")

    syn["priorities"] = rank_priorities(syn["priorities"])
    order1 = [p["code"] for p in syn["priorities"]]
    if order1 != w["order0"]:
        _log(w, 4, "충돌 조정·강제 제약 반영 후 최종 순서: " + " > ".join(order1[:6]))
    # 추가 확인 정보: ① 충돌·강제 제약이 요구한 확인(항상 표시) ② 데이터 빈칸 ③ AI 전문가들의 요청(주제로 묶어서)
    system = [f"[강제 제약] {x}" for o in overrides for x in o["confirm"]] + [f"[충돌] {x}" for c in conflicts for x in c["confirm"]]
    system = list(dict.fromkeys(system)) + _data_gaps(ctx)
    ai = _agent_missing(agents) + [("충돌 전문가", m) for c in conflicts for m in ((c.get("specialist") or {}).get("missing") or [])]
    confirm = system + _ai_missing(ai, system)[:max(0, MAX_CONFIRM - len(system))]
    syn["synthesis"] = {"order": STEP_NAMES, "steps": w["steps"], "conflicts": conflicts, "overrides": overrides,
                        "to_confirm": confirm, "specialists_on": bool(use_specialists)}
    return syn


def finalize(syn: dict, ctx: dict, base: dict | None = None, agents: list | None = None,
             caller=None, use_specialists: bool = False) -> dict:
    """synth → 새 synth (원본은 바꾸지 않음). base 가 없으면 syn 자체를 1단계 값으로 본다.
    LangGraph 경로에서는 같은 단계 함수가 노드 6개로 나뉘어 실행된다 (safety_check → rank_priorities →
    detect_conflicts → [conflict_specialist] → apply_locks → hard_constraints)"""
    w = s3_rank(s3_safety(s3_start(syn, base)))
    w = s3_detect(w, ctx)
    if needs_specialist(w, use_specialists):
        w = s3_specialists(w, ctx, caller)
    w = s3_locks(w)
    return s3_hard(w, ctx, agents, use_specialists)
