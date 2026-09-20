# -*- coding: utf-8 -*-
"""
근거 문헌 검색 (RAG)

  솔루션 생성 흐름에서의 위치
    care_rules  →  어떤 조치를 할지 (범위를 정한다)
    retrieval   →  그 조치의 근거 문단을 지침에서 찾아온다 (문구를 뒷받침한다)
    LLM         →  후보 조치 안에서 개인화하고, 지침 문단을 인용한다

  검색이 조치를 만들어내지 않는다. 가드레일(후보 rule_id 제한)은 그대로 유지된다.
  ※ 검색 질의에는 이름·ID 등 식별정보를 넣지 않는다.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

log = logging.getLogger("uvicorn.error")

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")   # 1536차원
EMBED_DIM = 1536
TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "30"))

MAX_QUERIES = int(os.getenv("RAG_QUERIES", "4"))        # 질의 수 (임베딩 1회에 묶어 보낸다)
PER_QUERY = int(os.getenv("RAG_PER_QUERY", "2"))        # 질의당 문단 수
MAX_SNIPPETS = int(os.getenv("RAG_SNIPPETS", "6"))      # 프롬프트에 넣을 문단 총수
SNIPPET_CHARS = int(os.getenv("RAG_SNIPPET_CHARS", "420"))
MIN_SIM = float(os.getenv("RAG_MIN_SIM", "0.33"))       # 절대 하한

# 상대 하한 — 한 질의 안에서 1등 대비 이 비율 아래는 버린다.
# 문단에 영문 권고문과 한국어 요지가 섞여 있어 유사도 절대값이 낮게 눌리므로,
# 절대 하한만으로는 잡음을 못 거른다. 1등과의 거리로 한 번 더 자른다.
REL_CUT = float(os.getenv("RAG_REL_CUT", "0.93"))


def enabled() -> bool:
    return os.getenv("RAG_ENABLED", "1") not in ("0", "false", "False", "")


# ─────────────────────────── 임베딩 ───────────────────────────

def _openai_key():
    from .solution import _key          # .env 재읽기 로직을 공유한다
    return _key("OPENAI_API_KEY")


def embed(texts: list[str]) -> list[list[float]]:
    """문장 목록 → 임베딩 벡터 목록 (한 번의 호출로 묶어 보낸다)."""
    key = _openai_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY 미설정 — 임베딩을 만들 수 없습니다.")
    r = httpx.post("https://api.openai.com/v1/embeddings",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.getenv("EMBED_MODEL", EMBED_MODEL), "input": texts},
                   timeout=TIMEOUT)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


# ─────────────────────────── 질의 만들기 ───────────────────────────

DX_QUERY = [
    (("당뇨", "diabet"), "고령자 당뇨 식사관리 혈당 간식 배분"),
    (("고혈압", "혈압"), "노인 고혈압 나트륨 제한 저염 식사"),
    (("신장", "콩팥", "투석"), "노인 만성콩팥병 단백질 칼륨 인 조절 식사"),
    (("치매", "인지"), "치매 어르신 식사 거부 식사 돕기 환경 조성"),
    (("빈혈",), "노인 빈혈 철분 섭취 식품"),
    (("골다공증", "골절"), "노인 골다공증 칼슘 비타민D 섭취"),
    (("변비",), "노인 변비 식이섬유 수분 섭취"),
    (("연하", "삼킴", "흡인"), "연하곤란 노인 점도 조절 식사 형태 안전한 식사 자세"),
    (("욕창",), "욕창 고령자 단백질 에너지 보충"),
]

NUT_QUERY = {
    "energy": "노인 에너지 섭취 부족 저체중 소량씩 자주 제공",
    "protein": "노인 단백질 권장량 근감소증 예방 단백질 식품",
    "fiber": "노인 식이섬유 섭취 늘리는 방법",
    "ca": "노인 칼슘 섭취 부족 유제품 대체",
    "vd": "노인 비타민D 부족 햇빛 식품",
    "fe": "노인 철분 섭취 부족",
    "k": "노인 칼륨 섭취",
    "na": "노인 나트륨 과다 섭취 줄이는 조리 배식 방법",
}

TEXTURE_QUERY = "요양시설 다진식 갈은식 제공 기준 식사 형태 단계"


def build_queries(features: dict, candidates: list, ctx_rules: dict) -> list[str]:
    """규칙·진단·부족 영양소에서 검색 질의를 만든다 (개인 식별정보 제외)."""
    qs: list[str] = []

    def add(q):
        if q and q not in qs:
            qs.append(q)

    # 1) 진단 질환 — 질환별 식사 조정 지침
    names = " ".join(str(x) for x in (features.get("diseases") or []))
    for keys, q in DX_QUERY:
        if any(k in names for k in keys):
            add(q)

    # 2) 기준 미달·초과 영양소
    pct = ctx_rules.get("nutrition_pct") or {}
    low = sorted(((v, k) for k, v in pct.items() if k != "na" and isinstance(v, (int, float)) and v < 80))
    for _, k in low[:2]:
        add(NUT_QUERY.get(k))
    if isinstance(pct.get("na"), (int, float)) and pct["na"] > 120:
        add(NUT_QUERY["na"])

    # 3) 식사 형태·삼킴
    if (features.get("texture_level") or 0) >= 1 or features.get("swallowing_difficulty") == 1:
        add(TEXTURE_QUERY)

    # 4) 그래도 비면 선택된 규칙 문장으로
    if not qs:
        for c in candidates[:2]:
            add(f"{c.get('category', '')} {c.get('staff', '')}".strip())

    return qs[:MAX_QUERIES]


# ─────────────────────────── 검색 ───────────────────────────

def _sources_by_id(sb, ids) -> dict:
    if not ids:
        return {}
    res = sb.table("care_sources").select("id,title,org,year,citation,url").in_("id", list(ids)).execute()
    return {r["id"]: r for r in (res.data or [])}


def search(queries: list[str]) -> list[dict]:
    """질의 목록 → 관련 문단 목록 (유사도 순, 문헌·문단 중복 제거)."""
    from dependencies import get_supabase
    sb = get_supabase()
    vecs = embed(queries)
    hits: dict[int, dict] = {}
    for q, v in zip(queries, vecs):
        # 상대 하한을 적용하려면 1등을 알아야 하므로 넉넉히 받아 온 뒤 자른다
        res = sb.rpc("match_care_chunks",
                     {"query_embedding": v, "match_count": PER_QUERY + 3, "min_similarity": MIN_SIM}).execute()
        rows = res.data or []
        if not rows:
            continue
        floor = rows[0]["similarity"] * REL_CUT
        for row in [r for r in rows if r["similarity"] >= floor][:PER_QUERY]:
            cur = hits.get(row["id"])
            if not cur or row["similarity"] > cur["similarity"]:
                hits[row["id"]] = {**row, "query": q}
    ranked = sorted(hits.values(), key=lambda r: -r["similarity"])[:MAX_SNIPPETS]
    meta = _sources_by_id(sb, {r["source_id"] for r in ranked})
    for r in ranked:
        r["source"] = meta.get(r["source_id"], {})
    return ranked


def _locator(row: dict) -> str:
    bits = [row.get("section") or "", f"p.{row['page']}" if row.get("page") else ""]
    return " · ".join(b for b in bits if b)


def guideline_context(features: dict, candidates: list, ctx_rules: dict):
    """LLM 프롬프트에 넣을 참고 지침 발췌와, 리포트에 쓸 출처 목록을 만든다.

    반환: (snippets_for_prompt, refs)
      snippets_for_prompt: [{"id": "G1", "출처": "...", "내용": "..."}]
      refs:                [{"tag": "G1", "source_id": ..., "title": ..., "citation": ..., "url": ...}]
    실패하면 ([], []) — 지침이 없어도 솔루션 생성은 그대로 진행된다.
    """
    if not enabled():
        return [], []
    try:
        queries = build_queries(features, candidates, ctx_rules)
        if not queries:
            return [], []
        rows = search(queries)
    except Exception as e:                       # 임베딩·네트워크·미적재 모두 여기로
        log.warning("[care] 지침 검색 생략: %r", e)
        return [], []

    snippets, refs = [], []
    for i, row in enumerate(rows, 1):
        tag = f"G{i}"
        src = row.get("source") or {}
        label = src.get("citation") or " ".join(str(x) for x in [src.get("title"), src.get("org"), src.get("year")] if x)
        loc = _locator(row)
        text = re.sub(r"\s+", " ", row["text"]).strip()[:SNIPPET_CHARS]
        snippets.append({"id": tag, "출처": f"{label}{(' — ' + loc) if loc else ''}", "내용": text})
        refs.append({"tag": tag, "source_id": row["source_id"], "title": src.get("title") or row["source_id"],
                     "org": src.get("org"), "year": src.get("year"), "citation": label,
                     "locator": loc, "url": src.get("url"), "similarity": round(float(row["similarity"]), 3)})
    return snippets, refs


def status() -> dict:
    """적재 현황 — 설정 화면에서 확인용."""
    out = {"enabled": enabled(), "embed_model": os.getenv("EMBED_MODEL", EMBED_MODEL),
           "openai_key": bool(_openai_key()), "sources": []}
    try:
        from dependencies import get_supabase
        res = get_supabase().table("care_knowledge_status").select("*").execute()
        out["sources"] = res.data or []
    except Exception as e:
        out["error"] = str(e)[:200]
    return out
