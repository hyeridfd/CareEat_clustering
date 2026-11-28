# -*- coding: utf-8 -*-
"""평가 세트 라벨링 파일 만들기.

    python -m mapping.eval.build_eval_set --store local            # mapping/eval/평가세트_라벨링.xlsx
    python -m mapping.eval.build_eval_set --store supabase --random 100 --seed 7

대상: 사용 중량 상위 300개(누적 92%) + 그 밖에서 무작위 100개(꼬리 성능).
식재료마다 공급사별 후보(승인·대기 전부 + 거절 중 점수 높은 것)를 늘어놓는다.
사람이 '정답' 열에 O(같은 식재료) / X(다름)를 적는다. 시스템 판정 열은 참고용이고, 라벨을 볼 때 가려도 된다.
목록에 없는 정답 상품은 '누락' 시트에 적는다 (후보 찾기 재현율 계산용).
"""
import argparse
import os
import random

import pandas as pd

from .. import config as C
from ..sources import load_ingredients
from ..store import open_store

OUT = os.path.join(C.HERE, "eval", "평가세트_라벨링.xlsx")
TRAPS = [("고추장", "청양고추"), ("배추김치", "배추"), ("새우살", "새우젓"), ("마늘(다진것)", "깐마늘"),
         ("돼지고기(목살)", "삼겹살"), ("단호박", "애호박"), ("방울토마토", "토마토"), ("국간장", "진간장"),
         ("미역(말린것)", "생미역")]


def build(store_kind="local", top=300, n_random=100, seed=7, per_supplier=10, out=OUT):
    ings = load_ingredients()
    pool = [i for i in ings if not i.not_product]
    head = [i for i in pool if i.rank <= top]
    tail = [i for i in pool if i.rank > top]
    random.Random(seed).shuffle(tail)
    chosen = head + tail[:n_random]
    group = {i.ingredient_id: ("상위300" if i.rank <= top else "무작위") for i in chosen}
    trap_ids = {i.ingredient_id for i in chosen for a, _ in TRAPS if i.rep_name == a}

    mp = open_store(store_kind).load_map()
    mp = mp[mp["ingredient_id"].isin(group)]
    rows = []
    for (iid, sup), g in mp.groupby(["ingredient_id", "supplier"]):
        keep = g[g["status"] != "auto_rejected"]
        rej = g[g["status"] == "auto_rejected"].sort_values("score", ascending=False).head(max(3, per_supplier - len(keep)))
        for r in pd.concat([keep, rej]).sort_values("score", ascending=False).to_dict("records"):
            f = r.get("features") or {}
            rows.append({"구분": group[iid], "함정": "Y" if iid in trap_ids else "", "식재료ID": iid,
                         "공급사": sup, "단품코드": str(r["item_cd"]), "상품명": f.get("item_nm"), "규격": f.get("spec"),
                         "원/kg": round(f["price_per_g"] * 1000) if f.get("price_per_g") else None,
                         "시스템판정": r["status"], "점수": r.get("score"), "근거": r.get("reason"), "정답(O/X)": "",
                         "메모": ""})
    meta = pd.DataFrame([{"식재료ID": i.ingredient_id, "순위": i.rank, "대표 원재료명": i.rep_name,
                          "식약처 식품명": i.mfds_name, "식품대분류": i.food_group, "사용량_g": i.usage_g,
                          "구분": group[i.ingredient_id]} for i in chosen])
    df = pd.DataFrame(rows).merge(meta[["식재료ID", "순위", "대표 원재료명"]], on="식재료ID", how="left")
    df = df.sort_values(["순위", "공급사", "점수"], ascending=[True, True, False])
    cols = ["구분", "함정", "순위", "식재료ID", "대표 원재료명", "공급사", "단품코드", "상품명", "규격", "원/kg",
            "정답(O/X)", "메모", "시스템판정", "점수", "근거"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame({"안내": [
            "정답(O/X): 그 상품을 사서 이 식재료로 그대로 쓸 수 있고 g당 가격을 써도 되면 O, 아니면 X.",
            "손질·썰기·냉동 차이는 O. 다른 품종·부위, 그 재료로 만든 가공품, 말린것↔생것은 X.",
            "시스템판정 열은 참고용 (라벨을 붙일 때 가려도 됨). 빈칸으로 둔 행은 평가에서 빠진다.",
            "목록에 없는 정답 상품을 알면 '누락' 시트에 식재료ID·공급사·단품코드를 적는다 (후보 찾기 재현율).",
            "평가: python -m mapping.evaluate --labels mapping/eval/평가세트_라벨링.xlsx",
        ]}).to_excel(w, sheet_name="안내", index=False)
        df[cols].to_excel(w, sheet_name="라벨", index=False)
        meta.sort_values("순위").to_excel(w, sheet_name="식재료", index=False)
        pd.DataFrame(columns=["식재료ID", "공급사", "단품코드", "메모"]).to_excel(w, sheet_name="누락", index=False)
        pd.DataFrame(TRAPS, columns=["식재료", "헷갈리는 상품"]).to_excel(w, sheet_name="함정", index=False)
    _style(out)
    return out, len(df), len(chosen)


def _style(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill
    wb = load_workbook(path)
    ws = wb["라벨"]
    widths = {"A": 8, "B": 6, "C": 6, "D": 28, "E": 16, "F": 11, "G": 11, "H": 46, "I": 22, "J": 9, "K": 9, "L": 18,
              "M": 14, "N": 7, "O": 50}
    for k, v in widths.items():
        ws.column_dimensions[k].width = v
    fill = PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2, min_col=11, max_col=11):
        for c in row:
            c.fill = fill
    ws.freeze_panes = "F2"
    ws.auto_filter.ref = ws.dimensions
    wb["안내"].column_dimensions["A"].width = 110
    wb.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--top", type=int, default=300)
    ap.add_argument("--random", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    out, n, k = build(a.store, a.top, a.random, a.seed, out=a.out)
    print(f"{out}: 식재료 {k}개, 후보 {n:,}행")


if __name__ == "__main__":
    main()
