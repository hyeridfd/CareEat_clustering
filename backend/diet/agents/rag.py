# -*- coding: utf-8 -*-
"""영역 에이전트용 임상 근거 검색 (RAG)

  두 갈래로 근거 문단을 모은다.
    ① 연결 근거 (rule-linked) — 에이전트가 낸 문제·기준마다 guideline_rules.json 에 적힌 (문헌, 조항)
       문단을 그대로 가져온다. 결정적(deterministic)이라 같은 판단에는 늘 같은 근거가 붙는다.
    ② 검색 근거 (semantic)    — 그 에이전트 영역의 문헌 안에서만(맥락 격리) 의미 검색으로 더 찾는다.
       문제 제목·영양소로 질의를 만들고, 어르신 이름·ID 는 넣지 않는다.

  저장소(RAG_BACKEND)
    supabase (기본) — care_chunks 테이블 + match_care_chunks(only_sources) RPC. scripts/ingest_guidelines.py 로 적재
    local          — care/knowledge/docs/*.md 를 바로 읽어 글자 겹침으로 찾는다 (적재 전 점검·오프라인 시험용)
    supabase 가 실패하면 local 로 자동 전환한다. 근거가 없어도 식단 설계는 그대로 진행된다.

  사용
    from diet.agents.rag import evidence_for
    ev = evidence_for(assessment)          # Assessment 1개 (domain 에이전트 결과)
    ev["snippets"] → LLM 프롬프트용 [{"id": "E1", "출처": "...", "내용": "..."}]
    ev["refs"]     → 화면·보고서용 출처 목록
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger("uvicorn.error")

BACKEND = Path(__file__).resolve().parents[2]
DOCS = BACKEND / "care" / "knowledge" / "docs"
SOURCES = BACKEND / "care" / "knowledge" / "sources.json"

# 에이전트별로 볼 수 있는 문헌 (맥락 격리 — 당뇨 에이전트는 당뇨·약물 문헌만 검색)
AGENT_SOURCES = {
    "body":         ["ESPEN_GERIATRIC", "SARCOPENIA_KR", "KDRI2025", "MFDS_MEAL_STD", "LTC_MEAL_GUIDE"],
    "diabetes":     ["KDA_DM_2025", "MFDS_MEAL_STD", "DRUG_FOOD", "KDRI2025"],
    "hypertension": ["KSH_HTN_2026", "MFDS_MEAL_STD", "KDRI2025"],
    "cognition":    ["ESPEN_DEMENTIA", "BRAIN_DIET", "ESPEN_GERIATRIC"],
    "oral":         ["IDDSI", "ESPEN_GERIATRIC", "ESPEN_DEMENTIA"],
    "intake":       ["KDRI2025", "ESPEN_GERIATRIC", "LTC_MEAL_GUIDE"],
    "medication":   ["DRUG_FOOD", "MFDS_EASY"],
}
# 영역 기본 질의 (문제가 없어도 영역 근거를 한 번은 찾는다)
AGENT_QUERY = {
    "body":         "노인 에너지 단백질 필요량 저영양 선별",
    "diabetes":     "당뇨 의학영양요법 당류 포화지방 나트륨 단백질",
    "hypertension": "고혈압 소금 섭취 제한 칼륨 건강한 식사요법",
    "cognition":    "치매 어르신 식사 돕기 영양 강화 체중 관찰",
    "oral":         "삼킴 곤란 씹기 어려움 식사 형태 조정 점도",
    "intake":       "노인 영양소 섭취 부족 권장섭취량 충분섭취량",
    "medication":   "약물 식품 상호작용 식재료 제외 복약 시간",
}
NUT_KO = {"energy": "열량 에너지", "protein": "단백질", "sugar": "당류 첨가당", "sat_fat": "포화지방",
          "fat": "지방", "sodium": "나트륨 소금", "potassium": "칼륨", "fiber": "식이섬유"}

MAX_LINKED = int(os.getenv("DIET_RAG_LINKED", "4"))       # 연결 근거 최대 문단 수
MAX_SEARCH = int(os.getenv("DIET_RAG_SEARCH", "3"))       # 검색 근거 최대 문단 수
PER_QUERY = 2
SNIPPET_CHARS = int(os.getenv("DIET_RAG_SNIPPET_CHARS", "420"))
MIN_SIM = float(os.getenv("DIET_RAG_MIN_SIM", "0.30"))

_CACHE: dict = {}
_LOCAL: list | None = None
_SRC_META: dict | None = None


def backend() -> str:
    return (os.getenv("RAG_BACKEND") or "supabase").strip().lower()


def enabled() -> bool:
    return os.getenv("DIET_RAG_ENABLED", "1") not in ("0", "false", "False", "")


# ─────────────────────────── 문헌 메타 ───────────────────────────

def source_meta() -> dict:
    global _SRC_META
    if _SRC_META is None:
        try:
            _SRC_META = {s["id"]: s for s in json.load(open(SOURCES, encoding="utf-8"))["sources"]}
        except Exception:
            _SRC_META = {}
    return _SRC_META


def _label(sid: str) -> str:
    s = source_meta().get(sid) or {}
    return s.get("citation") or s.get("title") or sid


# ─────────────────────────── local 저장소 (docs/*.md 직접) ───────────────────────────

_PAGE = re.compile(r"<!--\s*p\.?\s*(\d+)\s*-->")


def _local_chunks() -> list[dict]:
    """docs/*.md → [{source_id, section, page, ord, text}] (적재 스크립트와 같은 기준: '## ' 제목 = section)"""
    global _LOCAL
    if _LOCAL is not None:
        return _LOCAL
    out = []
    for f in sorted(DOCS.glob("*.md")):
        if f.name.startswith("_"):
            continue
        sid, sec, page, ordn = f.stem, None, None, 0
        buf: list[str] = []

        def flush():
            nonlocal ordn
            body = "\n".join(buf).strip()
            body = re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()
            if sec and len(body) >= 20:
                out.append({"id": f"{sid}:{ordn}", "source_id": sid, "section": sec, "page": page, "ord": ordn, "text": body})
                ordn += 1

        raw = f.read_text(encoding="utf-8")
        raw = re.sub(r"<!--(?!\s*p\.?\s*\d+\s*-->).*?-->", "", raw, flags=re.S)   # 머리 주석 제거 (쪽 표시는 남김)
        for line in raw.splitlines():
            m = _PAGE.search(line)
            if m:
                page = int(m.group(1))
                continue
            h = re.match(r"^#{1,4}\s+(.*)", line)
            if h:
                flush()
                sec, buf = h.group(1).strip(), []
            else:
                buf.append(line)
        flush()
    _LOCAL = out
    return out


def _grams(t: str) -> set:
    t = re.sub(r"\s+", "", t.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _local_search(query: str, sources: list[str], k: int) -> list[dict]:
    q = _grams(query)
    rows = []
    for c in _local_chunks():
        if c["source_id"] not in sources:
            continue
        g = _grams(c["section"] + " " + c["text"][:600])
        sim = len(q & g) / (len(q) ** 0.5 * len(g) ** 0.5 + 1e-9)
        rows.append({**c, "similarity": round(sim, 3)})
    rows.sort(key=lambda r: -r["similarity"])
    return [r for r in rows[:k] if r["similarity"] > 0.05]


def _local_section(source: str, section: str) -> list[dict]:
    return [{**c, "similarity": 1.0} for c in _local_chunks() if c["source_id"] == source and c["section"] == section]


# ─────────────────────────── supabase 저장소 ───────────────────────────

def _sb():
    from dependencies import get_supabase
    return get_supabase()


def _sb_section(source: str, section: str) -> list[dict]:
    res = (_sb().table("care_chunks").select("id,source_id,section,page,ord,text")
           .eq("source_id", source).eq("section", section).order("ord").execute())
    return [{**r, "similarity": 1.0} for r in res.data or []]


def _sb_search(queries: list[str], sources: list[str], k: int) -> list[dict]:
    from care.retrieval import embed
    vecs = embed(queries)
    hits = {}
    for q, v in zip(queries, vecs):
        res = _sb().rpc("match_care_chunks", {"query_embedding": v, "match_count": k + 2,
                                              "min_similarity": MIN_SIM, "only_sources": sources}).execute()
        for r in (res.data or [])[:k]:
            if r["id"] not in hits or r["similarity"] > hits[r["id"]]["similarity"]:
                hits[r["id"]] = {**r, "query": q}
    return sorted(hits.values(), key=lambda r: -r["similarity"])


# ─────────────────────────── 질의·연결 ───────────────────────────

def _strip_numbers(t: str) -> str:
    """질의에서 개인 수치(BMI 17.9, 45% 등)를 뺀다 — 근거 검색은 일반 개념으로"""
    t = re.sub(r"\(.*?\)", " ", t)
    return re.sub(r"[\d.,%]+", " ", t).strip()


def _kdri_section(ctx: dict | None) -> str:
    """어르신 나이·성별에 맞는 KDRI 표 조항"""
    c = ctx or {}
    band = "75세 이상" if (c.get("age") or 80) >= 75 else "65~74세"
    return f"KDRI {band} {'남자' if c.get('female') == 0 else '여자'}"


def linked_sections(assessment, ctx: dict | None = None) -> list[tuple[str, str]]:
    """에이전트 결과의 문제·기준 → guideline_rules.json 이 가리키는 (문헌, 조항)
    약물 문제는 drug_food_rules.json 의 규칙 이름으로 DRUG_FOOD 문서의 조항을 찾는다."""
    from .domain import rules
    from .medication import kb
    R = rules()
    drug = {r["id"]: r["title"] for r in kb()["rules"]}
    out = []
    for i in assessment.issues:
        r = R["issues"].get(i.code)
        if r and r.get("section"):
            out.append((r["source"], r["section"]))
        elif i.code in drug:
            out.append(("DRUG_FOOD", f"약물-식품 {drug[i.code]}"))
        elif i.code.startswith("mfds:"):                  # 식약처 e약은요 제품 → 그 제품 조항
            pname = next((m["product"] for m in assessment.outputs.get("mfds_matched", [])
                          if f"mfds:{m['seq']}" == i.code), None)
            if pname:
                out.append(("MFDS_EASY", f"e약은요 {pname}"))
    for c in assessment.constraints:
        for key, r in R["constraints"].items():
            if key.split(".")[0] == assessment.agent and r["nutrient"] == c.nutrient and r["bound"] == c.bound and r.get("section"):
                out.append((r["source"], r["section"]))
    out = [(src, _kdri_section(ctx) if (src == "KDRI2025" and sec.startswith("KDRI 75세 이상 여자")) else sec)
           for src, sec in out]
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def build_queries(assessment) -> list[str]:
    qs = [AGENT_QUERY.get(assessment.agent, "")]
    for i in assessment.issues[:4]:
        nut = " ".join(NUT_KO.get(n, n) for n in (i.nutrients or []))
        qs.append(f"{_strip_numbers(i.title)} {nut}".strip())
    out, seen = [], set()
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:5]


# ─────────────────────────── 공개 함수 ───────────────────────────

def evidence_for(assessment, ctx: dict | None = None, sources: list[str] | None = None) -> dict:
    """Assessment 1개 (+ 그 어르신 맥락: 나이·성별로 KDRI 표 선택) → {"snippets", "refs", "linked", "backend", "queries"}
    실패해도 예외를 던지지 않는다 (빈 근거 + "error")."""
    if not enabled() or not assessment.active:
        return {"snippets": [], "refs": [], "linked": [], "backend": None, "queries": [], "error": None}
    srcs = sources or AGENT_SOURCES.get(assessment.agent, [])
    return retrieve(linked_sections(assessment, ctx), build_queries(assessment), srcs, ctx)


def retrieve(links: list, queries: list, srcs: list, ctx: dict | None = None, prefix: str = "E",
             max_linked: int | None = None, max_search: int | None = None) -> dict:
    """연결 조항(links: [(문헌, 조항)]) + 의미 검색(queries, srcs 문헌 안에서) → 근거 문단 묶음.
    영역 전문가(evidence_for)와 3단계 충돌 전문가(specialists.py)가 함께 쓴다. 예외를 던지지 않는다."""
    out = {"snippets": [], "refs": [], "linked": [], "backend": None, "queries": [], "error": None}
    if not enabled():
        return out
    ml, ms = max_linked or MAX_LINKED, max_search or MAX_SEARCH
    out["linked"], out["queries"] = [f"{s} · {sec}" for s, sec in links], list(queries)
    key = hashlib.sha1(json.dumps([srcs, links, queries, backend(), prefix, ml, ms, _kdri_section(ctx) if ctx else None],
                                  ensure_ascii=False).encode()).hexdigest()
    if key in _CACHE:
        return _CACHE[key]
    rows, used = [], backend()
    for attempt in ([used, "local"] if used != "local" else ["local"]):
        try:
            rows = []
            for s, sec in links:
                got = _sb_section(s, sec) if attempt == "supabase" else _local_section(s, sec)
                rows += [{**r, "kind": "linked"} for r in got[:1]]          # 조항당 첫 문단
                if len(rows) >= ml:
                    break
            got = (_sb_search(queries, srcs, PER_QUERY) if attempt == "supabase"
                   else [r for q in queries for r in _local_search(q, srcs, PER_QUERY)])
            # KDRI 연령·성별 표는 이 어르신에게 맞는 표만 (다른 연령·성별 표가 검색되면 판단을 흐림)
            mine = _kdri_section(ctx) if ctx else None
            got = [r for r in got if not (r["source_id"] == "KDRI2025" and re.match(r"KDRI (65~74세|75세 이상) (남자|여자)$", r.get("section") or "")
                                          and mine and r["section"] != mine)]
            have = {(r["source_id"], r["section"]) for r in rows}
            extra = []
            for r in sorted(got, key=lambda r: -r["similarity"]):
                if (r["source_id"], r["section"]) not in have:
                    have.add((r["source_id"], r["section"]))
                    extra.append({**r, "kind": "search"})
            rows += extra[:ms]
            used = attempt
            break
        except Exception as e:                       # 임베딩·네트워크·미적재
            out["error"] = f"{attempt}: {e!r}"[:200]
            log.warning("[diet-rag] %s 검색 실패 → %s", attempt, e)
    snippets, refs = pack(rows, prefix)
    out.update(snippets=snippets, refs=refs, backend=used)
    _CACHE[key] = out
    return out


def pack(rows: list, prefix: str = "E") -> tuple[list, list]:
    snippets, refs = [], []
    for n, r in enumerate(rows, 1):
        tag = f"{prefix}{n}"
        loc = " · ".join(x for x in [r.get("section") or "", f"p.{r['page']}" if r.get("page") else ""] if x)
        text = re.sub(r"\s+", " ", r["text"]).strip()[:SNIPPET_CHARS]
        snippets.append({"id": tag, "출처": f"{_label(r['source_id'])} — {loc}", "내용": text})
        refs.append({"tag": tag, "source_id": r["source_id"], "section": r.get("section"), "page": r.get("page"),
                     "kind": r.get("kind"), "similarity": round(float(r.get("similarity") or 0), 3),
                     "short": (source_meta().get(r["source_id"]) or {}).get("short") or r["source_id"]})
    return snippets, refs


def valid_citations(text: str, snippets: list, prefix: str = "E") -> tuple[str, list]:
    """LLM 출력의 [E3] 인용 중 실제로 준 근거 번호만 남긴다 → (고친 문장, 쓰인 번호)"""
    ok = {s["id"] for s in snippets}
    used = []

    def fix(m):
        tags = [t.strip() for t in m.group(1).split(",")]
        keep = [t for t in tags if t in ok]
        used.extend(t for t in keep if t not in used)
        return f"[{', '.join(keep)}]" if keep else ""
    return re.sub(r"\[((?:" + prefix + r"\d+\s*,?\s*)+)\]", fix, text or ""), used
