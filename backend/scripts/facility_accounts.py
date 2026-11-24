# -*- coding: utf-8 -*-
"""요양원·담당자 계정 확인과 담당자 소속 시설 변경

  python scripts/facility_accounts.py                       # 목록
  python scripts/facility_accounts.py --move STAFF_ID --to NH002   # 담당자를 다른 시설로 옮김
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from care.data import fetch_all  # noqa: E402
from dependencies import get_supabase  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--move")
ap.add_argument("--to")
a = ap.parse_args()
sb = get_supabase()

if a.move and a.to:
    if not sb.table("nursing_homes").select("id").eq("id", a.to).execute().data:
        sys.exit(f"시설 {a.to} 가 없습니다.")
    sb.table("facility_staff").update({"nursing_home_id": a.to}).eq("id", a.move).execute()
    print(f"담당자 {a.move} → {a.to} 로 옮겼습니다. 다시 로그인하세요.")

homes = fetch_all(sb, "nursing_homes")
staff = fetch_all(sb, "facility_staff", columns="id,nursing_home_id,name,is_active")
res = Counter(r["nursing_home_id"] for r in fetch_all(sb, "elderly_residents", columns="nursing_home_id"))
basic = Counter(r["nursing_home_id"] for r in fetch_all(sb, "basic_survey", columns="nursing_home_id"))
print(f"{'시설ID':8} {'이름':20} {'어르신':>6} {'기초조사':>8}  담당자")
for h in sorted(homes, key=lambda r: str(r["id"])):
    st = [s["id"] + ("" if s.get("is_active") is not False else "(비활성)") for s in staff if s["nursing_home_id"] == h["id"]]
    print(f"{h['id']:8} {str(h.get('name') or ''):20} {res.get(h['id'], 0):>6} {basic.get(h['id'], 0):>8}  {', '.join(st) or '-'}")
