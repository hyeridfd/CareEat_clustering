# -*- coding: utf-8 -*-
"""[Stage 2] 조건부 정제 — LLM '임상 영양사' 가 어르신 1명의 7개 영역 평가를 함께 보고 종합 판단

  NutriOrion Stage 2(질환별 영양사가 Stage 1 결과를 받아 다듬기) + Stage 3 의 우선순위 매기기에 해당.
  Stage 1 종합은 "같은 영양소는 더 엄격한 값" 이라는 기계적 규칙뿐이라 영역끼리 충돌을 판단하지 못한다.
    예) 저체중이라 열량↑ 인데 당뇨라 당류↓ / 영양불량이라 단백질↑ 인데 단백질 제한 / 연하곤란 + 영양불량이면 더 시급
  이 단계에서 LLM 이
    1) 영역끼리 충돌을 찾고 어떻게 풀지 정하고
    2) 개인 영양 기준을 '허용 범위' 안에서만 조정하고 (목표 열량 포함)
    3) 문제마다 심각도·시급성·개선 가능성을 어르신 전체 상황을 보고 다시 매긴다 → S(j) 재계산
  코드가 지키는 것
    · 허용 범위 밖 값은 범위로 잘라 냄 (나트륨·당류·포화지방 상한은 더 엄격하게만 가능)
    · 최소 ≤ 최대 유지, 목표 열량은 ±10% 이고 열량 범위 안
    · 점수는 0~1, Stage 1 값에서 ±0.3 까지만
    · 피할 식재료(약물·알레르기)는 손대지 않음 (입력에도 사유만 보냄)
    · 실패·미설정이면 Stage 1 결과 그대로 (mode="rule")
  LLM 에는 이름·ID 를 보내지 않는다 (나이는 구간으로).
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

from .. import llm_select as LS
from .base import W_MOD, W_SEV, W_URG, rank_priorities

PROMPT_VERSION = "2026-11-09-refine2"
MAX_WORKERS = 8
RESCORE_MAX_DELTA = 0.3
ENERGY_DELTA = 0.10
# Stage 1 종합값 대비 조정 허용 배율 (낮은 쪽, 높은 쪽)
BANDS = {
    "sodium_max": (0.85, 1.00), "sugar_max": (0.80, 1.00), "sat_fat_max": (0.80, 1.00),
    "fat_max": (0.85, 1.10), "protein_max": (0.90, 1.15), "protein_min": (0.90, 1.25),
    "energy_min": (0.90, 1.15), "energy_max": (0.90, 1.15), "fat_min": (0.90, 1.20),
    "fiber_min": (0.80, 1.25), "potassium_min": (0.80, 1.25),
}
FIELD_KO = {"energy_min": "열량 하한(kcal)", "energy_max": "열량 상한(kcal)", "sugar_max": "당류 상한(g)",
            "protein_min": "단백질 하한(g)", "protein_max": "단백질 상한(g)", "fat_min": "지방 하한(g)",
            "fat_max": "지방 상한(g)", "sat_fat_max": "포화지방 상한(g)", "sodium_max": "나트륨 상한(mg)",
            "potassium_min": "칼륨 하한(mg)", "fiber_min": "식이섬유 하한(g)"}
_CACHE: dict = {}

SYSTEM_PROMPT = """당신은 요양원 어르신의 영양을 총괄하는 임상 영양사입니다.
어르신 1명에 대해 7개 영역 평가(신체·당뇨·고혈압·인지·구강·섭취·약물)가 서로의 결과를 보지 않고 따로 낸 결과가 주어집니다.
각 결과를 함께 보고 종합 판단을 내립니다. 여기서 정한 기준은 한 끼 배식량 조정과 대체찬 선택에 쓰입니다.

할 일:
1. 영역끼리 충돌을 찾습니다. 예) 저체중·영양불량이라 열량·단백질을 늘려야 하는데 당뇨라 당류를 묶어야 함,
   단백질을 늘려야 하는데 단백질 상한이 있음, 연하곤란인데 단백질 공급이 부족함. 충돌이 없으면 빈 목록.
2. 충돌을 풀거나 어르신 전체 상황에 맞추기 위해 꼭 필요하면 개인 영양 기준을 조정합니다.
   반드시 '조정_허용범위' 안의 값만 씁니다. 범위가 없는 항목은 조정하지 않습니다. 조정이 필요 없으면 빈 목록.
   목표 열량을 바꾸면 열량 비율(%E)로 정한 기준(예: 당류 ≤ 열량의 10%)은 시스템이 바뀐 열량으로 다시 계산합니다.
3. Level 2(영양 중재) 문제(code)의 심각도·시급성·개선 가능성(0~1)을 어르신 전체 상황을 보고 다시 매깁니다.
   예) 영양불량과 섭취 부족이 함께 있으면 시급성이 올라감, 섭취율이 매우 낮으면 제한보다 섭취 확보가 먼저.
   Level 1(안전성: 알레르기·연하 안전·약물 상호작용)은 점수와 무관하게 항상 최우선이므로 다시 매기지 않습니다.
   바꿀 필요가 있는 문제만 적습니다.
4. 담당자가 읽을 2문장 요약을 씁니다.

규칙:
- 입력에 있는 문제 code 와 기준 이름만 씁니다. 새 영양소·새 문제를 만들지 않습니다.
- 피할 식재료(약물·알레르기)는 바꾸지 않습니다.
- 약 이름·용량·처방·진단을 말하지 않습니다.
- 숫자는 입력에 있는 값만 근거로 씁니다.
- 반드시 아래 JSON 한 개만 출력합니다.

{"conflicts": [{"agents": ["body", "diabetes"], "description": "충돌 내용", "resolution": "어떻게 풀었는지"}],
 "adjustments": [{"field": "protein_min", "value": 25, "reason": "이유"}],
 "target_energy": {"value": 650, "reason": "이유"},
 "rescore": [{"code": "underweight", "severity": 0.9, "urgency": 0.8, "modifiability": 0.6, "reason": "이유"}],
 "summary": "2문장 요약"}
target_energy 를 바꾸지 않으면 null 로 둡니다."""


# ─────────────────────────── 입력 만들기 ───────────────────────────
def _age_band(age):
    try:
        a = int(age)
    except (TypeError, ValueError):
        return None
    d = a // 10 * 10
    return f"{d}대 " + ("초반" if a % 10 < 4 else "중반" if a % 10 < 7 else "후반")


def _r(v, n=1):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def build_payload(ctx: dict, res: dict, target_energy: float) -> dict:
    """ctx = build_context 결과(어르신 1명), res = {"agents": [Assessment…], "synth": {...}}"""
    syn = res["synth"]
    person = {
        "나이": _age_band(ctx.get("age")), "성별": "여" if ctx.get("female") else "남", "BMI": ctx.get("bmi"),
        "질환": ctx.get("diseases") or [], "식사형태": ctx.get("meal_form"),
        "MNA_SF": ctx.get("mna_sf"), "MNA_위험": ctx.get("mna_risk"), "K-MBI": ctx.get("kmbi_score"), "MMSE": ctx.get("mmse"), "GDS": ctx.get("gds"),
        "혈압": [ctx.get("sbp"), ctx.get("dbp")], "저작곤란": ctx.get("chewing_difficulty"),
        "연하곤란": ctx.get("swallowing_difficulty"), "식사_도움": ctx.get("eating_dependence"),
        "전체_섭취율": ctx.get("intake_rate"),
        "하루평균_섭취": {k: _r(v) for k, v in (ctx.get("avg_day") or {}).items() if _r(v) is not None},
    }
    agents = []
    for a in res["agents"]:
        if not a.active:
            continue
        agents.append({
            "agent": a.agent, "영역": a.label, "요약": a.summary,
            "문제": [{"code": i.code, "title": i.title, "level": i.level, "severity": i.severity, "urgency": i.urgency,
                    "modifiability": i.modifiability, "priority": i.priority, "action": i.action,
                    "evidence": i.evidence} for i in a.issues],
            "기준": [{"nutrient": c.nutrient, "bound": c.bound, "value": _r(c.resolve(target_energy)), "source": c.source,
                    **({"열량_비율": c.value} if c.unit == "pctE" else {})}
                   for c in a.constraints],
            "피할_식재료_사유": [x.reason for x in a.avoid],
            # Stage 1 AI 영역 전문가 판단 (근거 검색) — 있으면 함께 본다
            **({"영역_전문가_판단": {"요약": a.llm.get("summary"), "우려": a.llm.get("concerns"),
                                "추가_확인": a.llm.get("missing"),
                                "문제별_근거": {i.code: i.rationale for i in a.issues if i.rationale}}}
               if (a.llm or {}).get("mode") == "llm" else {}),
        })
    current = {k: {"value": _r(v["value"]), "정한_에이전트": v["agent"]} for k, v in syn["constraints"].items()}
    ranges = {k: [_r(v["value"] * BANDS[k][0]), _r(v["value"] * BANDS[k][1])]
              for k, v in syn["constraints"].items() if k in BANDS and v.get("value")}
    lo_e, hi_e = target_energy * (1 - ENERGY_DELTA), target_energy * (1 + ENERGY_DELTA)
    return {"어르신": person, "영역_평가": agents, "종합_기준(끼니)": current,
            "목표_열량(끼니)": _r(target_energy), "목표_열량_허용범위": [_r(lo_e), _r(hi_e)],
            "조정_허용범위": ranges, "기준_이름": {k: FIELD_KO[k] for k in current if k in FIELD_KO}}


def _hash(payload: dict) -> str:
    return hashlib.sha1((PROMPT_VERSION + json.dumps(payload, ensure_ascii=False, sort_keys=True)).encode()).hexdigest()[:16]


# ─────────────────────────── 검증 ───────────────────────────
def _clip01(x):
    return max(0.0, min(1.0, float(x)))


def validate(raw: dict, payload: dict, res: dict) -> dict:
    """LLM 응답 → 적용할 조정 (범위 밖은 잘라 내고 기록)"""
    syn = res["synth"]
    ranges = payload["조정_허용범위"]
    adj, warn = [], []
    seen = set()
    for x in raw.get("adjustments") or []:
        f = str(x.get("field", "")).strip()
        if f not in ranges or f in seen:
            if f:
                warn.append(f"허용 범위가 없는 기준은 무시: {f}")
            continue
        try:
            v = float(x.get("value"))
        except (TypeError, ValueError):
            warn.append(f"값 형식 오류: {f}"); continue
        lo, hi = ranges[f]
        after = min(max(v, lo), hi)
        before = syn["constraints"][f]["value"]
        if abs(after - before) < 1e-6:
            continue
        seen.add(f)
        adj.append({"field": f, "label": FIELD_KO.get(f, f), "before": _r(before), "proposed": _r(v), "after": _r(after),
                    "clamped": abs(after - v) > 1e-6, "reason": LS._clean(x.get("reason"), 200)})
    # 최소 ≤ 최대
    vals = {k: v["value"] for k, v in syn["constraints"].items()}
    vals.update({a["field"]: a["after"] for a in adj})
    for lo_k, hi_k in (("energy_min", "energy_max"), ("protein_min", "protein_max"), ("fat_min", "fat_max")):
        if vals.get(lo_k) and vals.get(hi_k) and vals[lo_k] > vals[hi_k]:
            adj = [a for a in adj if a["field"] not in (lo_k, hi_k)]
            warn.append(f"{FIELD_KO[lo_k]} > {FIELD_KO[hi_k]} 가 되어 두 조정을 취소")
    te = None
    t = raw.get("target_energy")
    if isinstance(t, dict) and t.get("value") is not None:
        try:
            v = float(t["value"])
            lo_e, hi_e = payload["목표_열량_허용범위"]
            emin = vals.get("energy_min") or 0
            emax = vals.get("energy_max") or 99999
            after = min(max(v, lo_e, emin), hi_e, emax)
            if abs(after - payload["목표_열량(끼니)"]) > 0.5:
                te = {"before": payload["목표_열량(끼니)"], "proposed": _r(v), "after": _r(after),
                      "clamped": abs(after - v) > 1e-6, "reason": LS._clean(t.get("reason"), 200)}
        except (TypeError, ValueError):
            warn.append("목표 열량 형식 오류")
    issues = {i.code: i for a in res["agents"] if a.active for i in a.issues}
    rescore = []
    for x in raw.get("rescore") or []:
        code = str(x.get("code", "")).strip()
        i = issues.get(code)
        if not i:
            if code:
                warn.append(f"없는 문제 code 무시: {code}")
            continue
        if i.level == 1:                       # 안전성은 점수와 무관하게 최우선 → 다시 매기지 않음
            warn.append(f"안전성(Level 1) 문제는 우선순위를 바꾸지 않음: {code}")
            continue
        new = {}
        for k in ("severity", "urgency", "modifiability"):
            try:
                v = _clip01(x.get(k, getattr(i, k)))
            except (TypeError, ValueError):
                v = getattr(i, k)
            old = getattr(i, k)
            new[k] = round(min(max(v, old - RESCORE_MAX_DELTA), old + RESCORE_MAX_DELTA), 3)
        if all(abs(new[k] - getattr(i, k)) < 1e-6 for k in new):
            continue
        rescore.append({"code": code, "title": i.title, "agent": i.agent,
                        "before": {**{k: getattr(i, k) for k in new}, "priority": i.priority},
                        "after": {**new, "priority": round(W_SEV * new["severity"] + W_URG * new["urgency"] + W_MOD * new["modifiability"], 3)},
                        "reason": LS._clean(x.get("reason"), 200)})
    conflicts = [{"agents": [str(a) for a in (c.get("agents") or [])][:4],
                  "description": LS._clean(c.get("description"), 200), "resolution": LS._clean(c.get("resolution"), 200)}
                 for c in (raw.get("conflicts") or []) if isinstance(c, dict)][:5]
    return {"conflicts": conflicts, "adjustments": adj, "target_energy": te, "rescore": rescore,
            "summary": LS._clean(raw.get("summary"), 300), "warnings": warn}


# ─────────────────────────── 실행 ───────────────────────────
def _eligible(res: dict) -> bool:
    """정제할 거리가 있는 어르신: 문제가 2개 이상이거나 신체 외 영역이 하나라도 켜짐"""
    n_issue = sum(len(a.issues) for a in res["agents"] if a.active)
    others = sum(1 for a in res["agents"] if a.active and a.agent != "body")
    return n_issue >= 2 or others >= 1


def refine_one(ctx: dict, res: dict, caller=None, prev: dict | None = None) -> dict:
    payload = build_payload(ctx, res, res["synth"]["target_energy"])
    # 모델·추론 강도가 바뀌면 다시 판단 (같은 입력이라도 이전 결과를 재사용하지 않음)
    _p = LS.provider()
    _m = LS._model(_p) if _p in ("openai", "anthropic") else ""
    h = _hash({**payload, "_model": _m, "_effort": LS.effort(_m)})
    if prev and prev.get("hash") == h and prev.get("mode") == "llm":
        return {**prev, "reused": True}
    if h in _CACHE:
        return {**_CACHE[h], "reused": True}
    t0 = time.time()
    try:
        call = caller or (lambda p: LS.call_llm(p, system=SYSTEM_PROMPT, max_tokens=1500))
        raw, model = call(payload)
        out = validate(raw, payload, res)
        bad = LS.unknown_numbers({"reasons": [a["reason"] for a in out["adjustments"]] + [r["reason"] for r in out["rescore"]],
                                  "tradeoffs": "", "summary": out["summary"]}, payload)
        if bad:
            out["warnings"].append(f"입력에 없는 숫자: {bad[:5]}")
        out.update(mode="llm", model=model, hash=h, prompt_version=PROMPT_VERSION, latency_sec=round(time.time() - t0, 1))
        _CACHE[h] = out
        return out
    except Exception as e:
        return {"mode": "rule", "hash": h, "note": str(e)[:160], "latency_sec": round(time.time() - t0, 1)}


def refine_all(contexts: dict, results: dict, caller=None, prev: dict | None = None, progress=None) -> dict:
    """{eid: refine 결과}. 대상이 아닌 어르신은 {"mode": "none"}"""
    prev = prev or {}
    targets = [eid for eid in results if _eligible(results[eid])]
    out = {eid: {"mode": "none"} for eid in results if eid not in targets}
    if progress:
        progress(f"AI 임상 영양사 종합 판단 ({len(targets)}명)")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {eid: ex.submit(refine_one, contexts[eid], results[eid], caller, prev.get(eid)) for eid in targets}
        for eid, f in futs.items():
            out[eid] = f.result()
    return out


def apply_refine(syn: dict, ref: dict) -> dict:
    """정제 결과를 종합 결과(synth)에 반영한 새 synth (원래 값은 ref 안 before 로 남음)"""
    if ref.get("mode") != "llm":
        return syn
    syn = json.loads(json.dumps(syn))
    # [2026-11-09] 목표 열량이 바뀌면 열량 비율(%E) 기준(당류·포화지방·지방 등)을 바뀐 열량으로 다시 계산
    te = ref.get("target_energy")
    rescaled = []
    if te and syn.get("specs"):
        from .manager import resolve_constraints
        old_c = syn["constraints"]
        new_c = resolve_constraints(syn["specs"], te["after"])
        for k, v in new_c.items():
            if k in old_c and abs(v["value"] - old_c[k]["value"]) > 1e-6:
                rescaled.append({"field": k, "label": FIELD_KO.get(k, k), "before": _r(old_c[k]["value"]),
                                 "after": _r(v["value"]), "energy": [te["before"], te["after"]]})
                v["energy_rescaled_from"] = _r(old_c[k]["value"])
        syn["constraints"] = new_c
    if te:
        syn["target_energy"] = te["after"]
    syn["energy_rescaled"] = rescaled
    for a in ref.get("adjustments") or []:
        c = syn["constraints"][a["field"]]
        base = c.get("energy_rescaled_from")
        # LLM 이 조정한 비율을 바뀐 열량 기준에도 그대로 적용 (예: 당류 상한을 90% 로 낮췄다면 새 기준의 90%)
        val = a["after"] if base is None or not a["before"] else round(c["value"] * a["after"] / a["before"], 2)
        c["value"] = val
        c["refined_from"] = a["before"]
        c["agent"] = "refine"
    for x in rescaled:                         # 화면용: 열량 재계산 + LLM 조정까지 반영된 최종값
        x["final"] = _r(syn["constraints"][x["field"]]["value"])
    by = {r["code"]: r["after"] for r in ref.get("rescore") or []}
    for it in syn.get("priorities") or []:
        if it.get("code") in by:
            it["priority_stage1"] = it["priority"]
            it.update({k: by[it["code"]][k] for k in ("severity", "urgency", "modifiability", "priority")})
    syn["priorities"] = rank_priorities(syn.get("priorities") or [])
    return syn


if __name__ == "__main__":
    # 실제 LLM 확인:  venv-win\Scripts\python -m diet.agents.refine tests\llm_refine_sample.json
    #   (합성 어르신 3명 — 개인정보 없음). 영역 평가 → AI 종합 판단 → 검증 결과를 출력
    import sys
    from .manager import assess_residents
    ctxs = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "tests/llm_refine_sample.json", encoding="utf-8"))
    res = assess_residents(ctxs)
    print("설정:", LS.status())
    for eid, ctx in ctxs.items():
        r = refine_one(ctx, res[eid])
        print(f"\n■ {eid} ({ctx.get('age')}세 · {', '.join(ctx.get('diseases') or []) or '질환 없음'} · BMI {ctx.get('bmi')} · {ctx.get('meal_form')})")
        print("  영역 문제:", [f"{i.title} S{i.priority}" for a in res[eid]['agents'] if a.active for i in a.issues])
        if r.get("mode") != "llm":
            print("  →", r.get("mode"), r.get("note")); continue
        print(f"  요약: {r['summary']}  ({r['model']} · {r['latency_sec']}초)")
        for c in r["conflicts"]:
            print(f"  충돌 {c['agents']}: {c['description']} → {c['resolution']}")
        for a in r["adjustments"]:
            print(f"  기준 {a['label']}: {a['before']} → {a['after']}{' (범위로 맞춤, 제안 ' + str(a['proposed']) + ')' if a['clamped'] else ''} — {a['reason']}")
        if r["target_energy"]:
            t = r["target_energy"]; print(f"  목표 열량: {t['before']} → {t['after']}{' (범위로 맞춤)' if t['clamped'] else ''} — {t['reason']}")
        for x in r["rescore"]:
            print(f"  우선순위 {x['title']}: {x['before']['priority']} → {x['after']['priority']} — {x['reason']}")
        if r["warnings"]:
            print("  경고:", r["warnings"])
