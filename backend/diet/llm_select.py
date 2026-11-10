# -*- coding: utf-8 -*-
"""AI 영양사 식단 선택 — 최적화(NSGA-II)가 찾은 파레토 식단 중 하나를 LLM 이 시설 상황을 보고 고른다

  흐름 ("최적화가 후보를 만들고, LLM 이 판단하고, 코드가 지킨다")
    1) 후보 추리기  shortlist()  파레토 해 중 f1 ≤ 0.3 통과 해에서 서로 다른 성격의 식단 최대 6개
                    = 규칙 선택(균형점) + 목적별 최우수(영양·비용·다양성·조화) + 서로 멀리 떨어진 해
    2) 후보 요약    summarize()  반복 보정까지 마친 식단으로 f1~f4, 하루 평균 영양, 반복, 조화, 비용, 자주 나온 메뉴
    3) 시설 상황    facility_context()  어르신 수·질환·식사형태·에이전트가 꼽은 주요 문제·피할 식재료 (개인 식별정보 없음)
    4) LLM 판단     choose()  후보 id 하나를 고르고 이유·포기한 점·승인 전 확인할 점을 JSON 으로
    5) 가드레일     고른 id 가 후보에 없거나, 형식이 틀리거나, 호출이 실패하면 → 규칙 선택(균형점)으로 대체
  LLM 은 이미 검증된 후보 중에서만 고르므로 영양·안전 기준을 벗어난 식단은 나올 수 없다.

  설정 (backend/.env 또는 환경변수)
    DIET_LLM_PROVIDER   openai | anthropic | none   (없으면 LLM_PROVIDER, 그것도 없으면 none = 규칙 선택)
    DIET_LLM_MODEL      모델 이름 (없으면 OPENAI_MODEL / ANTHROPIC_MODEL, 기본 gpt-4o-mini / claude-sonnet-4-5)
    DIET_LLM_EFFORT     추론형 모델(gpt-5·gpt-6·o 시리즈)의 추론 강도 none|low|medium|high (기본 low)
                        추론형 모델에는 temperature 를 보내지 않는다 (지원하지 않음)
    OPENAI_API_KEY · ANTHROPIC_API_KEY  (돌봄 솔루션과 같은 키)
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

from .moo_metrics import BALANCE_PASS_F1, select_balanced

PROMPT_VERSION = "2026-11-04-select2"
MAX_CANDIDATES = 6
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
OBJ = ("f1_영양", "f2_비용", "f3_다양성", "f4_조화")
ORIGIN = ("영양 최우수", "비용 최우수", "다양성 최우수", "조화 최우수")
NUTR_SHOW = (("energy", "열량", "kcal"), ("protein", "단백질", "g"), ("sodium", "나트륨", "mg"),
             ("sugar", "당류", "g"), ("fat", "지방", "g"), ("fiber", "식이섬유", "g"))
WHITE = {"쌀밥", "배추김치", "백김치"}


# ─────────────────────────── 1) 후보 추리기 ───────────────────────────
def shortlist(F, k: int = MAX_CANDIDATES, pass_f1: float = BALANCE_PASS_F1) -> list[tuple[int, list[str]]]:
    """→ [(파레토 해 번호, [뽑힌 이유…])]  첫 번째는 항상 규칙 선택(균형점)"""
    F = np.asarray(F, dtype=float)
    rule_i, _ = select_balanced(F, pass_f1)
    feas = np.where(F[:, 0] <= pass_f1)[0]
    if len(feas) == 0:
        feas = np.argsort(F[:, 0])[:max(1, int(len(F) * 0.1))]
    # 목적값이 같은 해(중복)는 하나만
    uniq, seen = [], set()
    for i in [rule_i] + [int(x) for x in feas]:
        key = tuple(np.round(F[i], 6))
        if key not in seen:
            seen.add(key)
            uniq.append(i)
    picks: dict[int, list[str]] = {rule_i: ["규칙 선택(균형점)"]}
    sub = F[uniq]
    for j, name in enumerate(ORIGIN):
        if np.ptp(sub[:, j]) < 1e-9:                     # 모두 같은 값(예: 재고 미입력으로 f2=0)이면 의미 없음
            continue
        i = uniq[int(np.argmin(sub[:, j]))]
        picks.setdefault(i, []).append(name)
    # 나머지는 정규화 목적 공간에서 이미 고른 해와 가장 먼 해 (서로 다른 성격)
    lo, hi = sub.min(axis=0), sub.max(axis=0)
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    Z = {i: (F[i] - lo) / span for i in uniq}
    while len(picks) < min(k, len(uniq)):
        far = max((i for i in uniq if i not in picks), key=lambda i: min(np.linalg.norm(Z[i] - Z[p]) for p in picks))
        picks[far] = ["다른 균형"]
    out = [(rule_i, picks.pop(rule_i))] + sorted(picks.items(), key=lambda t: F[t[0], 0])
    return out[:k]


# ─────────────────────────── 2) 후보 요약 ───────────────────────────
def summarize(problem, chrom, standard) -> dict:
    """식단 1개 → LLM·화면에 보일 요약 (숫자는 모두 코드가 계산)"""
    from .problem import N_DAYS, repeat_counts
    menus = problem.effective_menus(chrom)
    f = problem._eval_one(chrom)
    days = [menus[d * 18:(d + 1) * 18] for d in range(N_DAYS)]
    nutr = {}
    for key, label, unit in NUTR_SHOW:
        avg = float(np.mean([sum(m.get(key, 0) or 0 for m in d) for d in days]))
        lo, hi = getattr(standard, f"daily_{key}_min", None), getattr(standard, f"daily_{key}_max", None)
        nutr[label] = {"하루평균": round(avg, 1), "단위": unit, "기준": [lo, hi]}
    viol = problem.nutrition_breakdown(menus)
    top_v = {k: round(v, 3) for k, v in list(viol.items())[:4] if v >= 0.005}
    pat = problem.pattern_breakdown(chrom)
    names = [m["menu_name"] for i, m in enumerate(menus) if i % 6 in (1, 2, 3, 4)]
    freq = [(n, c) for n, c in Counter(x for x in names if x not in WHITE and not x.startswith("-(")).most_common(5) if c > 2]
    out = {"목적함수": {k: round(float(v), 4) for k, v in zip(OBJ, f)},
           "하루평균_영양": nutr,
           "영양위반_주요": top_v,
           "반복": repeat_counts(menus),
           "자주나온_메뉴": [f"{n} {c}회" for n, c in freq],
           "시설선호_평균": round(float(np.mean([m.get("preference_score", 0.7) for m in menus])), 3),
           "끼니당_비용": round(sum(m.get("cost", 0) or 0 for m in menus) / (N_DAYS * 3)),
           "다진찬_부적합_끼니": pat.get("다진찬_부적합_포함_끼니", 0),
           "한그릇_끼니": pat.get("한그릇_끼니수", 0)}
    h = problem.meal_harmony(chrom)
    if h is not None:
        from .pipeline import _harmony_summary
        hs = _harmony_summary(problem, chrom) or {}
        out["조화"] = {"한끼_평균": hs.get("mean"), "낮은_끼니": hs.get("low_meals"),
                     "시설스타일_유사도": hs.get("style_similarity")}
    return out


def compact_menu(records: list) -> list:
    """화면에서 '이 후보로 바꾸기' 에 쓸 식단표 (메뉴 이름만)"""
    keep = ("일차", "끼니", "밥", "국", "주찬", "부찬1", "부찬2", "김치")
    return [{k: r.get(k) for k in keep} for r in records]


# 후보끼리 비교는 코드가 미리 계산한다 (LLM 이 숫자 방향을 거꾸로 읽는 실수를 막음)
#   (표시 이름, 값 꺼내기, 좋은 방향 low|high)
COMPARE = [
    ("영양 위반 f1", lambda c: c["목적함수"]["f1_영양"], "low"),
    ("다양성 f3", lambda c: c["목적함수"]["f3_다양성"], "low"),
    ("조화 f4", lambda c: c["목적함수"]["f4_조화"], "low"),
    ("나트륨 하루평균(mg)", lambda c: c["하루평균_영양"]["나트륨"]["하루평균"], "low"),
    ("당류 하루평균(g)", lambda c: c["하루평균_영양"]["당류"]["하루평균"], "low"),
    ("단백질 하루평균(g)", lambda c: c["하루평균_영양"]["단백질"]["하루평균"], "high"),
    ("식이섬유 하루평균(g)", lambda c: c["하루평균_영양"]["식이섬유"]["하루평균"], "high"),
    ("14일 안 반복(회)", lambda c: c["반복"]["반복_14일안"], "low"),
    ("3일 안 반복(회)", lambda c: c["반복"]["반복_3일안"] + c["반복"]["반복_같은날·연속끼니"], "low"),
    ("한 끼 조화", lambda c: (c.get("조화") or {}).get("한끼_평균"), "high"),
    ("조화 낮은 끼니(개)", lambda c: (c.get("조화") or {}).get("낮은_끼니"), "low"),
    ("다진찬 부적합 끼니(개)", lambda c: c["다진찬_부적합_끼니"], "low"),
    ("시설 선호", lambda c: c["시설선호_평균"], "high"),
    ("끼니당 비용(원)", lambda c: c["끼니당_비용"], "low"),
]
SAME_PCT = 2.0          # 이 % 미만 차이는 '비슷'


def _fmt(v):
    return int(v) if float(v).is_integer() else round(float(v), 4)


def compare(cands: list) -> list:
    """후보 목록 → 각 후보에 'A_대비'(좋아진 점·나빠진 점·비슷한 항목)와 '기준_초과' 를 붙인 새 목록"""
    base = cands[0]
    out = []
    for c in cands:
        c = {k: v for k, v in c.items() if k not in ("A_대비", "기준_초과")}
        over = []
        for label, d in (c.get("하루평균_영양") or {}).items():
            lo, hi = (d.get("기준") or [None, None])[:2]
            v = d.get("하루평균")
            if hi is not None and v > hi:
                over.append(f"{label} 하루평균 {_fmt(v)}{d['단위']} > 상한 {_fmt(hi)}")
            if lo is not None and v < lo:
                over.append(f"{label} 하루평균 {_fmt(v)}{d['단위']} < 하한 {_fmt(lo)}")
        c["기준_초과"] = over or ["없음"]
        if c is not base and c["id"] != base["id"]:
            good, bad, same = [], [], []
            for label, get, better in COMPARE:
                try:
                    v, b = get(c), get(base)
                except (KeyError, TypeError):
                    continue
                if v is None or b is None:
                    continue
                diff = v - b
                pct = diff / abs(b) * 100 if b else (0.0 if diff == 0 else 100.0)
                if abs(pct) < SAME_PCT:
                    same.append(label)
                    continue
                word = f"{label}: {_fmt(v)} (A {_fmt(b)}, {'+' if diff > 0 else ''}{round(pct)}%)"
                ((good if (diff < 0) == (better == "low") else bad)).append(word)
            c["A_대비"] = {"좋아진_점": good or ["없음"], "나빠진_점": bad or ["없음"], "비슷함(2% 미만)": same}
        out.append(c)
    return out


def build_payload(context: dict, cands: list) -> dict:
    return {"시설_상황": context, "후보": compare(cands),
            "참고": ("A 는 기존 규칙(f1 통과 해 중 네 목적의 균형점)이 고른 후보입니다. 목적함수는 0~1, 낮을수록 좋습니다. "
                   "후보끼리 비교는 각 후보의 'A_대비' 에 코드가 이미 계산해 두었습니다.")}


# ─────────────────────────── 3) 시설 상황 ───────────────────────────
def facility_context(profiles: list, meta: dict, agent_json: dict, start_date=None, budget: int | None = None) -> dict:
    """개인 식별정보 없이 집계만 (이름·ID·생년월일을 넣지 않는다)"""
    n = len(profiles)
    dz = Counter(d for m in meta.values() for d in (m.get("diseases") or []))
    dz.update({"치매": sum(1 for m in meta.values() if m.get("dementia"))})
    tex = Counter(m.get("texture") for m in meta.values())
    issues = Counter()
    for v in (agent_json or {}).values():
        for it in ((v.get("synth") or {}).get("priorities") or [])[:3]:
            issues[it.get("title") or it.get("code")] += 1
    avoid = Counter()
    for p in profiles:
        for a in getattr(p, "avoid", []) or []:
            avoid[a.get("reason", "")[:40]] += 1
    ages = [m.get("age") for m in meta.values() if m.get("age")]
    month = None
    try:
        month = int(str(start_date)[5:7]) if start_date else time.localtime().tm_mon
    except ValueError:
        month = time.localtime().tm_mon
    season = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄", 6: "여름", 7: "여름", 8: "여름"}.get(month, "가을")
    return {"어르신_수": n, "평균_나이": round(float(np.mean(ages)), 1) if ages else None,
            "질환_인원": dict(dz.most_common()), "식사형태_인원": dict(tex.most_common()),
            "다진찬_인원_합계": sum(v for k, v in tex.items() if k and "다진" in k),
            "죽_인원_합계": sum(v for k, v in tex.items() if k and str(k).startswith("죽")),
            "매운음식_제한_인원": sum(1 for m in meta.values() if m.get("no_spicy")),
            "주요_문제_상위3_인원": dict(issues.most_common(8)),
            "피할_식재료_사유_인원": dict(avoid.most_common(5)),
            "시작_월": month, "계절": season, "끼니당_예산": budget}


# ─────────────────────────── 4) LLM 판단 ───────────────────────────
SYSTEM_PROMPT = """당신은 요양원 급식을 총괄하는 임상 영양사입니다.
다목적 최적화가 만든 28일 공통 식단 후보 여러 개와 시설 어르신들의 상황 요약이 주어집니다.
후보는 모두 기본 영양 기준(f1 ≤ 0.3)을 통과했고, 개인별 대체찬·배식량 조정은 다음 단계에서 따로 합니다.
당신의 일은 이 시설에 가장 알맞은 후보 하나를 고르는 것입니다.

판단 기준 (중요한 순서):
1. 시설에 많은 질환·문제(예: 고혈압이 많으면 나트륨, 당뇨가 많으면 당류, 저체중·영양불량이 많으면 열량·단백질)에 맞는 후보
2. 영양 위반이 적은 후보 (f1, 하루 평균 영양이 기준 안인지)
3. 어르신이 잘 드실 후보 (시설 선호, 한 끼 조화, 다진찬 부적합 끼니가 적은지 — 다진찬 인원이 많을수록 중요)
4. 메뉴 반복이 적은 후보 (특히 같은 날·3일 안 반복)
5. 비용

규칙:
- 반드시 후보 id 중 하나를 고릅니다. 새 식단이나 메뉴를 만들지 않습니다.
- 후보끼리 비교할 때는 각 후보의 'A_대비' 판정(좋아진_점·나빠진_점·비슷함)을 그대로 따릅니다. 숫자를 직접 빼거나 비교하지 않습니다.
- '비슷함' 에 있는 항목은 장점이나 단점으로 쓰지 않습니다.
- tradeoffs 에는 고른 후보의 '나빠진_점' 중 중요한 것을 씁니다. A 를 골랐다면 다른 후보들의 '좋아진_점' 중 A 가 놓친 것을 씁니다.
- '기준_초과' 에 있는 영양소는 '적합하다', '적절하다' 고 쓰지 않습니다. 모든 후보가 초과하면 그 사실을 check_before_approval 에 적습니다.
- 이유에는 입력에 있는 숫자만 그대로 인용합니다. 입력에 없는 수치를 지어내거나 계산해 쓰지 않습니다.
- 약 이름·처방·진단·치료 효과를 말하지 않습니다.
- 규칙 선택(균형점) 후보와 다른 것을 고르면, 왜 그 후보보다 나은지 이유에 분명히 적습니다.
- 반드시 아래 JSON 한 개만 출력합니다.

{"choice": "B",
 "ranking": ["B", "A", "D"],
 "reasons": ["고른 이유 1 (숫자 인용)", "고른 이유 2"],
 "tradeoffs": "고른 후보가 다른 후보보다 불리한 점 1~2문장",
 "check_before_approval": ["영양사가 승인 전에 확인할 점"],
 "summary": "영양사에게 보여 줄 2문장 요약"}"""

_BANNED = re.compile(r"처방|치료제|완치")   # [2026-11-09] 복용·투약은 사실 서술("당뇨약 복용")이라 가리지 않음


def _key(name: str):
    """환경변수 → 없으면 backend/.env 다시 읽기 (돌봄 솔루션과 같은 방식)"""
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


def provider() -> str:
    return (_key("DIET_LLM_PROVIDER") or _key("LLM_PROVIDER") or "none").strip().lower()


def status() -> dict:
    p = provider()
    has = {"openai": bool(_key("OPENAI_API_KEY")), "anthropic": bool(_key("ANTHROPIC_API_KEY"))}
    return {"provider": p, "ready": p in has and has[p], "model": _model(p) if p in has else None,
            "prompt_version": PROMPT_VERSION}


def _model(p: str) -> str:
    if _key("DIET_LLM_MODEL"):
        return _key("DIET_LLM_MODEL")
    return (_key("OPENAI_MODEL") or "gpt-4o-mini") if p == "openai" else (_key("ANTHROPIC_MODEL") or "claude-sonnet-4-5")


def _extract_json(text: str) -> dict:
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("JSON 없음")
    return json.loads(text[s:e + 1])


_REASONING = re.compile(r"^(o\d|gpt-5|gpt-6)", re.I)
USAGE: list = []          # 호출 기록 (모델 비교용): {model, effort, in, out, sec}


def effort(model: str) -> str | None:
    """추론형 모델이면 추론 강도, 아니면 None (temperature 0 사용)"""
    if not _REASONING.match(model or ""):
        return None
    e = (_key("DIET_LLM_EFFORT") or "low").strip().lower()
    return e if e in ("none", "minimal", "low", "medium", "high", "xhigh", "max") else "low"


def _post_openai(httpx, key: str, req: dict):
    """모델마다 받는 파라미터가 달라서, 400 이 '지원하지 않는 값'이면 그 값만 고쳐 한 번 더 보낸다"""
    for _ in range(3):
        r = httpx.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                       json=req, timeout=TIMEOUT)
        if r.status_code != 400:
            r.raise_for_status()
            return r, req
        msg = r.text.lower()
        if "temperature" in msg and "temperature" in req:
            req = {k: v for k, v in req.items() if k != "temperature"}
        elif "reasoning_effort" in msg and req.get("reasoning_effort") == "none":
            req = {**req, "reasoning_effort": "low"}          # 예: gpt-6.1-sol 은 none 미지원
        elif "reasoning_effort" in msg and "reasoning_effort" in req:
            req = {k: v for k, v in req.items() if k != "reasoning_effort"}
        elif "response_format" in msg and "response_format" in req:
            req = {k: v for k, v in req.items() if k != "response_format"}   # JSON 은 프롬프트로 요구하고 있음
        else:
            r.raise_for_status()
    r.raise_for_status()
    return r, req


def _log_usage(model, eff, usage: dict, sec: float):
    USAGE.append({"model": model, "effort": eff, "in": usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
                  "out": usage.get("completion_tokens") or usage.get("output_tokens") or 0, "sec": round(sec, 1)})
    del USAGE[:-500]


def call_llm(user_payload: dict, p: str | None = None, system: str | None = None, max_tokens: int = 1500) -> tuple[dict, str]:
    """LLM 한 번 호출 → (JSON dict, "제공자:모델"). system 을 주면 다른 역할(예: 식단 검토자)로 쓸 수 있다"""
    system = system or SYSTEM_PROMPT
    p = p or provider()
    if p not in ("openai", "anthropic"):
        raise RuntimeError(f"AI 영양사 미설정 (DIET_LLM_PROVIDER / LLM_PROVIDER = {p})")
    import httpx
    model = _model(p)
    body = json.dumps(user_payload, ensure_ascii=False)
    if p == "openai":
        key = _key("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY 미설정")
        req = {"model": model, "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": body}]}
        eff = effort(model)
        if eff:
            req["reasoning_effort"] = eff                  # 추론형: temperature 대신 추론 강도
        else:
            req["temperature"] = 0
        t0 = time.time()
        r, req = _post_openai(httpx, key, req)
        data = r.json()
        _log_usage(model, req.get("reasoning_effort"), data.get("usage") or {}, time.time() - t0)
        label = f"openai:{model}" + (f"({req['reasoning_effort']})" if req.get("reasoning_effort") else "")
        return _extract_json(data["choices"][0]["message"]["content"]), label
    if p == "anthropic":
        key = _key("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 미설정")
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": model, "max_tokens": max_tokens, "temperature": 0, "system": system,
                             "messages": [{"role": "user", "content": body}]},
                       timeout=TIMEOUT)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        return _extract_json(text), f"anthropic:{model}"
    raise RuntimeError(f"알 수 없는 제공자: {p}")


def _clean(s, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return _BANNED.sub("○○", s)[:limit]


_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set:
    out = set()
    for m in _NUM.findall(text or ""):
        try:
            out.add(round(float(m.replace(",", "")), 1))
        except ValueError:
            pass
    return out


def unknown_numbers(res: dict, payload: dict) -> list:
    """이유·포기한 점·요약에 쓴 숫자 중 입력에 없는 것 (지어낸 수치 감지). 1자리 정수(개수·순번)는 제외"""
    allowed = _numbers(json.dumps(payload, ensure_ascii=False))
    text = " ".join(res.get("reasons", []) + [res.get("tradeoffs", ""), res.get("summary", "")])
    return sorted(n for n in _numbers(text) if n not in allowed and not (n.is_integer() and n < 10))


def validate(raw: dict, ids: list[str]) -> tuple[dict, list[str]]:
    """LLM 응답 검사 → (정리된 결과, 경고). 고른 id 가 후보에 없으면 ValueError"""
    warn = []
    choice = str(raw.get("choice", "")).strip().upper()
    if choice not in ids:
        raise ValueError(f"후보에 없는 선택: {raw.get('choice')!r}")
    rank = [str(x).strip().upper() for x in (raw.get("ranking") or [])]
    rank = [x for i, x in enumerate(rank) if x in ids and x not in rank[:i]]
    if not rank or rank[0] != choice:
        rank = [choice] + [x for x in rank if x != choice]
        warn.append("순위를 선택 결과에 맞춤")
    reasons = [_clean(x, 220) for x in (raw.get("reasons") or []) if str(x).strip()][:4]
    if not reasons:
        warn.append("이유 없음")
    return {"choice": choice, "ranking": rank, "reasons": reasons,
            "tradeoffs": _clean(raw.get("tradeoffs"), 300),
            "check_before_approval": [_clean(x, 160) for x in (raw.get("check_before_approval") or []) if str(x).strip()][:3],
            "summary": _clean(raw.get("summary"), 300)}, warn


def choose(problem, Xf, Ff, standard, context: dict, mode: str = "llm", caller=None, progress=None) -> dict:
    """→ {"index": 고른 파레토 해 번호, "selection": 화면·기록용 dict}
    mode = "llm" (AI 영양사) | "rule" (균형점 규칙). caller 는 테스트용 (payload → (raw, model))"""
    from .pipeline import menu_records, repair_repeats
    say = progress or (lambda *_: None)
    rule_i, rule_txt = select_balanced(Ff)
    if mode != "llm":
        return {"index": rule_i, "selection": {"mode": "rule", "rule": rule_txt}}

    say("AI 영양사: 후보 식단 비교 준비")
    short = shortlist(Ff)
    ids = [chr(65 + k) for k in range(len(short))]
    cands, view = [], []
    for cid, (i, tags) in zip(ids, short):
        chrom, _ = repair_repeats(problem, Xf[i])
        s = summarize(problem, chrom, standard)
        cands.append({"id": cid, "뽑힌_이유": tags, **s})
        view.append({"id": cid, "index": int(i), "tags": tags, "summary": s,
                     "menu": compact_menu(menu_records(problem, chrom))})
    sel = {"mode": "llm", "rule": rule_txt, "rule_choice": "A", "prompt_version": PROMPT_VERSION,
           "candidates": view, "context": context}
    if len(short) < 2:
        sel.update(mode="rule", fallback="비교할 후보가 1개뿐 → 규칙 선택")
        return {"index": rule_i, "selection": sel}

    payload = build_payload(context, cands)
    say(f"AI 영양사: 후보 {len(ids)}개 중 선택 중")
    t0 = time.time()
    try:
        res, warn, model = ask(payload, ids, caller)
    except Exception as e:                                   # 실패해도 설계는 계속 → 규칙 선택
        msg = str(e)[:160]
        sel.update(mode="rule", fallback=(f"{msg} → 규칙 선택" if msg.startswith("AI 영양사 미설정")
                                          else f"AI 선택 실패 → 규칙 선택 ({msg})"),
                   latency_sec=round(time.time() - t0, 1))
        return {"index": rule_i, "selection": sel}
    k = ids.index(res["choice"])
    sel.update(res, model=model, warnings=warn, agreed_with_rule=(res["choice"] == "A"),
               latency_sec=round(time.time() - t0, 1))
    return {"index": int(short[k][0]), "selection": sel}


def ask(payload: dict, ids: list, caller=None) -> tuple[dict, list, str]:
    """LLM 호출 + 검사. 입력에 없는 숫자를 쓰면 한 번 다시 묻고, 그래도 남으면 경고로 표시"""
    call = caller or call_llm
    raw, model = call(payload)
    res, warn = validate(raw, ids)
    bad = unknown_numbers(res, payload)
    if bad:
        retry = {**payload, "다시_확인": (f"앞선 답에 입력에 없는 숫자 {bad[:6]} 가 있었습니다. "
                                          "숫자는 입력(특히 A_대비)에 있는 값만 그대로 쓰세요.")}
        raw, model = call(retry)
        res, warn = validate(raw, ids)
        bad = unknown_numbers(res, payload)
        warn.append("숫자 확인 후 다시 답함")
        if bad:
            warn.append(f"입력에 없는 숫자: {bad[:6]}")
    return res, warn, model


if __name__ == "__main__":
    # 실제 LLM 연결 확인:  venv-win\Scripts\python -m diet.llm_select tests\llm_select_sample.json
    #   (합성 데이터로 만든 후보 요약 — 개인정보 없음). DIET_LLM_PROVIDER 와 API 키가 .env 에 있어야 함
    import sys
    src = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "tests/llm_select_sample.json", encoding="utf-8"))
    payload = build_payload(src["시설_상황"], src["후보"])
    ids = [c["id"] for c in payload["후보"]]
    print("설정:", status())
    if "--show" in sys.argv:
        print(json.dumps(payload["후보"][1]["A_대비"], ensure_ascii=False, indent=1))
    t0 = time.time()
    res, warn, model = ask(payload, ids)
    print(f"모델 {model} · {time.time() - t0:.1f}초 · 경고 {warn}")
    print(json.dumps(res, ensure_ascii=False, indent=1))
