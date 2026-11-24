# -*- coding: utf-8 -*-
"""[2026-11-24] 돌봄 리포트 자동 검증 → 자동 승인·발송

  초안 생성(solution.generate) → 관리자용·보호자용 검증 → 판정
      통과            : 자동 승인 → (동의한 보호자가 있으면) 자동 발송
      수정 가능        : 고칠 점을 생성 모델에 돌려줘 재작성 → 재검증 (최대 MAX_REWRITE 회)
      근거 부족        : 보류 (담당자 검토) — 재작성으로 풀리지 않는 경우 (입력 자료 부족·검증 불가)

  검증 = ① 결정적 검사(질환별 지침 규칙 표·우선순위 대응·형식) + ② 검증 에이전트(다른 LLM이 의미를 항목별로 판정)
  ※ 검증 에이전트에도 이름·ID 등 식별정보를 보내지 않는다.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import re

import httpx

from . import care_rules as CR
from . import solution as sol

log = logging.getLogger("uvicorn.error")

VERIFY_VERSION = "2026-11-24-v1"
STAFF_PASS = 80          # 관리자용 통과 점수
GUARDIAN_PASS = 85       # 보호자용 통과 점수
MAX_REWRITE = 2          # 재작성 최대 횟수 (첫 초안 + 2회)
IMPUTED_MAX = 2          # 결측 대체 변수가 이보다 많으면 근거 부족
AUTO_ACTOR = "auto-verifier"

# ─────────────────────────── 질환별 지침 일치 규칙 ───────────────────────────
#   when(f, c) 가 참인 조건마다 MUST(하나 이상 언급) · FORBID(권장하면 안 되는 내용)를 관리자용 문장에서 검사
#   FORBID 는 문장 단위로 보고, 부정·주의 표현('않도록', '피합니다', '주의')이 있는 문장은 건너뛴다

NEG = re.compile(r"않|말고|피하|피합|주의|금지|없도록|대신|삼가|자제|우려|오히려|경우")


def _malnut(f, c):
    return (CR._v(f, "mna_sf") is not None and CR._v(f, "mna_sf") <= 7) or (CR._v(f, "bmi") is not None and CR._v(f, "bmi") < 18.5)


def _undereat(f, c):
    return _malnut(f, c) or (CR._v(f, "intake_total") or 100) < 75


DISEASE_CHECKS = [
    dict(id="HTN", label="고혈압·나트륨 과다", source="대한고혈압학회 진료지침",
         when=lambda f, c: CR._flag(f, "dx_hypertension") or CR._dx(f, "고혈압") or CR._above(c, "na", 130),
         must=[("국물·절임 등 염분 줄이기", r"국물|염분|나트륨|짠|저염|싱겁|간을|간이|절임|젓갈|장아찌")],
         forbid=[("국물·간을 늘리는 권장", r"(국물|간)[을를]?\s*(더|많이|넉넉히|충분히)\s*(드|제공|늘)|짜게")]),
    dict(id="DM", label="당뇨", source="대한당뇨병학회 진료지침",
         when=lambda f, c: CR._flag(f, "dx_diabetes") or CR._dx(f, "당뇨"),
         must=[("당류·간식·규칙적 식사 관리", r"당류|단\s?음식|단\s?간식|당분|혈당|간식 종류|규칙적|단것|단 것")],
         forbid=[("(영양불량·섭취 저하인데) 식사량·열량 제한", r"(식사량|열량|밥\s?양|섭취량|칼로리)[을를]?\s*(줄|제한|감량)")],
         forbid_when=_undereat),
    dict(id="MALNUT", label="영양불량·저체중", source="ESPEN 고령자 영양 지침",
         when=_malnut,
         must=[("열량·단백질 보강", r"열량|에너지|단백질|간식|보충|보강|늘리|추가"), ("체중 기록·관찰", r"체중")],
         forbid=[("제한식 강조", r"(열량|칼로리|식사량)[을를]?\s*(제한|줄이)|다이어트|소식")]),
    dict(id="SWALLOW", label="삼킴 어려움", source="연하곤란 식사 지침",
         when=lambda f, c: CR._flag(f, "swallowing_difficulty"),
         must=[("식사형태·자세·사레 관찰", r"형태|다진|갈아|죽|점도|걸쭉|연하|자세|사레|기침|흡인")],
         forbid=[("일반식·질긴 음식 권장", r"일반식으로|질긴|딱딱한\s?음식[을를]?\s*(드|제공)|떡[을를]?\s*(드|제공)")]),
    dict(id="CHEW", label="씹기 어려움", source="장기요양기관 급식 지침",
         when=lambda f, c: CR._flag(f, "chewing_difficulty") and not CR._flag(f, "swallowing_difficulty"),
         must=[("부드러운 형태 제공", r"부드|다진|잘게|무르|연한|형태|씹")], forbid=[]),
    dict(id="KIDNEY", label="신장질환", source="대한고혈압학회 칼륨 권고",
         when=lambda f, c: CR._dx(f, "신장", "신부전", "투석"),
         must=[("의료진과 식사 조절 확인", r"의료진|의사|상의|확인")],
         forbid=[("칼륨 많은 채소·과일 증량", r"(칼륨|과일|채소)[을를이가]?\s*(더|많이|충분히|늘)")]),
    dict(id="DEMENTIA", label="치매", source="장기요양기관 급식 지침",
         when=lambda f, c: CR._flag(f, "dx_dementia") or CR._dx(f, "치매"),
         must=[("식사 도움·관찰", r"도움|관찰|안내|식사 시간|환경|지켜|확인|격려|살펴")], forbid=[]),
    dict(id="MOOD", label="우울", source="장기요양기관 급식 지침",
         when=lambda f, c: CR._flag(f, "dx_depression") or (CR._v(f, "gds") or 0) >= 6,
         must=[("기분·섭취 관찰, 연계", r"기분|우울|관찰|의료진|상담|정서|대화|격려|함께")], forbid=[]),
]
NUTRIENT_MUST = {   # 기준 대비 80% 미만 영양소 → 무엇을 늘릴지 언급
    "energy": ("열량", r"열량|에너지|간식|밥|양을|추가"),
    "protein": ("단백질", r"단백질|두부|달걀|계란|생선|고기|우유|콩"),
    "ca": ("칼슘", r"칼슘|우유|멸치|두부|치즈|요구르트|요거트"),
    "fiber": ("식이섬유", r"식이섬유|섬유|채소|나물|과일|잡곡"),
}
COMPONENT_MUST = {"밥·죽": r"밥|죽|주식", "국·탕": r"국|탕", "주찬": r"주찬|단백질 반찬|고기|생선|두부",
                  "부찬": r"부찬|반찬|나물|채소", "김치": r"김치"}
# 우선순위 요인 → 그 요인을 다루는 규칙 (후보에 있는데 조치에 빠지면 감점)
FACTOR_RULES = {
    "mna_malnourished": ["R_MALNUT"], "mna_at_risk": ["R_MALNUT_RISK"], "low_bmi": ["R_LOW_BMI"],
    "intake_very_low": ["R_LOW_INTAKE"], "intake_low": ["R_LOW_INTAKE"], "protein_dish_low": ["R_LOW_PROTEIN", "R_NUT_PROTEIN"],
    "swallowing": ["R_SWALLOW"], "chewing": ["R_CHEW"], "eating_full_help": ["R_DEPEND"], "eating_partial_help": ["R_DEPEND"],
    "depressive": ["R_MOOD"], "depressive_mild": ["R_MOOD"], "weight_loss": ["R_WEIGHT_LOSS"], "intake_drop": ["R_INTAKE_DROP"],
}
FEAR = re.compile(r"위험합니다|심각합니다|심각한 상태|위독|큰일|매우 걱정|악화될 수|사망|생명")
DECIMAL = re.compile(r"\d+\.\d{3,}")
SPECIFIC = re.compile(r"\d|매\s?끼|하루|주\s?\d|끼니|조리|국물|간식|부드럽|다져|데쳐|구워|저염|양을|횟수|시간")


def _sentences(t: str):
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n", t or "") if s.strip()]


def staff_texts(c: dict) -> list[str]:
    out = [c.get("summary", "")]
    for a in c.get("staff_actions") or []:
        out += [a.get("action", ""), a.get("why", "")]
    for k in ("meal_guidance", "monitoring", "cautions"):
        out += list(c.get(k) or [])
    return [str(x) for x in out if x]


def conditions(features: dict, ctx: dict) -> list[dict]:
    """이 어르신에게 해당하는 지침 조건과 MUST/FORBID"""
    out = []
    for d in DISEASE_CHECKS:
        try:
            if not d["when"](features, ctx):
                continue
        except Exception:
            continue
        fb = d["forbid"] if (not d.get("forbid_when") or d["forbid_when"](features, ctx)) else []
        out.append({"id": d["id"], "label": d["label"], "source": d["source"], "must": d["must"], "forbid": fb})
    pct = ctx.get("nutrition_pct") or {}
    for k, (lab, pat) in NUTRIENT_MUST.items():
        if pct.get(k) is not None and pct[k] < 80:
            out.append({"id": f"NUT_{k}", "label": f"{lab} 섭취 부족 ({pct[k]:.0f}%)", "source": "KDRI 2020",
                        "must": [(f"{lab}을(를) 늘릴 방법", pat)], "forbid": []})
    for lab in ctx.get("low_components") or []:
        out.append({"id": f"LEFT_{lab}", "label": f"{lab} 잔반 많음", "source": "잔반 조사",
                    "must": [(f"{lab} 대응", COMPONENT_MUST.get(lab, re.escape(lab)))], "forbid": []})
    return out


# ─────────────────────────── ① 결정적 검사 ───────────────────────────

def rule_checks(content: dict, conds: list, priority: dict, candidates: list, flags: list) -> dict:
    texts = staff_texts(content)
    joined = " ".join(texts)
    sents = [s for t in texts for s in _sentences(t)]
    gates, must_res, forbid_hits = [], [], []
    for cd in conds:
        for lab, pat in cd["must"]:
            ok = bool(re.search(pat, joined))
            must_res.append({"condition": cd["label"], "item": lab, "ok": ok, "source": cd["source"]})
        for lab, pat in cd["forbid"]:
            hit = next((s for s in sents if re.search(pat, s) and not NEG.search(s)), None)
            if hit:
                forbid_hits.append({"condition": cd["label"], "item": lab, "sentence": hit[:80]})
    if forbid_hits:
        gates.append({"code": "H3", "label": "질환 지침과 반대되는 권장", "detail": [f"{x['condition']}: {x['item']} — “{x['sentence']}”" for x in forbid_hits]})
    acts = content.get("staff_actions") or []
    if not acts or len(content.get("meal_guidance") or []) < 2 or len(content.get("monitoring") or []) < 2:
        gates.append({"code": "H5", "label": "필수 항목 누락", "detail": ["조치 1개 이상, 식사 지침·관찰 각 2개 이상 필요"]})
    replaced = [f for f in flags if f.get("type") in ("unsupported_action", "banned_expression")]
    # 우선순위 대응
    cand = {c["id"] for c in candidates}
    used = {a.get("rule_id") for a in acts}
    need = []
    for fx in priority.get("factors") or []:
        rs = [r for r in FACTOR_RULES.get(fx.get("code"), []) if r in cand]
        if rs and (fx.get("points") or 0) >= 5:
            need.append({"factor": fx["label"], "rules": rs, "ok": any(r in used for r in rs)})
    # 구체성: 규칙 원문을 그대로 옮기지 않았는가 + 식사 지침의 구체 표현
    own = [difflib.SequenceMatcher(None, a.get("action", ""), CR.RULE_BY_ID.get(a.get("rule_id"), {}).get("staff", "")).ratio() < 0.85
           for a in acts]
    mg = content.get("meal_guidance") or []
    spec = 0.5 * (sum(own) / len(own) if own else 0) + 0.5 * (sum(bool(SPECIFIC.search(x)) for x in mg) / len(mg) if mg else 0)
    # 형식
    fmt_issues = []
    for key, lo, hi in (("staff_actions", 3, 6), ("meal_guidance", 3, 5), ("monitoring", 3, 5), ("cautions", 2, 4)):
        n = len(content.get(key) or [])
        if not lo <= n <= hi:
            fmt_issues.append(f"{key} {n}개 (권장 {lo}~{hi})")
    dec = sorted({m.group(0) for t in texts for m in DECIMAL.finditer(t)})
    if dec:
        fmt_issues.append(f"소수점이 지나치게 긴 숫자: {', '.join(dec[:3])}")
    if replaced:
        fmt_issues.append(f"가드레일이 고친 항목 {len(replaced)}건")
    return {"gates": gates, "must": must_res, "forbid": forbid_hits, "coverage": need,
            "specificity": round(spec, 3), "format_issues": fmt_issues, "decimals": dec}


def guardian_checks(g: str, flags: list) -> dict:
    ss = _sentences(g)
    gates = []
    if any(f.get("type") == "guardian_message" for f in flags):
        gates.append({"code": "H4", "label": "보호자 문장 규칙 위반으로 규칙 문장으로 대체됨",
                      "detail": [f["detail"] for f in flags if f.get("type") == "guardian_message"]})
    if sol.JARGON.search(g) or sol.CITE.search(g) or re.search(r"\[\d+\]", g):
        gates.append({"code": "H4", "label": "보호자용에 척도명·코드·근거 표기", "detail": []})
    avg = sum(len(s) for s in ss) / len(ss) if ss else 0
    read = (10 if 3 <= len(ss) <= 5 else 5 if ss else 0) + (5 if len(g) <= sol.GUARDIAN_MAX else 0) + (10 if avg <= 70 else 5 if avg <= 90 else 0)
    polite = sum(bool(re.search(r"(니다|세요|어요|아요|해요|습니다|드립니다)[.!]?$", s)) for s in ss) / len(ss) if ss else 0
    fear = [m.group(0) for m in FEAR.finditer(g)]
    tone = (5 if polite >= 0.8 else 2) + (5 if not fear else 0)
    guide = 15 if re.search(r"문의|연락|상담|말씀|함께|가정에서|면회|알려", g) else 5
    return {"gates": gates, "sentences": len(ss), "chars": len(g), "avg_len": round(avg), "readability": read,
            "tone_rule": tone, "fear": fear, "action_guide": guide}


# ─────────────────────────── ② 검증 에이전트 ───────────────────────────

VERIFY_PROMPT = """당신은 요양원 돌봄 리포트를 검수하는 임상 영양사입니다. 다른 AI가 쓴 초안을 입력 자료와 대조해 항목별로 판정합니다.
글을 고쳐 쓰지 말고 판정만 합니다. 입력에 없는 사실을 근거로 판정하지 않습니다.

판정 기준
- summary: 입력 지표·우선순위 요인과 맞는가, 과장·누락이 없는가.
- staff_actions (번호마다): 이유(why)가 입력 지표와 맞는가, 무엇을·언제·얼마나가 드러나 실행할 수 있는가, 질환 지침과 충돌이 없는가.
- meal_guidance: 진단 질환에 맞는 식사 조정과 잔반이 많은 음식군 대응이 각각 있는가, 기준 80% 미만 영양소·나트륨 초과가 반영됐는가.
- monitoring: 관찰할 지표와 주기가 있는가.
- cautions: 이 어르신에게 해당하는 위험인가, 질환 간 충돌(예: 당뇨인데 영양불량)을 짚는가.
- disease_alignment: '지침 점검 조건'마다 초안이 지침 방향을 충족(met)·누락(missing)·반대(conflict)하는지.
- citations: 근거 번호마다 그 발췌가 해당 문장을 뒷받침하는가 (support / partial / unrelated).
- guardian: consistency(관리자용과 같은 내용인가, 없는 약속·수치를 만들지 않았는가), readability(쉬운 말), tone(불안을 주지 않고 사실대로), action_guide(보호자가 할 일·문의 안내).

점수: 2 = 그대로 승인 가능, 1 = 고치면 좋음, 0 = 고쳐야 함.
verdict: ok | fix | contradiction(입력 자료나 지침과 모순) | unsupported(입력 자료로 확인할 수 없는 주장).
evidence_sufficient: 입력 자료 자체가 부족해서 어떤 문장으로도 판단할 수 없으면 false (글을 고쳐도 해결되지 않는 경우만). 그 이유를 evidence_gap 에 씁니다.
fix_instructions: 재작성할 때 생성 AI에게 줄 구체적인 지시 (최대 6개, 한 문장씩).

아래 JSON 하나만 출력합니다.
{"staff": {"summary": {"score": 2, "verdict": "ok", "reason": ""},
           "actions": [{"index": 1, "score": 2, "verdict": "ok", "reason": ""}],
           "meal_guidance": {"score": 2, "verdict": "ok", "reason": ""},
           "monitoring": {"score": 2, "verdict": "ok", "reason": ""},
           "cautions": {"score": 2, "verdict": "ok", "reason": ""},
           "disease_alignment": [{"condition": "고혈압·나트륨 과다", "verdict": "met", "reason": ""}],
           "citations": [{"tag": "1", "verdict": "support", "reason": ""}]},
 "guardian": {"consistency": {"score": 2, "verdict": "ok", "reason": ""}, "readability": {"score": 2, "reason": ""},
              "tone": {"score": 2, "reason": ""}, "action_guide": {"score": 2, "reason": ""}},
 "evidence_sufficient": true, "evidence_gap": "", "fix_instructions": []}"""


def _verify_provider(gen_provider: str) -> str:
    p = (os.getenv("VERIFY_PROVIDER") or "").lower()
    if p in ("openai", "anthropic"):
        return p
    other = "anthropic" if gen_provider == "openai" else "openai"   # 생성과 다른 모델로 교차 검증
    if sol._key("ANTHROPIC_API_KEY" if other == "anthropic" else "OPENAI_API_KEY"):
        return other
    return gen_provider if gen_provider in ("openai", "anthropic") else ("openai" if sol._key("OPENAI_API_KEY") else "anthropic")


def _call(provider: str, system: str, payload: dict) -> tuple[dict, str]:
    body = json.dumps(payload, ensure_ascii=False)
    if provider == "openai":
        key = sol._key("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY 미설정")
        model = os.getenv("VERIFY_MODEL") or os.getenv("OPENAI_MODEL", sol.OPENAI_MODEL)
        r = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": body}]},
                       timeout=sol.TIMEOUT)
        r.raise_for_status()
        return sol._extract_json(r.json()["choices"][0]["message"]["content"]), f"openai:{model}"
    key = sol._key("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정")
    model = os.getenv("VERIFY_MODEL") or os.getenv("ANTHROPIC_MODEL", sol.ANTHROPIC_MODEL)
    r = httpx.post("https://api.anthropic.com/v1/messages",
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                   json={"model": model, "max_tokens": 2500, "temperature": 0, "system": system,
                         "messages": [{"role": "user", "content": body}]}, timeout=sol.TIMEOUT)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    return sol._extract_json(text), f"anthropic:{model}"


def agent_verify(content: dict, ctx_payload: dict, conds: list, snippets: list, provider: str) -> tuple[dict, str]:
    by_orig = {s["id"]: s for s in snippets or []}
    refs = [{"tag": r["tag"], "출처": by_orig.get(r.get("orig_tag"), {}).get("출처"), "내용": by_orig.get(r.get("orig_tag"), {}).get("내용")}
            for r in content.get("references") or []]
    payload = {
        "어르신 자료": ctx_payload,
        "지침 점검 조건": [{"condition": c["label"], "지침": c["source"], "충족해야 할 방향": [m[0] for m in c["must"]],
                       "하면 안 되는 권장": [x[0] for x in c["forbid"]]} for c in conds],
        "근거 발췌": refs,
        "초안_관리자용": {k: content.get(k) for k in ("summary", "staff_actions", "meal_guidance", "monitoring", "cautions")},
        "초안_보호자용": content.get("guardian_message"),
    }
    return _call(provider, VERIFY_PROMPT, payload)


# ─────────────────────────── 채점 · 판정 ───────────────────────────

def _s(x, default=1):
    try:
        return max(0, min(2, int((x or {}).get("score", default))))
    except Exception:
        return default


def score(content: dict, rc: dict, gc: dict, ag: dict | None, has_refs: bool) -> dict:
    st, gd = (ag or {}).get("staff") or {}, (ag or {}).get("guardian") or {}
    # 관리자용
    must = rc["must"]
    rule_align = sum(m["ok"] for m in must) / len(must) if must else 1.0
    da = st.get("disease_alignment") or []
    if da:
        ag_align = sum(1 if d.get("verdict") == "met" else 0 for d in da) / len(da)
        align = 0.5 * rule_align + 0.5 * ag_align
    else:
        align = rule_align
    cov = rc["coverage"]
    cover = sum(x["ok"] for x in cov) / len(cov) if cov else 1.0
    cits = st.get("citations") or []
    if cits:
        cite = sum(1 if c.get("verdict") == "support" else 0.5 if c.get("verdict") == "partial" else 0 for c in cits) / len(cits)
    else:
        cite = 0.5 if has_refs else 0.7
    acts = st.get("actions") or []
    ag_act = (sum(_s(a) for a in acts) / (2 * len(acts))) if acts else None
    spec = rc["specificity"] if ag_act is None else 0.5 * rc["specificity"] + 0.5 * ag_act
    fmt = max(0.0, 1 - 0.25 * len(rc["format_issues"]))
    staff_parts = {"질환 지침 일치": round(30 * align, 1), "우선순위 요인 대응": round(25 * cover, 1),
                   "근거 인용 정확도": round(20 * cite, 1), "구체성": round(15 * spec, 1), "형식": round(10 * fmt, 1)}
    # 보호자용
    cons = _s(gd.get("consistency")) / 2 if gd.get("consistency") else 0.75
    tone = gc["tone_rule"] + (5 * _s(gd.get("tone")) / 2 if gd.get("tone") else 3)
    read = gc["readability"] * (0.6 + 0.2 * _s(gd.get("readability"))) if gd.get("readability") else gc["readability"]
    guard_parts = {"관리자용과 내용 일치": round(40 * cons, 1), "읽기 쉬움": round(min(25, read), 1),
                   "어조": round(min(20, tone), 1), "보호자 행동 안내": round(gc["action_guide"], 1)}
    # 에이전트 판정에서 나온 관문 실패 (모순·반대)
    agate_s, agate_g = [], []
    bad = [("요약", st.get("summary"))] + [(f"조치 {a.get('index')}", a) for a in acts] + \
          [(k, st.get(k)) for k in ("meal_guidance", "monitoring", "cautions")]
    for name, x in bad:
        if (x or {}).get("verdict") == "contradiction":
            agate_s.append(f"{name}: {x.get('reason', '')}")
    for d in da:
        if d.get("verdict") == "conflict":
            agate_s.append(f"{d.get('condition')}: {d.get('reason', '')}")
    if (gd.get("consistency") or {}).get("verdict") in ("contradiction", "unsupported"):
        agate_g.append(gd["consistency"].get("reason", ""))
    gates_s = rc["gates"] + ([{"code": "A1", "label": "검증 에이전트: 입력 자료·지침과 모순", "detail": agate_s}] if agate_s else [])
    gates_g = gc["gates"] + ([{"code": "A2", "label": "검증 에이전트: 관리자용과 다른 내용", "detail": agate_g}] if agate_g else [])
    s_total, g_total = round(sum(staff_parts.values()), 1), round(sum(guard_parts.values()), 1)
    return {"staff": {"score": s_total, "parts": staff_parts, "gates": gates_s, "pass": not gates_s and s_total >= STAFF_PASS},
            "guardian": {"score": g_total, "parts": guard_parts, "gates": gates_g, "pass": not gates_g and g_total >= GUARDIAN_PASS}}


def evidence_gaps(priority: dict, imputed: list, conds: list, refs: list, ag: dict | None, agent_err: str | None) -> list[str]:
    """재작성으로 풀리지 않는 '근거 부족' — 있으면 보류"""
    gaps = []
    codes = {f.get("code") for f in priority.get("factors") or []}
    if "no_nutrition" in codes:
        gaps.append("영양(잔반) 조사 미완료 — 섭취 지표가 추정값입니다.")
    if "borderline" in codes:
        gaps.append("유형 경계 사례 — 담당자 확인이 필요한 평가입니다.")
    if len(imputed or []) > IMPUTED_MAX:
        gaps.append(f"평가 변수 {len(imputed)}개가 결측이라 대체값으로 평가했습니다.")
    if conds and not refs:
        gaps.append("질환 지침 근거를 불러오지 못했습니다 (지침 검색 결과 없음).")
    if agent_err:
        gaps.append(f"검증 에이전트를 실행하지 못했습니다: {agent_err[:120]}")
    if ag and ag.get("evidence_sufficient") is False:
        gaps.append(f"검증 에이전트: {ag.get('evidence_gap') or '입력 자료로 판단할 근거가 부족합니다.'}")
    return gaps


def feedback(content: dict, rc: dict, gc: dict, sc: dict, ag: dict | None) -> list[str]:
    """재작성 지시 — 생성 모델에 그대로 넘긴다"""
    fb = []
    for g in sc["staff"]["gates"] + sc["guardian"]["gates"]:
        fb.append(f"[필수] {g['label']}: {' / '.join(g['detail'])[:200]}" if g["detail"] else f"[필수] {g['label']}")
    for m in rc["must"]:
        if not m["ok"]:
            fb.append(f"{m['condition']}: '{m['item']}'에 대한 내용을 조치나 식사 지침에 넣으세요 ({m['source']}).")
    for c in rc["coverage"]:
        if not c["ok"]:
            fb.append(f"우선순위 요인 '{c['factor']}'에 대한 조치({'/'.join(c['rules'])})를 포함하세요.")
    for x in rc["format_issues"]:
        fb.append(f"형식: {x}" + (" — 소수점 첫째 자리까지만 쓰세요." if "소수점" in x else ""))
    st = (ag or {}).get("staff") or {}
    texts = staff_texts(content)
    for c in st.get("citations") or []:
        if c.get("verdict") == "unrelated":
            s = next((t for t in texts if f"[{c.get('tag')}]" in t), "")
            fb.append(f"근거 표기가 내용과 맞지 않습니다 — “{s[:50]}”의 표기를 빼거나 맞는 발췌로 바꾸세요.")
    for x in (ag or {}).get("fix_instructions") or []:
        fb.append(str(x))
    if not sc["guardian"]["pass"]:
        if gc["fear"]:
            fb.append(f"보호자용: 불안을 주는 표현({', '.join(gc['fear'])})을 사실대로 차분하게 바꾸세요.")
        if not 3 <= gc["sentences"] <= 5:
            fb.append("보호자용: 3~5문장으로 쓰세요.")
        if gc["action_guide"] < 15:
            fb.append("보호자용: 보호자가 도와주실 일이나 문의 방법을 한 문장 넣으세요.")
    seen, out = set(), []
    for x in fb:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:12]


def run(features, type_info, priority, transition, is_borderline, provider=None, imputed=None) -> dict:
    """초안 생성 → 검증 → (재작성) → 판정.  반환: content, generator, flags, candidates, verification"""
    attempts, fb, last = [], None, None
    gen_provider = (provider or os.getenv("LLM_PROVIDER", "none")).lower()
    for i in range(MAX_REWRITE + 1):
        detail: dict = {}
        content, gen, flags, cands = sol.generate(features, type_info, priority, transition, is_borderline,
                                                  provider, feedback=fb, detail=detail)
        ctx_rules = detail.get("ctx_rules") or {}
        conds = conditions(features, ctx_rules)
        rc = rule_checks(content, conds, priority, cands, flags)
        gc = guardian_checks(content.get("guardian_message", ""), flags)
        ag, ag_gen, ag_err = None, None, None
        vp = _verify_provider(gen_provider)
        try:
            ag, ag_gen = agent_verify(content, detail.get("ctx_payload") or {}, conds, detail.get("snippets") or [], vp)
        except Exception as e:
            ag_err = str(e)
            log.warning("[care] 검증 에이전트 실패: %r", e)
        sc = score(content, rc, gc, ag, bool(detail.get("refs")))
        gaps = evidence_gaps(priority, imputed, conds, detail.get("refs") or [], ag, ag_err)
        if gaps:
            decision = "hold"
        elif sc["staff"]["pass"] and sc["guardian"]["pass"]:
            decision = "pass"
        elif sc["staff"]["pass"] and i == MAX_REWRITE:
            decision = "pass_staff_only"         # 관리자용만 승인, 보호자 발송은 보류
        else:
            decision = "rewrite" if i < MAX_REWRITE else "hold"
        fbk = feedback(content, rc, gc, sc, ag) if decision in ("rewrite", "hold", "pass_staff_only") else []
        att = {"attempt": i + 1, "generator": gen, "verifier": ag_gen, "decision": decision, "scores": sc,
               "rule": rc, "guardian_rule": gc, "agent": ag, "gaps": gaps, "feedback_out": fbk,
               "feedback_in": fb or [], "conditions": [{"id": c["id"], "label": c["label"], "source": c["source"]} for c in conds]}
        attempts.append(att)
        last = (content, gen, flags, cands, att)
        if decision != "rewrite":
            break
        if gen == "rules":              # 규칙 기반 생성은 다시 써도 같은 결과 → 보류
            att["decision"] = decision = "hold"
            att["gaps"].append("규칙 기반 초안이라 재작성할 수 없습니다.")
            break
        fb = fbk
    content, gen, flags, cands, att = last
    reason = {"pass": "관리자용·보호자용 모두 통과", "pass_staff_only": "관리자용 통과 · 보호자용 미달 (보호자 발송 보류)",
              "hold": "보류 — " + ("; ".join(att["gaps"]) if att["gaps"] else f"재작성 {MAX_REWRITE}회 후에도 기준 미달")}.get(att["decision"], "")
    verification = {"version": VERIFY_VERSION, "decision": att["decision"], "reason": reason,
                    "thresholds": {"staff": STAFF_PASS, "guardian": GUARDIAN_PASS, "max_rewrite": MAX_REWRITE},
                    "final": att["scores"], "rewrites": len(attempts) - 1,
                    "attempts": [{k: v for k, v in a.items() if k != "agent"} | {"agent": a["agent"]} for a in attempts]}
    return {"content": content, "generator": gen, "flags": flags, "candidates": cands, "verification": verification}
