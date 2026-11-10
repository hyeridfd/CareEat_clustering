# -*- coding: utf-8 -*-
"""기초조사(basic_survey) 보유 질환 집계 — 요양원별 · 전체

  실행:  cd backend
         venv-win\\Scripts\\python scripts\\disease_summary.py
  결과:  화면 출력 + scripts/disease_summary.csv (요양원 × 질환 인원)
"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dependencies import get_supabase  # noqa: E402


def _list(v):
    if not v:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = [v]
    return [str(x).strip() for x in v if str(x).strip()]


def _all(sb, table, cols):
    out, start = [], 0
    while True:
        r = sb.table(table).select(cols).range(start, start + 999).execute().data
        out += r
        if len(r) < 1000:
            return out
        start += 1000


def main():
    sb = get_supabase()
    homes = {h["id"]: h["name"] for h in _all(sb, "nursing_homes", "id,name")}
    rows = _all(sb, "basic_survey", "elderly_id,nursing_home_id,diseases,diseases_etc")
    by_home = defaultdict(Counter)
    n_home = Counter()
    etc = defaultdict(Counter)
    multi = Counter()
    for r in rows:
        h = homes.get(r.get("nursing_home_id"), r.get("nursing_home_id") or "미상")
        ds = _list(r.get("diseases"))
        n_home[h] += 1
        real = [d for d in ds if d != "없음"]
        multi[min(len(real), 4)] += 1
        for d in set(ds) or {"(응답 없음)"}:
            by_home[h][d] += 1
            by_home["전체"][d] += 1
        if r.get("diseases_etc"):
            etc[h][str(r["diseases_etc"]).strip()] += 1
    n_home["전체"] = len(rows)

    for h in sorted(by_home, key=lambda x: (x != "전체", x)):
        n = n_home[h]
        print(f"\n■ {h} ({n}명)")
        for d, c in by_home[h].most_common():
            print(f"  {d:<40s} {c:>3}명 ({c / n * 100:4.1f}%)")
        if etc.get(h):
            print("  └ 기타 내용:", ", ".join(f"{k}({v})" for k, v in etc[h].most_common()))
    print("\n■ 보유 질환 수 (없음 제외):", {f"{k}{'+' if k == 4 else ''}개": v for k, v in sorted(multi.items())})

    import csv
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "disease_summary.csv")
    cols = sorted({d for c in by_home.values() for d in c}, key=lambda d: -by_home["전체"][d])
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["요양원", "인원"] + cols)
        for h in sorted(by_home, key=lambda x: (x != "전체", x)):
            w.writerow([h, n_home[h]] + [by_home[h].get(d, 0) for d in cols])
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
