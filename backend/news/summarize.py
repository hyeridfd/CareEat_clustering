# -*- coding: utf-8 -*-
"""
수집한 기사 묶음을 한 번의 LLM 호출로 요약한다.

  1) 기사 목록(제목·언론사·카테고리·발췌)을 JSON 으로 만들어 한 번에 보낸다
  2) 기사별 2~3문장 요약 + 주요 기사 표시 + 무관한 기사 제외 + 그날의 브리핑 5줄을 받는다
  3) 가드레일: 인덱스 검증, 길이 제한, 기사에 없는 내용 방지를 위한 프롬프트 제약
  4) 키 미설정·호출 실패 시 발췌문을 그대로 쓰는 규칙 기반으로 대체 (절대 500 을 던지지 않는다)

care/solution.py 의 호출 방식(httpx 직접 + _key 재읽기)을 그대로 따른다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx

OPENAI_MODEL = os.getenv("NEWS_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
log = logging.getLogger("uvicorn.error")

MAX_ARTICLES = 40          # 한 번에 요약할 최대 기사 수
SUMMARY_MAX = 300          # 기사 요약 글자 수 상한
BRIEF_MAX = 80             # 브리핑 한 줄 글자 수 상한
BRIEF_LINES = 5

SYSTEM_PROMPT = """당신은 고령친화식품·돌봄 사업을 하는 팀의 뉴스 브리핑 담당자입니다.
오늘 수집된 기사 목록이 JSON 배열로 주어집니다. 각 항목에는 i(번호), title, press, category, excerpt 가 있습니다.

규칙:
1. 기사에 실제로 담긴 내용만 씁니다. 추측하거나 배경지식을 덧붙이지 않습니다. 근거가 부족하면 제목이 말하는 사실만 짧게 씁니다.
2. summary 는 2~3문장의 한국어 평서문입니다. "~라고 밝혔다" 같은 기사체 대신, 무슨 일이 있었고 왜 중요한지가 바로 읽히게 씁니다. 300자 이내.
3. 노인·고령자·돌봄·요양·고령친화식품·관련 정책과 무관한 기사(연예, 스포츠, 일반 지역 행사 등)는 drop 을 true 로 표시합니다.
4. key 는 그날 특히 중요한 기사에만 true 로 합니다. 전체에서 3~6건을 넘기지 않습니다. 제도 시행·정책 변화·주요 통계 발표·돌봄 및 고령친화식품 산업의 큰 움직임이 우선입니다.
5. briefing 은 그날 전체를 아우르는 5줄입니다. 각 줄은 한 문장, 80자 이내. 기사 제목을 나열하지 말고 "이 분야에서 무슨 일이 있었나"를 말합니다. 건질 내용이 적으면 5줄보다 적어도 됩니다.
6. 반드시 아래 JSON 한 개만 출력합니다.

{"articles": [{"i": 0, "summary": "...", "key": false, "drop": false}],
 "briefing": ["...", "..."]}"""


def _key(name: str):
    v = None
    if ENV_FILE.exists():
        try:
            from dotenv import dotenv_values
            v = (dotenv_values(ENV_FILE).get(name) or "").strip() or None
        except Exception:
            v = None
    return v or os.getenv(name) or None


def llm_status() -> dict:
    return {"openai_key": bool(_key("OPENAI_API_KEY")),
            "model": (_key("NEWS_MODEL") or _key("OPENAI_MODEL") or OPENAI_MODEL),
            "env_file": str(ENV_FILE), "env_file_exists": ENV_FILE.exists()}


def _extract_json(text: str) -> dict:
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e < 0:
        raise ValueError("JSON 없음")
    return json.loads(text[s:e + 1])


def _trim(s, limit: int) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:limit]


def _fallback(articles: list[dict]) -> tuple[list[dict], list[str], str]:
    """LLM 없이 — 발췌문을 요약 자리에 넣고 브리핑은 비운다."""
    out = [{**a, "summary": _trim(a.get("description"), SUMMARY_MAX), "is_key": False}
           for a in articles]
    return out, [], "rules"


def summarize(articles: list[dict]) -> tuple[list[dict], list[str], str]:
    """(요약이 붙은 기사 목록, 브리핑 줄 목록, 생성기 이름) 을 돌려준다."""
    if not articles:
        return [], [], "empty"

    subset = articles[:MAX_ARTICLES]
    key = _key("OPENAI_API_KEY")
    if not key:
        log.warning("OPENAI_API_KEY 미설정 — 뉴스 요약을 규칙 기반으로 대체합니다.")
        return _fallback(subset)

    payload = [{"i": i, "title": a["title"], "press": a.get("press", ""),
                "category": a.get("category", ""), "excerpt": _trim(a.get("description"), 300)}
               for i, a in enumerate(subset)]

    model = _key("NEWS_MODEL") or _key("OPENAI_MODEL") or OPENAI_MODEL
    try:
        r = httpx.post("https://api.openai.com/v1/chat/completions",
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "temperature": 0.2,
                             "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                          {"role": "user",
                                           "content": json.dumps(payload, ensure_ascii=False)}]},
                       timeout=TIMEOUT)
        r.raise_for_status()
        out = _extract_json(r.json()["choices"][0]["message"]["content"])
    except Exception as e:                                  # noqa: BLE001
        log.warning("뉴스 요약 LLM 호출 실패 (%s) — 규칙 기반으로 대체합니다.", e)
        return _fallback(subset)

    # ── 가드레일 ──────────────────────────────────────────────
    by_index = {}
    for row in (out.get("articles") or []):
        try:
            i = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(subset):
            by_index[i] = row

    kept: list[dict] = []
    key_count = 0
    for i, a in enumerate(subset):
        row = by_index.get(i, {})
        if row.get("drop") is True:
            continue
        is_key = bool(row.get("key")) and key_count < 6
        if is_key:
            key_count += 1
        kept.append({**a,
                     "summary": _trim(row.get("summary"), SUMMARY_MAX)
                                or _trim(a.get("description"), SUMMARY_MAX),
                     "is_key": is_key})

    if not kept:                                            # 전부 걸러졌으면 원본을 살린다
        log.warning("뉴스 요약이 모든 기사를 제외했습니다 — 규칙 기반으로 대체합니다.")
        return _fallback(subset)

    briefing = [_trim(x, BRIEF_MAX) for x in (out.get("briefing") or []) if _trim(x, BRIEF_MAX)]
    return kept, briefing[:BRIEF_LINES], f"openai:{model}"
