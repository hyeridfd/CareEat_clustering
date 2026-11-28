# -*- coding: utf-8 -*-
"""식자재 화면 '매핑 검수' 탭 API  (main.py: app.include_router(mapping_review.router, prefix="/api/prices/mapping"))

읽기는 로그인한 담당자·관리자 모두, 승인·거절은 관리자만 (단가 매핑은 전 시설 공통이라).

  GET  /queue                       검수 대기 식재료 목록 (사용 중량 큰 순)
  GET  /ingredient/{ingredient_id}  식재료 하나의 후보 상품·근거·가격
  POST /review                      한 쌍 승인/거절  {ingredient_id, supplier, item_cd, decision, reason}
  POST /review/bulk                 여러 쌍 한 번에  {items: [...]}
  POST /ingredient/{id}/status      식재료를 '상품 아님'(육수 등)으로 표시하거나 되돌림
  GET  /stats                       상태별 건수·대기열 길이·최근 가격 연결률
  GET  /missing                     가격 없는 식재료 (사용 중량 큰 순)
"""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Security
from pydantic import BaseModel, Field

from dependencies import get_supabase, require_admin
from mapping.config import OPTIMIZE_COL
from routers.prices import SUPPLIERS, require_viewer, shape, _latest_days

router = APIRouter()
APPROVED = ["approved", "auto_approved"]


class ReviewIn(BaseModel):
    ingredient_id: str
    supplier: str
    item_cd: str
    decision: Literal["approve", "reject"]
    reason: Optional[str] = Field(None, max_length=300)


class BulkIn(BaseModel):
    items: list[ReviewIn] = Field(..., max_length=200)


class StatusIn(BaseModel):
    product_status: Literal["product", "not_product"]


def _all(make_query, page: int = 1000) -> list:
    """PostgREST 기본 상한(1000행)을 넘는 조회. make_query() 는 매번 새 쿼리를 만든다."""
    out, start = [], 0
    while True:
        chunk = make_query().range(start, start + page - 1).execute().data or []
        out += chunk
        if len(chunk) < page:
            return out
        start += page


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/queue")
def queue(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
          q: str = Query("", max_length=40), user: dict = Security(require_viewer)):
    sb = get_supabase()
    qry = sb.table("mapping_queue").select("*", count="exact").order("usage_g", desc=True)
    if q.strip():
        qry = qry.ilike("rep_name", f"%{q.strip()}%")
    res = qry.range(offset, offset + limit - 1).execute()
    items = res.data or []
    ids = [r["ingredient_id"] for r in items]
    prices = {}
    if ids:
        for r in (sb.table("ingredient_price_latest").select(f"ingredient_id,{OPTIMIZE_COL},price_date")
                  .in_("ingredient_id", ids).execute().data or []):
            prices[r["ingredient_id"]] = r
    for r in items:
        p = prices.get(r["ingredient_id"]) or {}
        r["price_per_kg"] = round(float(p[OPTIMIZE_COL]) * 1000) if p.get(OPTIMIZE_COL) else None
        r["has_price"] = r["price_per_kg"] is not None
    return {"total": res.count, "items": items}


@router.get("/ingredient/{ingredient_id}")
def ingredient(ingredient_id: str, include_rejected: bool = False, user: dict = Security(require_viewer)):
    sb = get_supabase()
    meta = sb.table("mapping_ingredients").select("*").eq("ingredient_id", ingredient_id).limit(1).execute().data
    if not meta:
        raise HTTPException(404, "식재료가 없습니다.")
    q = sb.table("ingredient_product_map").select("*").eq("ingredient_id", ingredient_id)
    if not include_rejected:
        q = q.neq("status", "auto_rejected")
    maps = q.order("score", desc=True).limit(300).execute().data or []
    # 상품 현재 단가 붙이기
    latest_day = _latest_days(sb)
    prods = {}
    for sup in SUPPLIERS:
        cds = [m["item_cd"] for m in maps if m["supplier"] == sup]
        for i in range(0, len(cds), 150):
            for r in (sb.table("supplier_prices_latest").select("*").eq("supplier", sup)
                      .in_("item_cd", cds[i:i + 150]).execute().data or []):
                prods[(sup, r["item_cd"])] = shape(r, latest_day)
    order = {"pending": 0, "approved": 1, "auto_approved": 2, "rejected": 3, "auto_rejected": 4, "not_product": 5}
    cands = []
    for m in maps:
        f = m.get("features") or {}
        p = prods.get((m["supplier"], m["item_cd"]), {})
        cands.append({
            "supplier": m["supplier"], "supplier_label": SUPPLIERS.get(m["supplier"], m["supplier"]),
            "item_cd": m["item_cd"], "item_nm": p.get("item_nm") or f.get("item_nm"),
            "spec": p.get("spec") or f.get("spec"), "unit": p.get("unit") or f.get("unit"),
            "category": p.get("category"), "unit_price_tax": p.get("unit_price_tax"),
            "price_per_kg": round(f["price_per_g"] * 1000) if f.get("price_per_g") else None,
            "pack_g": f.get("pack_g"), "pack_basis": f.get("pack_basis"),
            "on_sale": bool(p) and not p.get("stale"), "last_seen": p.get("last_seen"),
            "status": m["status"], "score": m.get("score"), "method": m.get("method"), "reason": m.get("reason"),
            "evidence": {k: f.get(k) for k in ("rel", "form", "tier", "leftover", "processed", "outranked",
                                                "owned_elsewhere", "form_shared", "variety", "state_ok", "state_why",
                                                "category", "price_range", "part_match", "dcls", "llm")},
            "reviewed_by": m.get("reviewed_by"), "reviewed_at": m.get("reviewed_at"),
        })
    cands.sort(key=lambda c: (order.get(c["status"], 9), -(c["score"] or 0)))
    price = (sb.table("ingredient_price_daily").select("*").eq("ingredient_id", ingredient_id)
             .order("price_date", desc=True).limit(28).execute().data or [])
    return {"ingredient": meta[0], "candidates": cands, "prices": price}


def _apply(sb, it: ReviewIn, user: dict) -> dict:
    status = "approved" if it.decision == "approve" else "rejected"
    actor = user.get("staff_id") or user.get("username") or user.get("sub") or "admin"
    res = (sb.table("ingredient_product_map")
           .update({"status": status, "method": "human", "reason": it.reason or ("승인" if status == "approved" else "거절"),
                    "reviewed_by": str(actor), "reviewed_at": _now(), "updated_at": _now()})
           .eq("ingredient_id", it.ingredient_id).eq("supplier", it.supplier).eq("item_cd", it.item_cd).execute())
    if not res.data:
        raise HTTPException(404, f"매핑 후보가 없습니다: {it.supplier}/{it.item_cd} → {it.ingredient_id}")
    _bump_category(sb, it, status)
    return {"ingredient_id": it.ingredient_id, "supplier": it.supplier, "item_cd": it.item_cd, "status": status}


def _bump_category(sb, it: ReviewIn, status: str):
    """분류 대응표 보완: (공급사 대·중분류, 식품대분류) 승인/거절 수 +1"""
    try:
        p = (sb.table("supplier_prices_latest").select("lcls_nm,mcls_nm").eq("supplier", it.supplier)
             .eq("item_cd", it.item_cd).limit(1).execute().data or [{}])[0]
        g = (sb.table("mapping_ingredients").select("food_group").eq("ingredient_id", it.ingredient_id)
             .limit(1).execute().data or [{}])[0].get("food_group")
        if not (p.get("lcls_nm") and p.get("mcls_nm") and g):
            return
        key = {"supplier": it.supplier, "lcls_nm": p["lcls_nm"], "mcls_nm": p["mcls_nm"], "food_group": g}
        cur = (sb.table("category_map").select("n_approved,n_rejected").match(key).limit(1).execute().data or [{}])[0]
        col = "n_approved" if status == "approved" else "n_rejected"
        sb.table("category_map").upsert({**key, "n_approved": cur.get("n_approved") or 0,
                                         "n_rejected": cur.get("n_rejected") or 0, col: (cur.get(col) or 0) + 1},
                                        on_conflict="supplier,lcls_nm,mcls_nm,food_group").execute()
    except Exception:                                            # noqa: BLE001  (통계 보완 실패는 검수를 막지 않음)
        pass


@router.post("/review")
def review(body: ReviewIn, user: dict = Security(require_admin)):
    return _apply(get_supabase(), body, user)


@router.post("/review/bulk")
def review_bulk(body: BulkIn, user: dict = Security(require_admin)):
    sb = get_supabase()
    return {"done": [_apply(sb, it, user) for it in body.items]}


@router.post("/ingredient/{ingredient_id}/status")
def set_ingredient_status(ingredient_id: str, body: StatusIn, user: dict = Security(require_admin)):
    sb = get_supabase()
    res = (sb.table("mapping_ingredients").update({"product_status": body.product_status, "updated_at": _now()})
           .eq("ingredient_id", ingredient_id).execute())
    if not res.data:
        raise HTTPException(404, "식재료가 없습니다.")
    return res.data[0]


@router.get("/stats")
def stats(user: dict = Security(require_viewer)):
    sb = get_supabase()
    counts = {r["status"]: r["n"] for r in (sb.table("mapping_status_counts").select("*").execute().data or [])}
    q = sb.table("mapping_queue").select("ingredient_id", count="exact").limit(1).execute()
    last = (sb.table("ingredient_price_daily").select("price_date").order("price_date", desc=True).limit(1)
            .execute().data or [])
    cov = None
    if last:
        day = last[0]["price_date"]
        ings = _all(lambda: sb.table("mapping_ingredients").select("ingredient_id,usage_g,product_status"))
        priced = {r["ingredient_id"] for r in _all(lambda: sb.table("ingredient_price_daily").select("ingredient_id")
                                                   .eq("price_date", day).not_.is_(OPTIMIZE_COL, "null"))}
        tot = sum(float(r["usage_g"] or 0) for r in ings if r["product_status"] == "product")
        got = sum(float(r["usage_g"] or 0) for r in ings if r["ingredient_id"] in priced)
        cov = {"price_date": day, "weight_pct": round(100 * got / tot, 1) if tot else 0, "n_priced": len(priced)}
    return {"status_counts": counts, "queue_ingredients": q.count, "coverage": cov}


@router.get("/missing")
def missing(limit: int = Query(50, ge=1, le=300), user: dict = Security(require_viewer)):
    sb = get_supabase()
    last = (sb.table("ingredient_price_daily").select("price_date").order("price_date", desc=True).limit(1)
            .execute().data or [])
    if not last:
        return {"price_date": None, "items": []}
    day = last[0]["price_date"]
    rows = _all(lambda: sb.table("ingredient_price_daily").select("ingredient_id").eq("price_date", day)
                .is_(OPTIMIZE_COL, "null"))
    ids = [r["ingredient_id"] for r in rows]
    items = []
    for i in range(0, len(ids), 150):
        items += (sb.table("mapping_ingredients").select("ingredient_id,rep_name,food_group,usage_g,rank")
                  .in_("ingredient_id", ids[i:i + 150]).execute().data or [])
    items.sort(key=lambda r: -float(r["usage_g"] or 0))
    return {"price_date": day, "items": items[:limit]}
