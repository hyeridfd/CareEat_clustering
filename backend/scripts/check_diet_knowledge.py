# -*- coding: utf-8 -*-
"""식단 설계 근거 지식 점검 (1단계: 지식 기반)

    python -m scripts.check_diet_knowledge              # 전체
    python -m scripts.check_diet_knowledge --local      # Supabase 없이 docs/*.md 로만 검색 시험

  1) 규칙표(diet/data/guideline_rules.json)의 각 숫자가 가리키는 지침 조항이 실제 문서에 있는지
     + 일치/환산/불일치/근거약함/설계값 현황과, 근거와 다른 값 목록
  2) 문헌 적재 현황 (Supabase care_knowledge_status) — 새 문서(KDRI2025·IDDSI·DRUG_FOOD) 적재 여부,
     규칙표 조항이 DB 에도 같은 이름으로 있는지
  3) 영역 에이전트별 근거 검색 시험 (합성 어르신 1명, 식별정보 없음)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
from dotenv import load_dotenv                                  # noqa: E402
load_dotenv(BACKEND / ".env")

DOCS = BACKEND / "care" / "knowledge" / "docs"
OK, NG, WARN = "  [OK]", "  [!!]", "  [주의]"

SAMPLE = dict(age=82, female=1, height_cm=155, weight_kg=42, bmi=17.5, mna_risk=2, kmbi_score=40, kmbi_max=100,
              diseases=["당뇨병", "고혈압", "치매"], medications=["당뇨병약"], intake_rate=0.5, slot_rates={"국": 0.4},
              avg_day={"energy": 900, "protein": 30, "fiber": 10}, sbp=150, dbp=95, mmse=16, gds=9, meal_form="죽/다진찬",
              chewing_difficulty=True, swallowing_difficulty=True, med_records=[{"name": "와파린정"}],
              allergy_records=[{"allergen": "새우", "severity": "moderate"}])


def doc_sections() -> dict:
    out = {}
    for f in DOCS.glob("*.md"):
        out[f.stem] = {m.group(1).strip() for m in re.finditer(r"^#{1,4}\s+(.*)$", f.read_text(encoding="utf-8"), re.M)}
    return out


def check_rules():
    print("\n① 규칙표 ↔ 지침 문서 연결")
    from diet.agents.domain import rules
    R = rules()
    secs = doc_sections()
    srcs = {s["id"] for s in json.load(open(BACKEND / "care/knowledge/sources.json", encoding="utf-8"))["sources"]}
    broken, status, flagged = [], Counter(), []
    for grp in ("thresholds", "constraints", "issues"):
        for key, r in R[grp].items():
            if key.startswith("_"):
                continue
            status[r.get("status", "?")] += 1
            if r["source"] not in srcs:
                broken.append(f"{grp}.{key}: 문헌 {r['source']} 이 sources.json 에 없음")
            if r.get("section") and r["section"] not in secs.get(r["source"], set()):
                broken.append(f"{grp}.{key}: 조항 '{r['section']}' 이 docs/{r['source']}.md 에 없음")
            if r.get("status") in ("불일치", "근거약함") and grp != "issues" or (grp == "issues" and r.get("status") == "근거약함"):
                flagged.append((r["status"], f"{grp}.{key}", r.get("value"), r.get("note", "")))
    # [2026-11-10] 3단계 충돌 표·강제 제약 표 — 근거 조항(section)과 전문가 연결 조항(links)
    codes = set(R["issues"]) | {r["id"] for r in json.load(open(BACKEND / "diet/data/drug_food_rules.json", encoding="utf-8"))["rules"]}
    for grp in ("conflicts", "hard_overrides"):
        for key, r in (R.get(grp) or {}).items():
            if key.startswith("_"):
                continue
            status[r.get("status", "?")] += 1
            for s, sec in [(r["source"], r.get("section"))] + [tuple(x) for x in r.get("links") or []]:
                if s not in srcs:
                    broken.append(f"{grp}.{key}: 문헌 {s} 이 sources.json 에 없음")
                elif sec and sec not in secs.get(s, set()):
                    broken.append(f"{grp}.{key}: 조항 '{sec}' 이 docs/{s}.md 에 없음")
            for g in r.get("when") or []:
                for t in g:
                    if t.startswith("issue:") and t[6:] not in codes:
                        broken.append(f"{grp}.{key}: 없는 문제 code {t}")
    print(OK if not broken else NG, f"연결 끊김 {len(broken)}건")
    for b in broken:
        print("      -", b)
    print("    상태:", dict(status))
    print("\n    근거와 다른 값 · 근거가 약한 값 (결정 필요)")
    for st, key, val, note in sorted(flagged):
        print(f"    [{st}] {key} = {val}\n           {note}")
    return not broken


def check_db():
    print("\n② 문헌 적재 현황 (Supabase)")
    try:
        from dependencies import get_supabase
        sb = get_supabase()
        rows = sb.table("care_knowledge_status").select("*").execute().data or []
    except Exception as e:
        print(NG, f"Supabase 연결 실패: {e!r}"[:200])
        return False
    have = {r["id"]: r for r in rows}
    files = sorted(f.stem for f in DOCS.glob("*.md") if not f.name.startswith("_"))
    for sid in files:
        r = have.get(sid)
        if not r:
            print(NG, f"{sid}: 적재 안 됨 → python scripts/ingest_guidelines.py --only {sid}")
        else:
            mark = OK if r.get("embedded") == r.get("chunks") and r.get("chunks") else WARN
            print(mark, f"{sid}: 문단 {r.get('chunks')} · 임베딩 {r.get('embedded')}")
    # 규칙표 조항이 DB 에 같은 이름으로 있는지
    from diet.agents.domain import rules
    R = rules()
    want = {(r["source"], r["section"]) for g in ("constraints", "issues") for r in R[g].values()
            if isinstance(r, dict) and r.get("section")}
    miss = []
    for src, sec in sorted(want):
        got = sb.table("care_chunks").select("id").eq("source_id", src).eq("section", sec).limit(1).execute().data
        if not got:
            miss.append(f"{src} · {sec}")
    print(OK if not miss else WARN, f"규칙표 조항 {len(want)}개 중 DB 에 없는 것 {len(miss)}개")
    for m in miss[:15]:
        print("      -", m)
    return True


def check_search(local: bool):
    print(f"\n③ 영역별 근거 검색 시험 ({'local' if local else os.getenv('RAG_BACKEND', 'supabase')})")
    if local:
        os.environ["RAG_BACKEND"] = "local"
    from diet.agents import assess_residents
    from diet.agents.rag import evidence_for
    res = assess_residents({"SAMPLE": SAMPLE})["SAMPLE"]
    for a in res["agents"]:
        if not a.active:
            continue
        ev = evidence_for(a, SAMPLE)
        mark = OK if ev["snippets"] else NG
        print(mark, f"{a.label} — 저장소 {ev['backend']}, 연결 {sum(r['kind'] == 'linked' for r in ev['refs'])} · "
                    f"검색 {sum(r['kind'] == 'search' for r in ev['refs'])}" + (f" · 오류 {ev['error']}" if ev["error"] else ""))
        for s, r in zip(ev["snippets"], ev["refs"]):
            print(f"      {s['id']} {'연결' if r['kind'] == 'linked' else '검색'} {r['similarity']:.2f}  {r['short']} — {r['section']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="Supabase 없이 docs/*.md 로만 검색")
    a = ap.parse_args()
    check_rules()
    if not a.local:
        check_db()
    check_search(a.local)


if __name__ == "__main__":
    main()
