# -*- coding: utf-8 -*-
"""
근거 문헌 검색(RAG)이 실제로 도는지 점검

    python scripts/check_rag.py
    python scripts/check_rag.py "치매 어르신 식사 거부 식사 돕기 환경 조성"

확인하는 것
    1) 키·설정        OPENAI_API_KEY / SUPABASE / RAG_ENABLED
    2) 적재 현황      문헌별 문단 수와 임베딩 수
    3) 검색 동작      실제 질의를 임베딩해 match_care_chunks 호출 → 걸린 문단 출력
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv                                  # noqa: E402
load_dotenv(BACKEND / ".env")

OK, NG = "  [OK]", "  [!!]"


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "치매 어르신 식사 거부 식사 돕기 환경 조성"

    # 1) 설정
    print("\n1) 설정")
    key = os.getenv("OPENAI_API_KEY")
    print(f"{OK if key else NG} OPENAI_API_KEY {'있음' if key else '없음 — 임베딩 불가'}")
    url, skey = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    print(f"{OK if url and skey else NG} SUPABASE {'설정됨' if url and skey else '없음'}")
    rag_on = os.getenv("RAG_ENABLED", "1") not in ("0", "false", "False", "")
    print(f"{OK if rag_on else NG} RAG_ENABLED = {os.getenv('RAG_ENABLED', '1(기본값)')}")
    print(f"{OK} 임베딩 모델 = {os.getenv('EMBED_MODEL', 'text-embedding-3-small')}")
    if not (key and url and skey):
        sys.exit("\n설정이 부족해 여기서 멈춥니다. backend/.env 를 확인하세요.")

    from supabase import create_client
    sb = create_client(url, skey)

    # 2) 적재 현황
    print("\n2) 적재 현황")
    try:
        rows = (sb.table("care_knowledge_status").select("*").execute().data) or []
    except Exception as e:
        sys.exit(f"{NG} care_knowledge_status 조회 실패 — sql/care_schema_v6.sql 을 실행했나요?\n     {e}")
    if not rows:
        sys.exit(f"{NG} 적재된 문헌이 없습니다. python scripts/ingest_guidelines.py 를 먼저 실행하세요.")
    total = 0
    for r in rows:
        c, e = r.get("chunks") or 0, r.get("embedded") or 0
        mark = OK if c and c == e else NG
        state = "정상" if c and c == e else ("문단 없음" if not c else f"임베딩 {c - e}개 누락")
        print(f"{mark} {r['id']:<18} 문단 {c:>3}  임베딩 {e:>3}  {state}  ({'사용' if r.get('enabled') else '비활성'})")
        total += e
    print(f"     합계 임베딩 {total}개")

    # 3) 검색
    print(f"\n3) 검색  질의: “{query}”")
    import httpx
    r = httpx.post("https://api.openai.com/v1/embeddings",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.getenv("EMBED_MODEL", "text-embedding-3-small"), "input": [query]},
                   timeout=30)
    if r.status_code != 200:
        sys.exit(f"{NG} 임베딩 호출 실패 HTTP {r.status_code}: {r.text[:160]}")
    vec = r.json()["data"][0]["embedding"]
    print(f"{OK} 질의 임베딩 생성 ({len(vec)}차원)")

    min_sim = float(os.getenv("RAG_MIN_SIM", "0.33"))
    rel_cut = float(os.getenv("RAG_REL_CUT", "0.93"))
    per_query = int(os.getenv("RAG_PER_QUERY", "2"))
    try:
        hits = (sb.rpc("match_care_chunks",
                       {"query_embedding": vec, "match_count": 8, "min_similarity": 0.15}).execute().data) or []
    except Exception as e:
        sys.exit(f"{NG} match_care_chunks 호출 실패 — 함수가 만들어졌나요?\n     {e}")

    if not hits:
        print(f"{NG} 걸린 문단이 하나도 없습니다. 질의를 바꿔 보세요.")
        return

    floor = max(hits[0]["similarity"] * rel_cut, min_sim)
    kept = [h for h in hits if h["similarity"] >= floor][:per_query]
    print(f"{OK} 후보 {len(hits)}개  →  채택 {len(kept)}개")
    print(f"     기준: 절대 하한 {min_sim}, 1등({hits[0]['similarity']:.3f}) 대비 {rel_cut} → 실제 하한 {floor:.3f}\n")

    for i, h in enumerate(hits, 1):
        loc = " · ".join(x for x in [h.get("section") or "", f"p.{h['page']}" if h.get("page") else ""] if x)
        mark = f"[G{len([k for k in kept if k['id'] == h['id']]) and kept.index(h) + 1}]" if h in kept else " 탈락 "
        print(f"  {mark:<6} 유사도 {h['similarity']:.3f}  {h['source_id']} — {loc}")
        print(f"         {h['text'][:100].strip()}…\n")

    if kept:
        print("검색은 정상입니다. 채택된 문단만 솔루션의 근거로 들어갑니다.")
    else:
        print(f"{NG} 채택된 문단이 없습니다. 이 질의에는 맞는 지침이 없다는 뜻이고, 솔루션은 지침 없이 만들어집니다.")


if __name__ == "__main__":
    main()
