# -*- coding: utf-8 -*-
"""학습용 라벨링 파일 만들기 (사람이 O/X 확인 → 판정 모델 학습 + 평가).

    python -m mapping.eval.build_label_set                 # mapping/eval/학습세트_라벨링.xlsx
    python -m mapping.eval.build_label_set --store local --seed 7

모델이 배우기 좋은 쌍을 골라 담는다 (전체 13,000쌍이 아니라 약 1,500쌍):
  · 자동 승인 일부        — 규칙이 맞게 승인하는지 확인 (정답 O 예시)
  · 검수 대기(애매한 쌍)  — 점수 높은 것부터, 사조 상품을 섞어서 (모델이 가장 많이 배우는 부분)
  · 아깝게 거절된 쌍      — 거절 중 점수가 가장 높은 것 (헷갈리는 오답 예시)
  사용 중량 상위 100개는 더 많이, 101~300위는 조금, 그 밖에서 무작위 50개.
식재료별로 묶여 있어 한 식재료 후보들을 한 번에 보며 O/X 를 정할 수 있다.
"""
import argparse
import os
import random

import pandas as pd

from .. import config as C
from ..sources import load_ingredients
from ..store import open_store

OUT = os.path.join(C.HERE, "eval", "학습세트_라벨링.xlsx")
QUOTA = [(100, (2, 3, 2)), (300, (1, 2, 1))]        # (순위 이하, (자동승인, 대기, 아까운 거절))
TAIL = (50, (1, 1, 1))


def evidence_text(f: dict) -> str:
    """판정 근거를 사람이 읽을 수 있게."""
    rel = f.get("rel")
    parts = []
    if rel == "meat":
        pm = {"primary": "부위 일치", "secondary": "같은코드 다른 부위", "unknown": "부위 모름",
              "conflict": "부위 다름", "animal_conflict": "동물 다름"}.get(f.get("part_match"), "")
        parts.append(f"육류 · {pm}")
    elif rel in ("exact", "suffix", "prefix", "dcls"):
        name = {"exact": "이름 같음", "suffix": "이름이 식재료로 끝남", "prefix": "식재료로 시작 + 뒤에 말",
                "dcls": "세분류만 같음"}[rel]
        tier = "대표 이름" if f.get("tier") == "P" else "같은코드 이름"
        parts.append(f"{name}('{f.get('form')}', {tier})")
        if f.get("leftover"):
            parts.append(f"모르는 말 '{f['leftover']}'")
    else:
        parts.append(f"글자만 비슷({f.get('sim', 0):.2f})")
    for k, label in (("processed", "가공품"), ("variety", "품종·맛"), ("outranked", "다른 식재료가 주인"),
                     ("owned_elsewhere", "다른 식재료 대표 이름"), ("form_shared", "여러 식재료 공통 이름"),
                     ("ready_meal", "간편식")):
        v = f.get(k)
        if v:
            parts.append(label if v is True else f"{label} {v}")
    if f.get("state_ok") is False:
        parts.append(f"상태 불일치({f.get('state_why', '')[:30]})")
    if f.get("category") == "conflict":
        parts.append("분류 안 맞음")
    if f.get("price_range") == "out":
        parts.append("가격 범위 밖")
    elif f.get("price_range") == "none":
        parts.append("규격 환산 불가")
    return " · ".join(parts)


def build(store_kind="supabase", seed=7, out=OUT):
    rnd = random.Random(seed)
    ings = [i for i in load_ingredients() if not i.not_product]
    by_id = {i.ingredient_id: i for i in ings}
    head = {}
    for i in ings:
        for lim, q in QUOTA:
            if i.rank <= lim:
                head[i.ingredient_id] = q
                break
    tail = [i for i in ings if i.ingredient_id not in head]
    rnd.shuffle(tail)
    for i in tail[:TAIL[0]]:
        head[i.ingredient_id] = TAIL[1]

    mp = open_store(store_kind).load_map()
    mp = mp[mp["ingredient_id"].isin(head)]
    picked = []
    for iid, g in mp.groupby("ingredient_id"):
        na, npend, nrej = head[iid]
        a = g[g["status"] == "auto_approved"]
        picked.append(a.sample(min(na, len(a)), random_state=seed))
        p = g[g["status"] == "pending"].sort_values("score", ascending=False)
        ps = pd.concat([p[p["supplier"] == "sajo"].head((npend + 1) // 2), p[p["supplier"] != "sajo"].head(npend)])
        picked.append(ps.drop_duplicates(["supplier", "item_cd"]).head(npend))
        r = g[g["status"] == "auto_rejected"].sort_values("score", ascending=False)
        picked.append(r.head(nrej))
    sel = pd.concat(picked)

    rows = []
    for r in sel.to_dict("records"):
        f = r.get("features") or {}
        ing = by_id[r["ingredient_id"]]
        rows.append({
            "순위": ing.rank, "식재료(Recipe.title)": ing.rep_name, "식약처 식품명": ing.mfds_name or "",
            "공급사": "현대그린푸드" if r["supplier"] == "hgreenfood" else "사조푸디스트",
            "상품명": f.get("item_nm"), "규격": f.get("spec"),
            "원/kg": round(f["price_per_g"] * 1000) if f.get("price_per_g") else None,
            "판정 근거": evidence_text(f),
            "시스템 판정": {"auto_approved": "자동승인", "pending": "검수대기", "auto_rejected": "자동거절"}.get(r["status"], r["status"]),
            "시스템 제안": "O" if (r["status"] == "auto_approved" or (r["status"] == "pending" and (r.get("score") or 0) >= 0.6)) else "X",
            "정답(O/X)": "", "메모": "",
            "식재료ID": r["ingredient_id"], "supplier": r["supplier"], "단품코드": str(r["item_cd"]),
            "점수": round(float(r.get("score") or 0), 3),
        })
    df = pd.DataFrame(rows).sort_values(["순위", "공급사", "점수"], ascending=[True, True, False])
    df.insert(0, "번호", range(1, len(df) + 1))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame({"안내": [
            "목적: 공급사 상품 ↔ Recipe 매핑 판정 모델 학습 데이터. '정답(O/X)' 열만 채우면 된다.",
            "O = 그 상품을 사서 이 식재료로 그대로 쓸 수 있고, kg당 가격을 이 식재료 가격으로 써도 된다.",
            "X = 다른 식재료 / 다른 품종·부위 / 그 재료로 만든 가공품·양념·반찬 / 말린것↔생것이 다름.",
            "손질·썰기·냉동·포장 크기 차이는 O.  애매하면 비워 두고 메모 (빈칸은 학습에서 빠진다).",
            "'시스템 제안'에 동의하는 구간은 복사해서 '정답'에 붙여도 된다. 단, 붙인 행은 한 번씩 훑어볼 것.",
            "다 하면: python -m mapping.train   (부분만 해도 200행 이상이면 학습·평가 가능)",
        ]}).to_excel(w, sheet_name="안내", index=False)
        df.to_excel(w, sheet_name="라벨", index=False)
    _style(out)
    return out, len(df), df["식재료ID"].nunique()


def _style(path):
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = load_workbook(path)
    ws = wb["라벨"]
    widths = [6, 6, 18, 24, 12, 44, 20, 9, 48, 10, 10, 10, 18, 4, 4, 4, 6]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = wdt
    for c in ws[1]:
        c.font = Font(bold=True)
    col = {c.value: c.column for c in ws[1]}
    yellow = PatternFill("solid", fgColor="FFF2CC")
    grey = PatternFill("solid", fgColor="F2F2F2")
    dv = DataValidation(type="list", formula1='"O,X"', allow_blank=True)
    ws.add_data_validation(dv)
    prev, shade = None, False
    for r in range(2, ws.max_row + 1):
        name = ws.cell(r, col["식재료(Recipe.title)"]).value
        if name != prev:
            shade, prev = not shade, name
        for cc in range(1, ws.max_column + 1):
            if shade:
                ws.cell(r, cc).fill = grey
        ws.cell(r, col["정답(O/X)"]).fill = yellow
        ws.cell(r, col["정답(O/X)"]).alignment = Alignment(horizontal="center")
        dv.add(ws.cell(r, col["정답(O/X)"]))
    for key in ("식재료ID", "supplier", "단품코드"):
        ws.column_dimensions[ws.cell(1, col[key]).column_letter].hidden = True
    ws.freeze_panes = "G2"
    ws.auto_filter.ref = ws.dimensions
    wb["안내"].column_dimensions["A"].width = 110
    wb.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    out, n, k = build(a.store, a.seed, a.out)
    print(f"{out}: 식재료 {k}개, {n:,}행 — '정답(O/X)' 열을 채운 뒤 python -m mapping.train")


if __name__ == "__main__":
    main()
