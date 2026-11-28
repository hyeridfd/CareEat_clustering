# -*- coding: utf-8 -*-
"""엑셀에 적은 O/X 를 매핑 표에 사람 판정으로 저장하고, 가격·그래프를 다시 계산한다.

    python -m mapping.eval.apply_labels                       # eval 폴더의 가격상품확인_*.xlsx · 학습세트_라벨링.xlsx 전부
    python -m mapping.eval.apply_labels --files 가격상품확인_2026-11-27.xlsx
    python -m mapping.eval.apply_labels --no-reprice          # 저장만 (가격·그래프는 다음 실행 때)

O → approved (사람 승인),  X → rejected (사람 거절).  method = human, reviewed_by = excel:<파일명>.
사람 판정은 이후 run --full 로 다시 돌려도 바뀌지 않는다. 이미 같은 판정이면 건너뛴다.
"""
import argparse
import glob
import os

import pandas as pd

from .. import config as C
from ..store import open_store

SUP = {"현대그린푸드": "hgreenfood", "사조푸디스트": "sajo", "hgreenfood": "hgreenfood", "sajo": "sajo"}


def default_files() -> list[str]:
    d = os.path.join(C.HERE, "eval")
    return sorted(glob.glob(os.path.join(d, "가격상품확인_*.xlsx"))) + \
        [p for p in [os.path.join(d, "학습세트_라벨링.xlsx")] if os.path.exists(p)]


def read(path: str) -> pd.DataFrame:
    d = pd.read_excel(path, sheet_name="라벨", dtype={"단품코드": str})
    lab = d["정답(O/X)"].astype(str).str.strip().str.upper()
    d = d.assign(y=lab, ingredient_id=d["식재료ID"], supplier=d["supplier"].map(SUP), item_cd=d["단품코드"].astype(str),
                 memo=d.get("메모", pd.Series([""] * len(d))).fillna("").astype(str), file=os.path.basename(path))
    return d[d["y"].isin(["O", "X"])][["ingredient_id", "supplier", "item_cd", "y", "memo", "file"]]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--source", choices=["supabase", "csv"], default="supabase")
    ap.add_argument("--no-reprice", action="store_true")
    a = ap.parse_args(argv)
    files = [f if os.path.isabs(f) else (f if os.path.exists(f) else os.path.join(C.HERE, "eval", f))
             for f in (a.files or default_files())]
    if not files:
        raise SystemExit("O/X 를 적은 엑셀이 없습니다 (mapping/eval/가격상품확인_*.xlsx).")
    print(f"[mapping] 엑셀 {len(files)}개 읽는 중: {', '.join(os.path.basename(f) for f in files)}", flush=True)
    labels = pd.concat([read(f) for f in files], ignore_index=True).drop_duplicates(
        ["ingredient_id", "supplier", "item_cd"], keep="last")
    print(f"[mapping] O/X {len(labels):,}건 → 매핑 표 불러오는 중 (약 11만 행, 30초~1분)", flush=True)
    store = open_store(a.store)
    keys = set(zip(labels["supplier"], labels["item_cd"], labels["ingredient_id"]))
    cur = store.load_map(columns=["ingredient_id", "supplier", "item_cd", "status"])
    cur = cur[[k in keys for k in zip(cur["supplier"], cur["item_cd"].astype(str), cur["ingredient_id"])]]
    cur["item_cd"] = cur["item_cd"].astype(str)
    m = labels.merge(cur, on=["ingredient_id", "supplier", "item_cd"], how="left")
    missing = int(m["status"].isna().sum())
    todo = m[m["status"].notna() & ~((m["y"] == "O") & (m["status"] == "approved"))
             & ~((m["y"] == "X") & (m["status"] == "rejected"))]
    n_ok = n_x = 0
    for (y, file), g in todo.groupby(["y", "file"]):
        keys = list(zip(g["supplier"], g["item_cd"], g["ingredient_id"]))
        status = "approved" if y == "O" else "rejected"
        reason = "엑셀 확인: 같은 식재료" if y == "O" else "엑셀 확인: 다른 식재료"
        store.set_status(keys, status, reason, by=f"excel:{file}")
        n_ok += len(keys) if y == "O" else 0
        n_x += len(keys) if y == "X" else 0
    print(f"O/X {len(labels):,}건 읽음 → 사람 승인 {n_ok:,} · 사람 거절 {n_x:,} 저장"
          + (f" · 매핑 표에 없는 쌍 {missing}건 건너뜀" if missing else ""))
    if not a.no_reprice and len(labels):          # 이미 저장된 판정이어도 가격은 다시 맞춘다
        from ..run import run_day, today_kst
        r = run_day(today_kst(), source=a.source, store_kind=a.store, price_only=True, graph=True, use_llm=False,
                    graph_dry_run=a.store == "local")
        print("가격·그래프 다시 계산:", r.get("coverage"), r.get("graph"))


if __name__ == "__main__":
    main()
