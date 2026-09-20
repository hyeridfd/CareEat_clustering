# -*- coding: utf-8 -*-
"""
어르신별 돌봄 솔루션 생성
  1) 규칙 라이브러리에서 후보 조치 선택 (근거 목록)
  2) LLM(OpenAI / Anthropic)이 후보 안에서만 개인화·우선순위화 → JSON
  3) 가드레일 검증 (근거 없는 조치 제거, 약물·진단 표현 차단, 보호자 문장 점검)
  4) 실패·미설정 시 규칙 기반 솔루션으로 대체
  ※ LLM 에는 이름·ID 등 식별정보를 보내지 않는다.
"""
from __future__ import annotations
import json
import os
import re

import logging
from pathlib import Path

import httpx

from . import care_rules
from . import nutrition as nutri
from . import retrieval
from .priority import LEVEL_LABEL

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
log = logging.getLogger("uvicorn.error")


def _key(name: str):
    """환경변수에 없으면 backend/.env 를 다시 읽어 확인 (서버 재시작 없이 .env 수정 반영)."""
    v = os.getenv(name)
    if not v and ENV_FILE.exists():
        try:
            from dotenv import dotenv_values
            v = (dotenv_values(ENV_FILE).get(name) or "").strip() or None
            if v:
                os.environ[name] = v
        except Exception:
            pass
    return v


def llm_status():
    return {"default_provider": os.getenv("LLM_PROVIDER", "none"), "env_file": str(ENV_FILE),
            "env_file_exists": ENV_FILE.exists(), "openai_key": bool(_key("OPENAI_API_KEY")),
            "anthropic_key": bool(_key("ANTHROPIC_API_KEY")),
            "openai_model": os.getenv("OPENAI_MODEL", OPENAI_MODEL),
            "anthropic_model": os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL), "pid": os.getpid()}

BANNED = [
    (re.compile(r"\d+(\.\d+)?\s?(mg|㎎|mcg|IU|iu|단위|g\s?/\s?회|mL|ml|㎖|정|알|캡슐)"), "용량 표현"),
    (re.compile(r"처방|투약|복용|진단(?!\s?평가)|완치|치료제|약을|약물"), "의료행위 표현"),
]
JARGON = re.compile(r"MNA|GDS|MMSE|K-MBI|BMI|C\d\b|군집|클러스터")
GUARDIAN_MAX = 350

FEATURE_LABELS = {
    "age": "연령", "female": "여성(1)", "bmi": "BMI", "mna_sf": "MNA-SF(0–14)", "kmbi_pct": "K-MBI(%)",
    "mmse": "K-MMSE-2(0–30)", "gds": "GDS-SF(0–15)", "chewing_difficulty": "씹기 어려움", "swallowing_difficulty": "삼킴 어려움",
    "texture_level": "식사형태(0일반~3유동)", "eating_dependence": "식사 도움(0–2)", "intake_total": "전체 섭취율(%)",
    "intake_rice": "밥/죽 섭취율(%)", "intake_main": "주찬 섭취율(%)", "intake_side": "부찬 섭취율(%)",
    "intake_soup": "국 섭취율(%)", "sat_overall": "급식 만족(1–5)", "sat_quality": "맛·품질 만족(1–5)",
    "sat_portion": "양 적절성(1–5)", "dx_dementia": "치매", "dx_diabetes": "당뇨", "dx_hypertension": "고혈압",
    "dx_parkinson": "파킨슨", "dx_stroke": "뇌혈관질환", "dx_depression": "우울증", "pref_seafood": "생선 선호",
    "pref_meat": "고기 선호", "pref_fruit": "과일 선호", "pref_vegetable": "채소 선호",
}

SYSTEM_PROMPT = """당신은 요양원 식사·영양 돌봄 코디네이터를 돕는 도우미입니다.
입력으로 어르신 1명의 평가 요약(유형, 우선순위 요인, 주요 지표)과 '후보 조치 목록'이 주어집니다.

규칙:
1. 조치는 반드시 후보 조치 목록 안에서만 고르고, 각 조치에 해당 rule_id 를 적습니다. 목록에 없는 새로운 의학적 조치를 만들지 않습니다.
2. 약 이름·용량, 진단, 처방, 치료 효과를 단정하는 표현을 쓰지 않습니다. 의료적 판단이 필요하면 '의료진과 상의'로 안내합니다.
3. 후보 문장을 어르신의 지표·선호에 맞게 구체화하고, 중요도 순으로 정렬합니다(최대 6개).
3-0. '진단 질환'과 '잔반이 많은 음식군'을 반드시 함께 봅니다. 질환에 맞는 식사 조정(예: 고혈압이면 국물·절임, 당뇨면 단 간식 시간)과 어느 음식군을 남기는지에 대한 대응을 각각 한 줄 이상 씁니다. 약 이름을 근거로 효능·부작용을 설명하지 않습니다.
3-1. '실제 섭취 영양소(하루 평균)'가 주어지면 그 수치를 근거로 씁니다. 기준 대비 80% 미만인 영양소는 무엇을 늘릴지, 나트륨이 기준을 넘으면 무엇을 줄일지 식사 지침에 구체적으로 적습니다. 특정 끼니가 유난히 적으면 그 끼니를 짚습니다. 영양제·보충제 제품명이나 용량은 쓰지 않습니다.
3-2. '참고 지침' 이 주어지면 그 발췌 안의 내용을 근거로 삼습니다. 지침에 근거한 문장은 끝에 [G1] 처럼 해당 발췌 번호를 붙입니다. 발췌에 없는 내용을 지침인 것처럼 쓰거나, 없는 번호를 지어내지 않습니다. 여러 발췌가 근거면 [G1][G3] 처럼 이어 붙입니다.
3-3. 참고 지침이 후보 조치와 다른 방향을 가리키면, 조치 자체는 후보 목록을 따릅니다(후보는 이 어르신의 상태를 이미 반영해 고른 것입니다). 대신 지침이 경고하는 위험을 관찰 항목이나 주의사항에 한 줄로 적습니다. 두 방향을 한 문장에 섞어 모순되게 쓰지 않습니다.
4. guardian_message 는 보호자가 읽는 3~5문장의 쉬운 존댓말입니다. 점수·척도명(MNA, GDS 등)·유형 코드와 [G1] 같은 인용 표기를 쓰지 않고, 불안을 주지 않되 사실대로 씁니다. 350자 이내.
5. '참고 지침' 이 주어졌다면 staff_actions 와 meal_guidance 를 통틀어 **최소 두 문장에는 [G#] 표기를 답니다.** 발췌 내용과 정말로 맞는 문장이 하나도 없을 때만 표기를 생략합니다.
6. 반드시 아래 JSON 한 개만 출력합니다.

{"summary": "담당자용 2~3문장 요약",
 "staff_actions": [{"rule_id": "R_...", "category": "...", "action": "구체적 조치 [G1]", "why": "이 어르신에게 필요한 이유 [G2]"}],
 "meal_guidance": ["식사 지침 [G1]", "..."],
 "monitoring": ["관찰·재평가 항목", "..."],
 "cautions": ["담당자가 주의할 점 [G3]"],
 "guardian_message": "보호자 안내 문장 (인용 표기 없이)"}

위 예시의 [G1] [G2] [G3] 은 '참고 지침' 발췌의 id 입니다. 지침이 주어졌다면 실제 발췌 내용에 근거하는 문장 끝에 그 id 를 붙이세요. 지침이 주어지지 않았으면 아무 표기도 하지 않습니다."""




COMPONENT_LABELS = {"intake_rice": "밥·죽", "intake_soup": "국·탕", "intake_main": "주찬",
                    "intake_side": "부찬", "intake_kimchi": "김치"}


def low_components(features: dict, cut: float = 70.0, top: int = 2):
    """잔반이 특히 많은 음식군 — 섭취율이 낮은 순으로 최대 두 가지"""
    vals = [(v, label) for k, label in COMPONENT_LABELS.items()
            for v in [features.get(k)] if isinstance(v, (int, float)) and v < cut]
    return [label for _, label in sorted(vals)[:top]]


def nutrition_summary(features: dict):
    """features 의 섭취 영양소 요약 → (하루 평균, 기준 대비 %, 가장 낮은 끼니)"""
    n = features.get("nutrition")
    if not isinstance(n, dict) or not n.get("avg_day"):
        return None, {}, None
    gender = "여자" if features.get("female") == 1 else "남자"
    pct = {t["key"]: t["pct"] for t in nutri.compare_targets(n.get("avg_day"), gender, features.get("age"))}
    meals = [m for m in (n.get("meals") or []) if m.get("energy") is not None]
    low = None
    if len(meals) >= 2:
        lo = min(meals, key=lambda m: m["energy"])
        avg = sum(m["energy"] for m in meals) / len(meals)
        if avg and lo["energy"] < avg * 0.7:
            low = lo["meal"]
    return n, pct, low


def nutrition_ctx(features: dict):
    n, pct, low = nutrition_summary(features)
    if not n:
        return None
    fld = nutri.fields()
    keys = ["energy", "protein", "fiber", "ca", "na", "k", "fe", "vd"]
    avg = n.get("avg_day") or {}
    out = {fld[k]["label"]: f"{avg[k]} {fld[k]['unit']}" + (f" (기준 대비 {pct[k]}%)" if k in pct else "")
           for k in keys if k in avg and k in fld}
    if n.get("meals"):
        out["끼니별 에너지(kcal)"] = {m["meal"]: m.get("energy") for m in n["meals"]}
    if low:
        out["특히 적게 드시는 끼니"] = low
    out["_계산"] = "식단표 1인 레시피 × 실제 배식량 × 목측법 섭취율. 간식 제외."
    return out


def build_context(features: dict, type_info: dict, priority: dict, candidates: list, transition: dict,
                  guidelines: list | None = None):
    ind = {FEATURE_LABELS[k]: features.get(k) for k in FEATURE_LABELS if features.get(k) is not None}
    ctx = {
        "유형": {"이름": type_info.get("name"), "설명": type_info.get("description"),
               "보호자용 표현": type_info.get("guardian_label")},
        "우선순위": {"점수": priority["score"], "등급": LEVEL_LABEL[priority["level"]],
                 "요인": [f"{x['label']}" + (f" ({x['value']})" if x.get("value") not in (None, 1) else "")
                        for x in priority["factors"]]},
        "유형 변화": transition.get("kind"),
        "주요 지표": ind,
        "진단 질환": [str(x) for x in (features.get("diseases") or [])][:12],
        "복용 약물": [str(x) for x in (features.get("medications") or [])][:12],
        "잔반이 많은 음식군": low_components(features) or "없음",
        "음식군별 섭취율(%)": {label: features.get(k) for k, label in COMPONENT_LABELS.items()
                            if features.get(k) is not None},
        "실제 섭취 영양소(하루 평균)": nutrition_ctx(features),
        "급식 개선 의견": (features.get("improvement_text") or "")[:200],
        "후보 조치 목록": [{"rule_id": c["id"], "category": c["category"], "staff": c["staff"], "meal": c["meal"],
                       "monitor": c["monitor"]} for c in candidates],
    }
    if guidelines:
        ctx["참고 지침"] = {
            "사용법": "각 발췌의 id(G1, G2 …)를, 그 발췌에 근거한 문장 끝에 [G1] 형태로 붙이세요. "
                    "staff_actions 와 meal_guidance 를 합쳐 최소 두 문장에 답니다. "
                    "발췌에 없는 내용에는 붙이지 않고, 없는 id 를 만들지 않습니다.",
            "발췌": guidelines,
        }
    return ctx


# ─────────────────────────── 규칙 기반 ───────────────────────────

def rules_solution(type_info, priority, candidates):
    top = [x["label"] for x in priority["factors"] if x["points"] > 0][:3]
    summary = (f"{type_info.get('name')} 유형, 우선순위 {LEVEL_LABEL[priority['level']]}({priority['score']:.0f}점)."
               + (f" 주요 요인: {', '.join(top)}." if top else " 뚜렷한 위험 요인은 없습니다."))
    g_parts = [c["guardian"] for c in candidates if c["guardian"]][:3]
    guardian = (f"이번 건강·식사 평가에서 어르신은 '{type_info.get('guardian_label')}'으로 확인되었습니다. "
                + " ".join(g_parts)
                + " 궁금하신 점은 시설로 편하게 문의해 주세요.")
    return {
        "summary": summary,
        "staff_actions": [{"rule_id": c["id"], "category": c["category"], "action": c["staff"], "why": ""}
                          for c in candidates][:6],
        "meal_guidance": [c["meal"] for c in candidates if c["meal"]][:5],
        "monitoring": [c["monitor"] for c in candidates if c["monitor"]][:5],
        "cautions": [],
        "references": [],
        "guardian_message": guardian[:GUARDIAN_MAX],
    }


# ─────────────────────────── LLM 호출 ───────────────────────────

def _extract_json(text: str) -> dict:
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("JSON 없음")
    return json.loads(text[s:e + 1])


def call_openai(ctx: dict) -> tuple[dict, str]:
    key = _key("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(f"OPENAI_API_KEY 미설정 (확인한 파일: {ENV_FILE})")
    r = httpx.post("https://api.openai.com/v1/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.getenv("OPENAI_MODEL", OPENAI_MODEL), "temperature": 0.2,
                         "response_format": {"type": "json_object"},
                         "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}]},
                   timeout=TIMEOUT)
    r.raise_for_status()
    return _extract_json(r.json()["choices"][0]["message"]["content"]), f"openai:{os.getenv('OPENAI_MODEL', OPENAI_MODEL)}"


def call_anthropic(ctx: dict) -> tuple[dict, str]:
    key = _key("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(f"ANTHROPIC_API_KEY 미설정 (확인한 파일: {ENV_FILE})")
    r = httpx.post("https://api.anthropic.com/v1/messages",
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                   json={"model": os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL), "max_tokens": 2000, "temperature": 0.2,
                         "system": SYSTEM_PROMPT,
                         "messages": [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}]},
                   timeout=TIMEOUT)
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    return _extract_json(text), f"anthropic:{os.getenv('ANTHROPIC_MODEL', ANTHROPIC_MODEL)}"


# ─────────────────────────── 가드레일 ───────────────────────────

def _scan(text: str):
    return [label for pat, label in BANNED if pat.search(text or "")]


CITE = re.compile(r"\[G(\d+)\]")


def _cite_fix(text: str, valid: set, used: set, flags: list):
    """없는 번호의 인용 표기를 지운다. 실제로 쓰인 번호는 used 에 모은다."""
    if not text:
        return text
    bad = []

    def sub(m):
        tag = f"G{m.group(1)}"
        if tag in valid:
            used.add(tag)
            return m.group(0)
        bad.append(tag)
        return ""

    out = CITE.sub(sub, text)
    if bad:
        flags.append({"type": "bad_citation", "detail": f"없는 근거 표기 제거: {', '.join(sorted(set(bad)))}"})
    return re.sub(r"\s{2,}", " ", out).strip()


def validate(out: dict, candidates: list, fallback: dict, refs: list | None = None):
    flags = []
    allowed = {c["id"] for c in candidates}
    valid_tags = {r["tag"] for r in (refs or [])}
    used_tags: set = set()
    clean = {"summary": str(out.get("summary", "")).strip() or fallback["summary"]}

    acts = []
    for a in out.get("staff_actions") or []:
        if not isinstance(a, dict):
            continue
        rid = a.get("rule_id")
        if rid not in allowed:
            flags.append({"type": "unsupported_action", "detail": f"근거 목록에 없는 조치 제거: {a.get('action', '')[:40]}"})
            continue
        hits = _scan(a.get("action", "") + a.get("why", ""))
        if hits:
            flags.append({"type": "banned_expression", "detail": f"{rid}: {', '.join(hits)} → 규칙 원문으로 대체"})
            a = {"rule_id": rid, "category": care_rules.RULE_BY_ID[rid]["category"],
                 "action": care_rules.RULE_BY_ID[rid]["staff"], "why": ""}
        action = _cite_fix(a.get("action", ""), valid_tags, used_tags, flags)
        why = _cite_fix(a.get("why", ""), valid_tags, used_tags, flags)
        # 인라인 표기 대신 evidence 배열로 준 경우 문장 끝에 붙여 준다
        extra = [t for t in (a.get("evidence") or []) if isinstance(t, str)]
        extra = [t if t.startswith("G") else f"G{t}" for t in extra]
        extra = [t for t in extra if t in valid_tags and f"[{t}]" not in action]
        if extra:
            used_tags.update(extra)
            action = (action + " " + "".join(f"[{t}]" for t in extra)).strip()
        acts.append({"rule_id": rid, "category": a.get("category") or care_rules.RULE_BY_ID[rid]["category"],
                     "action": action, "why": why})
    if not acts:
        flags.append({"type": "empty_actions", "detail": "유효한 조치가 없어 규칙 기반 조치 사용"})
        acts = fallback["staff_actions"]
    clean["staff_actions"] = acts[:6]

    for key in ("meal_guidance", "monitoring", "cautions"):
        items = [str(x) for x in (out.get(key) or []) if str(x).strip()]
        kept = []
        for x in items:
            x = _cite_fix(x, valid_tags, used_tags, flags)
            if _scan(x):
                flags.append({"type": "banned_expression", "detail": f"{key} 항목 제거: {x[:40]}"})
            elif x:
                kept.append(x)
        clean[key] = kept[:6] if kept else fallback.get(key, [])

    g = CITE.sub("", str(out.get("guardian_message", ""))).strip()
    problems = _scan(g)
    if JARGON.search(g):
        problems.append("전문용어·코드")
    if len(g) > GUARDIAN_MAX:
        problems.append(f"{GUARDIAN_MAX}자 초과")
    if not g or problems:
        flags.append({"type": "guardian_message", "detail": f"보호자 문장 대체 ({', '.join(problems) or '비어 있음'})"})
        g = fallback["guardian_message"]
    clean["guardian_message"] = g
    clean["references"] = [r for r in (refs or []) if r["tag"] in used_tags]
    return clean, flags


def generate(features, type_info, priority, transition, is_borderline, provider: str | None = None):
    _n, npct, low_meal = nutrition_summary(features)
    ctx_rules = {"factor_codes": {x["code"] for x in priority["factors"]}, "is_borderline": is_borderline,
                 "priority_level": priority["level"], "nutrition_pct": npct, "low_meal": low_meal,
                 "low_components": low_components(features)}
    candidates = care_rules.select(features, ctx_rules)
    fallback = rules_solution(type_info, priority, candidates)
    provider = (provider or os.getenv("LLM_PROVIDER", "none")).lower()
    if provider in ("", "none", "rules"):
        return fallback, "rules", [], candidates
    snippets, refs = retrieval.guideline_context(features, candidates, ctx_rules)
    ctx = build_context(features, type_info, priority, candidates, transition, snippets)
    try:
        raw, gen = call_openai(ctx) if provider == "openai" else call_anthropic(ctx)
        clean, flags = validate(raw, candidates, fallback, refs)
        if refs and not clean.get("references"):
            flags.append({"type": "no_citation", "detail": f"지침 {len(refs)}개를 전달했으나 인용되지 않음"})
        if snippets:
            gen = f"{gen}+rag{len(snippets)}"
    except httpx.HTTPStatusError as e:  # API 오류 (키 오류 401, 한도 429 등)
        body = e.response.text[:200] if e.response is not None else ""
        log.warning("[care] LLM %s 실패: %s %s", provider, e.response.status_code if e.response is not None else "", body)
        return fallback, "rules", [{"type": "llm_failed", "detail": f"{provider}: HTTP {e.response.status_code} {body}"}], candidates
    except Exception as e:  # 네트워크·키·파싱 오류 → 규칙 기반
        log.warning("[care] LLM %s 실패: %r", provider, e)
        return fallback, "rules", [{"type": "llm_failed", "detail": f"{provider}: {str(e)[:160]}"}], candidates
    log.info("[care] LLM 솔루션 생성: %s (검증 경고 %d건)", gen, len(flags))
    return clean, gen, flags, candidates
