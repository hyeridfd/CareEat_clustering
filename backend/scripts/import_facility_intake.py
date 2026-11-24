# -*- coding: utf-8 -*-
"""
통합 섭취 파일(메뉴별_상세) → Supabase nutrition_survey.meal_portions / plate_waste 채우기
(마리아의 집처럼 섭취 기록을 앱 밖에서 정리한 시설용)

  # 1) 미리보기 (DB 변경 없음)
  python scripts/import_facility_intake.py --intake "대상자별_영양섭취량.xlsx" --home NH002
  # 2) 적용
  python scripts/import_facility_intake.py --intake "대상자별_영양섭취량.xlsx" --home NH002 --apply

규칙 (유형 모델 학습값과 똑같이 재현되도록)
- 요약집계 '제외' 끼니, 배식량·숫자 섭취율이 없는 메뉴는 넣지 않는다
- 잔반 등급 = (100 − 섭취율) / 25  → 0(다 먹음) ~ 4(모두 남김)
- 밥과 죽이 한 끼에 모두 기록된 경우가 있어 슬롯을 '밥'·'죽'으로 따로 넣는다 (앱 시설별 산출이 그대로 읽음)
- 이미 meal_portions 가 채워진 행은 건드리지 않는다 (--overwrite 로 덮어쓰기)
- elderly_residents.meal_form 이 비어 있으면 통합 파일의 식사형태로 채운다
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from care.data import fetch_all  # noqa: E402
from dependencies import get_supabase  # noqa: E402

FACILITY_NAME = {"NH001": "요양원A", "NH002": "요양원B"}
SLOT = {"밥": "밥", "죽": "죽", "국": "국/탕", "주찬": "주찬", "부찬1": "부찬1", "부찬2": "부찬2",
        "김치1": "김치1", "김치2": "김치2"}


def as_obj(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return {}
    return x or {}


def day_key_style(sb):
    """기존 영양조사 행의 일자 키 모양을 따라간다 ('1일차' / '1' / 'day1')."""
    for r in fetch_all(sb, "nutrition_survey", columns="meal_portions", page=50)[:50]:
        mp = as_obj(r.get("meal_portions"))
        if mp:
            k = next(iter(mp))
            if k.isdigit():
                return lambda d: str(d)
            if k.endswith("일차"):
                return lambda d: f"{d}일차"
            prefix = "".join(ch for ch in k if not ch.isdigit())
            return lambda d: f"{prefix}{d}"
    return lambda d: f"{d}일차"


def build(intake, home, dkey):
    m = pd.read_excel(intake, sheet_name="메뉴별_상세")
    m = m[(m["요양원"] == FACILITY_NAME[home]) & (m["요약집계_포함여부"] != "제외")].copy()
    m["rate"] = pd.to_numeric(m["섭취율(%)"], errors="coerce")
    m = m[m["rate"].notna() & m["배식량(g)"].notna()]
    m["day"] = m["일차"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    out, forms = {}, {}
    for eid, g in m.groupby("대상자ID"):
        mp, pw = {}, {}
        for _, r in g.iterrows():
            d, meal, slot = dkey(r["day"]), r["끼니"], SLOT.get(r["분류"], r["분류"])
            mp.setdefault(d, {}).setdefault(meal, {})[slot] = round(float(r["배식량(g)"]), 1)
            pw.setdefault(d, {}).setdefault(meal, {})[slot] = int(round((100 - float(r["rate"])) / 25))
        out[str(eid).strip()] = (mp, pw)
        forms[str(eid).strip()] = g["식사형태"].iloc[0]
    return out, forms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", required=True)
    ap.add_argument("--home", default="NH002")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()

    sb = get_supabase()
    dkey = day_key_style(sb)
    data, forms = build(a.intake, a.home, dkey)
    rows = {r["elderly_id"]: r for r in fetch_all(sb, "nutrition_survey", eq={"nursing_home_id": a.home})}
    res = {r["id"]: r for r in fetch_all(sb, "elderly_residents", eq={"nursing_home_id": a.home})}
    upd, skip, missing = [], [], []
    for eid, (mp, pw) in data.items():
        row = rows.get(eid)
        if row is None:
            missing.append(eid)
            continue
        if as_obj(row.get("meal_portions")) and not a.overwrite:
            skip.append(eid)
            continue
        upd.append((row, mp, pw))
    form_upd = [(eid, f) for eid, f in forms.items() if eid in res and not res[eid].get("meal_form")]

    print(f"[{a.home}] 통합 파일 대상 {len(data)}명")
    print(f"  섭취 기록 채울 행: {len(upd)}  | 이미 있어 건너뜀: {len(skip)} {skip[:5]}  | 영양조사 행 없음: {missing}")
    print(f"  식사형태 채울 어르신: {len(form_upd)}")
    if upd:
        row, mp, pw = upd[0]
        d0 = next(iter(mp))
        print("  예시", row["elderly_id"], d0, json.dumps(mp[d0], ensure_ascii=False)[:200])
        print("      잔반", json.dumps(pw[d0], ensure_ascii=False)[:200])
    if not a.apply:
        print("\n미리보기입니다. 적용하려면 --apply 를 붙여 다시 실행하세요.")
        return
    for row, mp, pw in upd:
        (sb.table("nutrition_survey").update({"meal_portions": mp, "plate_waste": pw})
           .eq("elderly_id", row["elderly_id"]).eq("nursing_home_id", a.home).execute())
    for eid, f in form_upd:
        sb.table("elderly_residents").update({"meal_form": f}).eq("id", eid).execute()
    print(f"\n적용 완료: 섭취 기록 {len(upd)}행, 식사형태 {len(form_upd)}명")


if __name__ == "__main__":
    main()
