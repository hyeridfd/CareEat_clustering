# -*- coding: utf-8 -*-
"""가격 상품 확인표 — 그래프·식단 가격으로 실제 뽑힌 상품을 사람이 확인한다.

    python -m mapping.eval.build_price_check              # mapping/eval/가격상품확인_<날짜>.xlsx
    python -m mapping.eval.build_price_check --next 2     # 공급사마다 다음으로 싼 후보 2개도 함께
    python -m mapping.eval.build_price_check --pending 0  # 미승인 후보 빼고 (승인 상품만)

식재료 × 공급사마다 '오늘 뽑힌 상품'(가장 싼 승인 상품)과 그다음 싼 승인 상품을 늘어놓는다.
틀린 매핑일수록 싸게 보여 뽑히기 쉬우므로, 이 표만 확인해도 그래프에 들어가는 가격의 정확도가 가장 크게 오른다.
'정답(O/X)' 를 채운 뒤:  python -m mapping.eval.apply_labels  → 거절 반영 + 가격·그래프 다시 계산
(X 로 거절하면 다음 상품이 뽑히므로, 확인표를 다시 만들어 새로 뽑힌 것만 보면 된다)
"""
import argparse
import os

import pandas as pd

from .. import config as C
from ..sources import load_ingredients
from ..store import open_store
from .build_label_set import _style, evidence_text

SUP_LABEL = {"hgreenfood": "현대그린푸드", "sajo": "사조푸디스트"}


def build(store_kind="supabase", n_next=2, out=None, n_pending=2, min_score=0.4, max_rank_missing=500):
    store = open_store(store_kind)
    ings = {i.ingredient_id: i for i in load_ingredients() if not i.not_product}
    daily = store.load_daily()
    if daily.empty:
        raise SystemExit("ingredient_price_daily 가 비어 있습니다. 먼저 python -m mapping.run 을 실행하세요.")
    day = daily["price_date"].max()
    today = daily[daily["price_date"] == day]
    chosen = {}
    for r in today.to_dict("records"):
        for sup in C.SUPPLIERS:
            cd = r.get(f"{sup}_item_cd")
            if cd is not None and str(cd) not in ("", "nan", "None"):
                chosen[(r["ingredient_id"], sup)] = str(cd).replace(".0", "")
    mp = store.load_map(statuses=["auto_approved", "approved"])
    mp["item_cd"] = mp["item_cd"].astype(str)
    mp["ppg"] = mp["features"].map(lambda f: (f or {}).get("price_per_g"))
    rows = []
    for (iid, sup), g in mp.groupby(["ingredient_id", "supplier"]):
        if iid not in ings or (iid, sup) not in chosen:
            continue
        sel = chosen[(iid, sup)]
        g = g.dropna(subset=["ppg"]).sort_values("ppg")
        g = g.assign(_nm=g["features"].map(lambda f: (f or {}).get("item_nm")), _p=g["ppg"].round(3))
        first = g[g["item_cd"] == sel]
        rest = g[g["item_cd"] != sel]
        if len(first):                                  # 이름·가격이 같은 다른 코드는 한 줄만
            rest = rest[~((rest["_nm"] == first["_nm"].iloc[0]) & (rest["_p"] == first["_p"].iloc[0]))]
        top = pd.concat([first, rest.drop_duplicates(["_nm", "_p"]).head(n_next)])
        for rank, r in enumerate(top.to_dict("records"), start=1):
            f = r.get("features") or {}
            ing = ings[iid]
            rows.append({
                "순위": ing.rank, "식재료(Recipe.title)": ing.rep_name, "식약처 식품명": ing.mfds_name or "",
                "공급사": SUP_LABEL.get(sup, sup), "구분": "오늘 가격" if r["item_cd"] == sel else f"다음 후보{rank - 1}",
                "상품명": f.get("item_nm"), "규격": f.get("spec"),
                "원/kg": round(r["ppg"] * 1000) if r["ppg"] else None,
                "판정 근거": evidence_text(f),
                "판정": {"auto_approved": "자동승인", "approved": "사람승인"}.get(r["status"], r["status"]),
                "정답(O/X)": "O" if r["status"] == "approved" else "", "메모": "",
                "식재료ID": iid, "supplier": sup, "단품코드": r["item_cd"], "점수": round(float(r.get("score") or 0), 3),
            })
    # ── 미승인 후보 (검수 대기): 오늘 가격보다 싼 것, 그리고 가격이 아예 없는 식재료·공급사의 상위 후보 ──
    sel_ppg = {(r["식재료ID"], r["supplier"]): r["원/kg"] for r in rows if r["구분"] == "오늘 가격"}
    if n_pending:
        pend = store.load_map(statuses=["pending"])
        pend["item_cd"] = pend["item_cd"].astype(str)
        pend["ppg"] = pend["features"].map(lambda f: (f or {}).get("price_per_g"))
        pend = pend[pend["ingredient_id"].isin(ings) & (pend["score"].astype(float) >= min_score)]
        for (iid, sup), g in pend.groupby(["ingredient_id", "supplier"]):
            cur = sel_ppg.get((iid, sup))
            if cur is not None:
                g = g[g["ppg"].notna() & (g["ppg"] * 1000 < cur * 0.999)].sort_values("ppg")   # 지금 가격보다 싼 것
                kind = "미승인(더 쌈)"
            else:
                if ings[iid].rank > max_rank_missing:
                    continue
                g = g.sort_values(["score", "ppg"], ascending=[False, True])                    # 가격 없는 자리
                kind = "미승인(가격 없음)"
            for r in g.head(n_pending).to_dict("records"):
                f = r.get("features") or {}
                ing = ings[iid]
                rows.append({
                    "순위": ing.rank, "식재료(Recipe.title)": ing.rep_name, "식약처 식품명": ing.mfds_name or "",
                    "공급사": SUP_LABEL.get(sup, sup), "구분": kind, "상품명": f.get("item_nm"), "규격": f.get("spec"),
                    "원/kg": round(r["ppg"] * 1000) if pd.notna(r["ppg"]) and r["ppg"] else None, "판정 근거": evidence_text(f),
                    "판정": f"검수대기({r.get('reason') or ''})"[:60], "정답(O/X)": "", "메모": "",
                    "식재료ID": iid, "supplier": sup, "단품코드": r["item_cd"], "점수": round(float(r.get("score") or 0), 3),
                })
    order = {"오늘 가격": 0, "미승인(더 쌈)": 1, "미승인(가격 없음)": 2}
    df = pd.DataFrame(rows)
    df["_o"] = df["구분"].map(lambda k: order.get(k, 3))
    df = df.sort_values(["순위", "공급사", "_o", "원/kg"]).drop(columns="_o")
    df.insert(0, "번호", range(1, len(df) + 1))
    if out is None:                                     # 같은 이름이 있으면(엑셀에서 열려 있을 수 있음) _2, _3 …
        base = os.path.join(C.HERE, "eval", f"가격상품확인_{day}")
        out, k = f"{base}.xlsx", 2
        while os.path.exists(out):
            out, k = f"{base}_{k}.xlsx", k + 1
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame({"안내": [
            f"기준일 {day}. 식재료·공급사마다 오늘 가격으로 뽑힌 상품('오늘 가격')과 그다음 싼 승인 상품을 보여 준다.",
            "'미승인(더 쌈)': 검수 대기 상품 중 오늘 가격보다 싼 것 → 같은 식재료면 O (승인되면 그게 새 최저가).",
            "'미승인(가격 없음)': 가격이 없는 식재료·공급사의 검수 대기 후보 → 맞는 것에 O 하면 가격이 생긴다.",
            "'정답(O/X)': O = 이 식재료로 그대로 쓸 수 있고 kg당 가격을 이 식재료 가격으로 써도 됨, X = 아님.",
            "사용 중량 순으로 정렬돼 있다. 위(상위 식재료)부터 하면 영향이 가장 크다. 모르면 비워 둔다.",
            "다 하면: python -m mapping.eval.apply_labels   → O=사람 승인, X=거절로 저장 + 가격·그래프 다시 계산",
            "X 로 거절된 자리에는 다음 상품이 올라온다 → 확인표를 다시 만들어 새로 '오늘 가격'이 된 행만 보면 된다.",
            "여기서 채운 O/X 는 python -m mapping.train 의 학습 데이터로도 쓰인다.",
        ]}).to_excel(w, sheet_name="안내", index=False)
        df.to_excel(w, sheet_name="라벨", index=False)
    _style(out)
    return out, len(df), df["식재료ID"].nunique()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--next", type=int, default=2, help="공급사마다 함께 보여 줄 다음 후보 수")
    ap.add_argument("--pending", type=int, default=2, help="식재료·공급사마다 보여 줄 미승인 후보 수 (0 = 안 보임)")
    ap.add_argument("--min-score", type=float, default=0.4, help="미승인 후보 최소 점수")
    ap.add_argument("--max-rank", type=int, default=500, help="'가격 없음' 후보를 보여 줄 식재료 사용량 순위 상한")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out, n, k = build(a.store, a.next, a.out, a.pending, a.min_score, a.max_rank)
    print(f"{out}: 식재료 {k}개, {n:,}행 — '정답(O/X)' 를 채운 뒤 python -m mapping.eval.apply_labels")


if __name__ == "__main__":
    main()
