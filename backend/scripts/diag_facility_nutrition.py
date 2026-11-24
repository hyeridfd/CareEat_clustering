# -*- coding: utf-8 -*-
"""시설별 섭취 영양 계산이 왜 비는지 진단

  python scripts/diag_facility_nutrition.py NH002
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from care import engine, nutrition as nutri  # noqa: E402
from care.data import fetch_all, fetch_surveys  # noqa: E402
from dependencies import get_supabase  # noqa: E402

home = sys.argv[1] if len(sys.argv) > 1 else "NH002"
sb = get_supabase()
b, n, s = fetch_surveys(sb, home)
print(f"[{home}] 기초조사 {len(b)}행, 영양조사 {len(n)}행, 만족도 {len(s)}행")
if n:
    r = n[0]
    mp = r.get("meal_portions")
    mp = json.loads(mp) if isinstance(mp, str) else mp
    print("영양조사 예시:", r.get("elderly_id"), "| meal_portions 형식:", type(mp).__name__,
          "| 일자 키:", list((mp or {}).keys())[:6])
    if isinstance(mp, dict) and mp:
        d0 = next(iter(mp))
        print("  첫 일자 끼니:", {k: list(v.keys()) if isinstance(v, dict) else v for k, v in mp[d0].items()})
forms = {r["id"]: r.get("meal_form") for r in fetch_all(sb, "elderly_residents", eq={"nursing_home_id": home})}
print("식사형태 등록:", sum(1 for v in forms.values() if v), "/", len(forms))
df = engine.build_features(b, n, s, meal_forms=forms)
print("meal_log 있음:", int(df["meal_log"].apply(lambda x: isinstance(x, list) and len(x) > 0).sum()), "/", len(df),
      "| 영양 요약 있음:", int(df["nutrition"].apply(lambda x: isinstance(x, dict)).sum()))
print("facility_menus 에 시설 있음:", nutri.has_facility_table(home))
for key, row in df.iterrows():
    log = row["meal_log"]
    if isinstance(log, list) and log:
        cell = next((c for c in log if c.get("meal") in nutri.MAIN_MEALS), log[0])
        print("예시", key, "식사형태:", forms.get(row["elderly_id"]), "| 칸:", {k: cell.get(k) for k in ("day", "meal")})
        for it in cell.get("items", []):
            name, nut = nutri.facility_item_nutrients(home, cell.get("day"), cell.get("meal"), it.get("slot"),
                                                      it.get("g"), it.get("rate"), forms.get(row["elderly_id"]))
            print("   ", it.get("slot"), it.get("g"), it.get("rate"), "→", name, (nut or {}).get("energy"))
        break
