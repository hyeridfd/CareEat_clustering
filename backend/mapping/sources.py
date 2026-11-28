# -*- coding: utf-8 -*-
"""입력 읽기: 매핑 대상 식재료(엑셀) · 공급사 상품(Supabase 또는 크롤러 CSV)."""
import glob
import os
from datetime import date

import pandas as pd

from . import config as C
from .normalize import Ingredient, parse_ingredient

# 크롤러 CSV 열 → Supabase 열
CSV_COLS = {
    "기준일": "last_seen", "단품코드": "item_cd", "단품명": "item_nm", "대분류": "lcls_nm", "중분류": "mcls_nm",
    "소분류": "scls_nm", "세분류코드": "dcls_cd", "세분류": "dcls_nm", "원산지": "origin", "세구분": "tax_type",
    "규격": "spec", "단위": "unit", "보관": "storage", "최소발주일": "min_order_day", "단가": "unit_price",
    "세포함단가": "unit_price_tax",
}
PRODUCT_COLS = ["supplier", "item_cd", "item_nm", "lcls_nm", "mcls_nm", "scls_nm", "dcls_nm", "origin", "tax_type",
                "spec", "unit", "storage", "unit_price", "unit_price_tax", "last_seen"]


# ─────────────────────────── 식재료 ───────────────────────────
def load_ingredients(path: str = C.TARGETS_XLSX) -> list[Ingredient]:
    df = pd.read_excel(path, dtype={"식품코드": str})
    return [parse_ingredient(r) for r in df.to_dict("records")]


def ingredient_rows(ings: list[Ingredient]) -> list[dict]:
    """mapping_ingredients 테이블 행 (검수 화면이 이름·사용량을 읽는다)."""
    return [{
        "ingredient_id": i.ingredient_id, "rep_name": i.rep_name, "names": " | ".join(i.names)[:4000],
        "food_code": i.food_code, "mfds_name": i.mfds_name, "food_group": i.food_group,
        "discard_pct": i.discard_pct, "usage_g": i.usage_g, "rank": i.rank,
        "product_status": "not_product" if i.not_product else "product",
    } for i in ings]


# ─────────────────────────── 상품 ───────────────────────────
def _finish(df: pd.DataFrame) -> pd.DataFrame:
    for c in PRODUCT_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[PRODUCT_COLS].copy()
    df["item_cd"] = df["item_cd"].astype(str)
    for c in ("unit_price", "unit_price_tax"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["last_seen"] = pd.to_datetime(df["last_seen"].astype(str), errors="coerce").dt.date
    df = df[~df["mcls_nm"].fillna("").isin(C.NON_FOOD_MCLS)]
    txt = [c for c in df.columns if c not in ("unit_price", "unit_price_tax", "last_seen")]
    df[txt] = df[txt].astype(object).where(df[txt].notna(), None)
    return df.drop_duplicates(["supplier", "item_cd"], keep="last").reset_index(drop=True)


def csv_snapshot_path(supplier: str, day: date | None, root: str = C.CRAWLER_DATA) -> str | None:
    d = os.path.join(root, supplier)
    if day is not None:
        p = os.path.join(d, f"{supplier}_prices_{day:%Y%m%d}.csv")
        return p if os.path.exists(p) else None
    p = os.path.join(d, f"{supplier}_prices_latest.csv")
    return p if os.path.exists(p) else None


def csv_snapshot_days(supplier: str, root: str = C.CRAWLER_DATA) -> list[date]:
    out = []
    for p in glob.glob(os.path.join(root, supplier, f"{supplier}_prices_2*.csv")):
        s = os.path.basename(p).split("_")[-1][:8]
        try:
            out.append(date(int(s[:4]), int(s[4:6]), int(s[6:8])))
        except ValueError:
            pass
    return sorted(out)


def load_products_csv(day: date | None = None, root: str = C.CRAWLER_DATA, paths: dict | None = None) -> pd.DataFrame:
    """크롤러 스냅샷 CSV. day 가 없으면 *_latest.csv. paths={supplier: 파일} 로 직접 줄 수도 있다."""
    frames = []
    for sup in C.SUPPLIERS:
        p = (paths or {}).get(sup) or csv_snapshot_path(sup, day, root)
        if not p:
            continue
        d = pd.read_csv(p, dtype=str, encoding="utf-8-sig").rename(columns=CSV_COLS)
        d["supplier"] = sup
        frames.append(d)
    if not frames:
        raise FileNotFoundError(f"크롤러 CSV 없음: {root} ({day})")
    return _finish(pd.concat(frames, ignore_index=True))


def load_products_supabase(sb, page: int = 1000) -> pd.DataFrame:
    rows = []
    for sup in C.SUPPLIERS:
        start = 0
        while True:
            chunk = (sb.table("supplier_prices_latest").select(",".join(PRODUCT_COLS)).eq("supplier", sup)
                     .order("item_cd").range(start, start + page - 1).execute().data or [])
            rows += chunk
            if len(chunk) < page:
                break
            start += page
    return _finish(pd.DataFrame(rows))


def latest_day(products: pd.DataFrame) -> dict:
    return {s: g["last_seen"].max() for s, g in products.groupby("supplier")}
