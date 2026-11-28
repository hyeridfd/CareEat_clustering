# -*- coding: utf-8 -*-
"""저장소: Supabase(운영) · 로컬 CSV(오프라인 시험). 같은 메서드를 가진다.

테이블 (sql/ingredient_mapping.sql)
  mapping_ingredients     매핑 대상 식재료 (이름·사용량 — 검수 화면 정렬용)
  ingredient_product_map  매핑 기억. 키 (supplier, item_cd, ingredient_id)
  mapping_seen_products   한 번 판단한 상품 (다음 날부터는 새 상품만 판단)
  ingredient_price_daily  식재료별 하루 가격. 키 (ingredient_id, price_date)
  unit_conversions        밀도·개당 중량
  category_map            공급사 분류 ↔ 식약처 식품대분류
"""
import json
import os
from datetime import date, datetime, timezone

import pandas as pd

from . import config as C

HUMAN = {"approved", "rejected", "not_product"}
MAP_KEY = ["supplier", "item_cd", "ingredient_id"]
MAP_COLS = ["ingredient_id", "supplier", "item_cd", "score", "method", "status", "features", "reason",
            "model_version", "reviewed_by", "reviewed_at", "created_at", "updated_at"]
DAILY_COLS = ["ingredient_id", "price_date", "price_per_g", "supplier", "item_cd", "item_nm", "n_candidates",
              "price_per_g_28d", "hgreenfood_min", "hgreenfood_item_cd", "hgreenfood_item_nm", "hgreenfood_n",
              "sajo_min", "sajo_item_cd", "sajo_item_nm", "sajo_n"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jsonable(v):
    if isinstance(v, set):
        return sorted(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def clean_map_rows(rows: list[dict]) -> list[dict]:
    out = []
    now = _now()
    for r in rows:
        f = {k: _jsonable(v) for k, v in (r.get("features") or {}).items()}
        out.append({"ingredient_id": r["ingredient_id"], "supplier": r["supplier"], "item_cd": str(r["item_cd"]),
                    "score": r.get("score"), "method": r.get("method"), "status": r.get("status"),
                    "features": f, "reason": r.get("reason"), "model_version": r.get("model_version"),
                    "updated_at": now})
    return out


class BaseStore:
    def protect_human(self, rows: list[dict], keep_llm: bool = False) -> list[dict]:
        """사람이 정한 판정은 덮어쓰지 않는다. keep_llm=True 면 LLM 판정도 그대로 둔다 (--no-llm 으로 다시 돌릴 때)."""
        cur = self.load_map(columns=["supplier", "item_cd", "ingredient_id", "status", "method"])
        if cur.empty:
            return rows
        lock = cur["status"].isin(HUMAN)
        if keep_llm and "method" in cur.columns:
            lock |= cur["method"].astype(str).eq("llm")
        locked = {tuple(x) for x in cur[lock][MAP_KEY].astype(str).values}
        return [r for r in rows if (r["supplier"], str(r["item_cd"]), r["ingredient_id"]) not in locked]


# ═════════════════════════════ 로컬 CSV ═════════════════════════════
class LocalStore(BaseStore):
    def __init__(self, root: str = C.LOCAL_STORE):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _p(self, name):
        return os.path.join(self.root, f"{name}.csv")

    def _read(self, name, cols=None) -> pd.DataFrame:
        p = self._p(name)
        if not os.path.exists(p):
            return pd.DataFrame(columns=cols or [])
        d = pd.read_csv(p, dtype={"item_cd": str}, encoding="utf-8-sig", low_memory=False)
        return d

    def _write(self, name, df: pd.DataFrame):
        df.to_csv(self._p(name), index=False, encoding="utf-8-sig")

    def _upsert(self, name, rows: list[dict], key: list[str]):
        if not rows:
            return
        new = pd.DataFrame(rows)
        for c in new.columns:
            if new[c].map(lambda v: isinstance(v, (dict, list))).any():
                new[c] = new[c].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
        old = self._read(name)
        if len(old):
            for k in key:
                old[k], new[k] = old[k].astype(str), new[k].astype(str)
            keep_cols = [c for c in old.columns if c not in new.columns]
            if keep_cols:                                         # created_at 등 보존
                new = new.merge(old[key + keep_cols], on=key, how="left")
            old = old.set_index(key)
            new = new.set_index(key)
            old = old[~old.index.isin(new.index)]
            df = pd.concat([old, new]).reset_index()
        else:
            df = new
        self._write(name, df)

    # 식재료
    def upsert_ingredients(self, rows):
        self._upsert("mapping_ingredients", rows, ["ingredient_id"])

    def load_ingredients_table(self):
        return self._read("mapping_ingredients")

    # 매핑
    def load_map(self, columns=None, statuses=None) -> pd.DataFrame:
        d = self._read("ingredient_product_map", MAP_COLS)
        if statuses is not None and len(d):
            d = d[d["status"].isin(statuses)]
        if "features" in d.columns and (columns is None or "features" in columns):
            d["features"] = d["features"].map(lambda s: json.loads(s) if isinstance(s, str) and s else {})
        return d[columns] if columns else d

    def upsert_map(self, rows):
        rows = clean_map_rows(rows)
        now = _now()
        for r in rows:
            r.setdefault("created_at", now)
        self._upsert("ingredient_product_map", rows, MAP_KEY)

    def set_status(self, keys: list[tuple], status: str, reason: str, by: str | None = None):
        d = self._read("ingredient_product_map", MAP_COLS)
        if d.empty:
            return 0
        d["item_cd"] = d["item_cd"].astype(str)
        idx = d.set_index(MAP_KEY).index
        mask = idx.isin([(s, str(i), g) for s, i, g in keys])
        d.loc[mask, "status"] = status
        d.loc[mask, "reason"] = reason
        d.loc[mask, "updated_at"] = _now()
        if by:
            d.loc[mask, "reviewed_by"] = by
            d.loc[mask, "reviewed_at"] = _now()
            d.loc[mask, "method"] = "human"
        self._write("ingredient_product_map", d)
        return int(mask.sum())

    # 본 상품
    def seen_keys(self) -> set:
        d = self._read("mapping_seen_products")
        return set(zip(d["supplier"].astype(str), d["item_cd"].astype(str))) if len(d) else set()

    def add_seen(self, rows):
        self._upsert("mapping_seen_products", rows, ["supplier", "item_cd"])

    # 가격
    def load_daily(self, since: date | None = None) -> pd.DataFrame:
        d = self._read("ingredient_price_daily", DAILY_COLS)
        if len(d):
            d["price_date"] = pd.to_datetime(d["price_date"]).dt.date
            if since:
                d = d[d["price_date"] >= since]
        return d

    def upsert_daily(self, rows):
        self._upsert("ingredient_price_daily", [{**r, "price_date": str(r["price_date"])} for r in rows],
                     ["ingredient_id", "price_date"])

    # 표
    def load_conversions(self):
        return self._read("unit_conversions").to_dict("records")

    def load_category_map(self):
        return self._read("category_map").to_dict("records")

    def upsert_category_map(self, rows):
        self._upsert("category_map", rows, ["supplier", "lcls_nm", "mcls_nm", "food_group"])


# ═════════════════════════════ Supabase ═════════════════════════════
class SupabaseStore(BaseStore):
    PAGE = 1000
    CHUNK = 500

    def __init__(self, sb=None):
        if sb is None:
            import sys
            sys.path.insert(0, C.BACKEND)
            try:
                from dotenv import load_dotenv
                load_dotenv(os.path.join(C.BACKEND, ".env"))
            except Exception:                                  # noqa: BLE001
                pass
            from dependencies import get_supabase
            sb = get_supabase()
        self.sb = sb

    def _select(self, table, columns="*", filters=None, order=None) -> list[dict]:
        out, start = [], 0
        while True:
            q = self.sb.table(table).select(columns)
            for f in filters or []:
                q = getattr(q, f[0])(*f[1:])
            if order:
                q = q.order(order)
            chunk = q.range(start, start + self.PAGE - 1).execute().data or []
            out += chunk
            if len(chunk) < self.PAGE:
                return out
            start += self.PAGE

    def _upsert(self, table, rows, on_conflict):
        for i in range(0, len(rows), self.CHUNK):
            self.sb.table(table).upsert(rows[i:i + self.CHUNK], on_conflict=on_conflict).execute()

    def upsert_ingredients(self, rows):
        self._upsert("mapping_ingredients", rows, "ingredient_id")

    def load_ingredients_table(self):
        return pd.DataFrame(self._select("mapping_ingredients"))

    def _select_map_keyset(self, columns, statuses) -> list[dict]:
        """ingredient_product_map 을 기본키 순서(공급사 → 상품코드 → 식재료) 키셋 페이지로 읽는다.
        offset 페이지(range)는 표가 커질수록 느려져 statement timeout(57014)이 난다."""
        cols = columns.split(",") if columns != "*" else None
        need = ["supplier", "item_cd", "ingredient_id"]
        sel = columns if cols is None else ",".join(dict.fromkeys(cols + need))
        out = []
        for sup in C.SUPPLIERS:
            last, page = None, self.PAGE
            while True:
                q = self.sb.table("ingredient_product_map").select(sel).eq("supplier", sup)
                if statuses:
                    q = q.in_("status", list(statuses))
                if last:
                    ic, ig = last
                    q = q.or_(f'item_cd.gt."{ic}",and(item_cd.eq."{ic}",ingredient_id.gt."{ig}")')
                q = q.order("item_cd").order("ingredient_id").limit(page)
                try:
                    chunk = q.execute().data or []
                except Exception as e:                         # noqa: BLE001
                    if "57014" in str(e) and page > 100:      # 시간 초과면 페이지를 줄여 다시
                        page //= 2
                        continue
                    raise
                out += chunk
                if len(chunk) < page:
                    break
                last = (chunk[-1]["item_cd"], chunk[-1]["ingredient_id"])
        if cols is not None:
            out = [{k: r.get(k) for k in cols} for r in out]
        return out

    def load_map(self, columns=None, statuses=None) -> pd.DataFrame:
        d = pd.DataFrame(self._select_map_keyset(",".join(columns) if columns else "*", statuses))
        if d.empty:
            return pd.DataFrame(columns=columns or MAP_COLS)
        if "item_cd" in d.columns:
            d["item_cd"] = d["item_cd"].astype(str)
        return d

    def upsert_map(self, rows):
        self._upsert("ingredient_product_map", clean_map_rows(rows), "supplier,item_cd,ingredient_id")

    def set_status(self, keys, status, reason, by=None):
        """여러 쌍의 상태를 한 번에 바꾼다 (500건씩 upsert — 한 건씩 보내면 수천 건에 십수 분 걸림)."""
        now = _now()
        patch = {"status": status, "reason": reason, "updated_at": now}
        if by:
            patch.update(reviewed_by=by, reviewed_at=now, method="human")
        rows = [{"supplier": s, "item_cd": str(i), "ingredient_id": g, **patch} for s, i, g in keys]
        for k in range(0, len(rows), self.CHUNK):
            self.sb.table("ingredient_product_map").upsert(rows[k:k + self.CHUNK],
                                                           on_conflict="supplier,item_cd,ingredient_id").execute()
            if len(rows) > self.CHUNK:
                print(f"[mapping]   저장 {min(k + self.CHUNK, len(rows)):,}/{len(rows):,}", flush=True)
        return len(keys)

    def seen_keys(self) -> set:
        return {(r["supplier"], str(r["item_cd"])) for r in self._select("mapping_seen_products", "supplier,item_cd")}

    def add_seen(self, rows):
        self._upsert("mapping_seen_products", rows, "supplier,item_cd")

    def load_daily(self, since: date | None = None) -> pd.DataFrame:
        filters = [("gte", "price_date", since.isoformat())] if since else None
        d = pd.DataFrame(self._select("ingredient_price_daily", "*", filters))
        if d.empty:
            return pd.DataFrame(columns=DAILY_COLS)
        d["price_date"] = pd.to_datetime(d["price_date"]).dt.date
        return d

    def upsert_daily(self, rows):
        self._upsert("ingredient_price_daily", [{**r, "price_date": str(r["price_date"])} for r in rows],
                     "ingredient_id,price_date")

    def load_conversions(self):
        return self._select("unit_conversions")

    def load_category_map(self):
        return self._select("category_map")

    def upsert_category_map(self, rows):
        self._upsert("category_map", rows, "supplier,lcls_nm,mcls_nm,food_group")


def open_store(kind: str = "supabase"):
    return LocalStore() if kind == "local" else SupabaseStore()
