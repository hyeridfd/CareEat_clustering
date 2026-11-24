# -*- coding: utf-8 -*-
"""
통합 섭취 파일(대상자별_영양섭취량.xlsx)의 '메뉴별_상세' 시트 →
care/nutrition_data/facility_menus.json  (시설별 식단표 + 메뉴 1 g당 영양소)

통합 파일 계산식:  영양소 = (100 g당 영양성분 ÷ 100) × 배식량(g) × 섭취율(%) ÷ 100
→ 1 g당 영양소 = 영양소 ÷ 섭취량(g)  (메뉴마다 일정하므로 섭취량>0인 행의 중앙값을 쓴다)
영양성분 파일에 값이 없는 메뉴·영양소는 null 로 두고 앱에서도 합산에서 뺀다(통합 파일과 같은 규칙).

  python scripts/build_facility_menus.py "../식사/대상자별_영양섭취량.xlsx"
"""
import json
import sys
from pathlib import Path

import pandas as pd

FACILITY = {"요양원A": "NH001", "요양원B": "NH002"}
FIELDS = {  # 앱 영양 지표 키 ← 통합 파일 열
    "energy": "에너지(kcal)", "carb": "탄수화물(g)", "protein": "단백질(g)", "fat": "지방(g)",
    "fiber": "식이섬유(g)", "sugar": "당류(g)", "ca": "칼슘(mg)", "fe": "철(mg)", "p": "인(mg)",
    "k": "칼륨(mg)", "na": "나트륨(mg)", "zn": "아연(mg)", "mg": "마그네슘(mg)", "va": "비타민 A(μg RAE)",
    "vd": "비타민 D(μg)", "ve": "비타민 E(mg α-TE)", "vc": "비타민 C(mg)", "b1": "티아민(mg)",
    "b2": "리보플라빈(mg)", "b3": "니아신(mg)", "b6": "비타민 B6 / 피리독신(mg)", "folate": "엽산(μg DFE)",
    "b12": "비타민 B12(μg)", "chol": "콜레스테롤(mg)", "sfa": "포화지방산(g)", "water": "수분(g)",
}


def main(src, out):
    m = pd.read_excel(src, sheet_name="메뉴별_상세")
    m["day"] = m["일차"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    res = {"source": Path(src).name,
           "rule": "영양소 = 1g당 영양소 × 배식량(g) × 섭취율(%)/100, 값이 없는 영양소는 합산 제외",
           "facilities": {}}
    for fac, code in FACILITY.items():
        f = m[m["요양원"] == fac]
        plan = {}
        for (day, meal, slot), g in f.groupby(["day", "끼니", "분류"]):
            plan.setdefault(str(day), {}).setdefault(meal, {})[slot] = g["메뉴"].mode().iloc[0]
        dens = {}
        x = f[pd.to_numeric(f["섭취량(g)"], errors="coerce") > 0]
        for menu, g in x.groupby("메뉴"):
            eaten = g["섭취량(g)"].astype(float)
            d = {}
            for key, col in FIELDS.items():
                if col not in g:
                    d[key] = None
                    continue
                v = pd.to_numeric(g[col], errors="coerce") / eaten
                d[key] = None if v.notna().sum() == 0 else round(float(v.median()), 6)
            dens[menu] = d
        res["facilities"][code] = {"name": fac, "plan": plan, "per_g": dens}
        print(code, fac, "식단 칸", sum(len(s) for dd in plan.values() for s in dd.values()), "메뉴", len(dens))
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", out)


if __name__ == "__main__":
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parent.parent /
                                                     "care" / "nutrition_data" / "facility_menus.json")
    main(src, out)
