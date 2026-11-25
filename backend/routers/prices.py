# -*- coding: utf-8 -*-
"""
식자재 단가 검색 (현대그린푸드 · 사조푸디스트)

price-crawler 가 매일 아침 Supabase 에 올리는 두 테이블을 읽기만 한다.
  · supplier_prices_latest  — 공급사·단품별 최신 단가 1행
  · supplier_price_history  — 신규/단가변동이 있었던 날만 1행

단가표는 전 시설 공통이라 nursing_home_id 로 격리하지 않는다 (뉴스와 같음).
공급사마다 규격 표기가 달라 규격 문자열에서 포장 중량을 읽어 'kg당 환산가'를 만든다.
"""
import re
import unicodedata
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Security
from fastapi.security import HTTPAuthorizationCredentials

from dependencies import decode_token, get_supabase, security

router = APIRouter()

SUPPLIERS = {
    "hgreenfood": "현대그린푸드",
    "sajo": "사조푸디스트",
}
COLS = ("supplier,item_cd,item_nm,lcls_nm,mcls_nm,scls_nm,dcls_nm,origin,tax_type,"
        "spec,unit,storage,min_order_day,unit_price,unit_price_tax,last_seen")
# 식품이 아닌 분류 (현대그린푸드만 분류가 있음)
NON_FOOD_MCLS = {"생활용품", "세제류", "포장용품"}
# 고령자 식단에 자주 쓰는 묶음 태그 → 단품명 키워드
TAGS = {
    "soft": ["다짐", "무스", "부드러운", "고령친화", "퓨레", "연육", "으깬", "토로미", "케어푸드"],
    "lowsalt": ["저염", "저당", "무염", "저나트륨"],
}
FETCH_CAP = 1000  # 한 번 검색에서 DB 에서 가져오는 최대 행 (Supabase 기본 상한)


def require_viewer(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    user = decode_token(credentials.credentials)
    if user.get("role") == "staff" or user.get("is_admin"):
        return user
    raise HTTPException(status_code=403, detail="로그인이 필요합니다.")


# ─────────────────────────── 규격 → 포장 중량 ───────────────────────────

_NUM = r"(\d+(?:[.,]\d+)?)"
_W = re.compile(_NUM + r"\s*(kg|g|ml|l)(?![a-z])", re.I)
_MUL = re.compile(_NUM + r"\s*(kg|g|ml|l)\s*[*xX×]\s*(\d+)", re.I)
_SLASH = re.compile(_NUM + r"\s*(kg|g|ml|l)\s*/\s*(\d+)\s*(?:개|ea|입|팩|봉|pk)", re.I)  # '100G/50개'
MAX_PER_KG = 1_000_000  # 이보다 크면 규격을 잘못 읽은 것으로 보고 환산하지 않음


def _to_g(n: str, u: str) -> float:
    v = float(n.replace(",", ""))
    return v * 1000 if u.lower() in ("kg", "l") else v


def pack_grams(spec: Optional[str], unit: Optional[str]):
    """(포장 중량 g 또는 ml, 부피 여부). 읽을 수 없으면 (None, False).

    단위가 KG 이면 단가 자체가 kg당 가격이다. 그 외에는 규격의 첫 중량 표기를 쓴다:
    '1.56Kg(52~60g*30EA)' → 1560g, '1Kg*10EA' → 10kg, 'EA/3KG/부침용' → 3kg, 'KG(500G*2개입)' → 1kg.
    """
    u = (unit or "").strip().lower()
    s = unicodedata.normalize("NFKC", spec or "")   # ㎖ ㎏ 같은 기호를 ml kg 로
    if u == "kg":
        return 1000.0, False
    if re.match(r"^\s*kg(?![a-z0-9])", s, re.I):
        return 1000.0, False
    head = s.split("(")[0]
    for part in (head, s):
        m = _MUL.match(part.strip()) or _SLASH.match(part.strip())
        if m:
            return _to_g(m.group(1), m.group(2)) * int(m.group(3)), m.group(2).lower() in ("ml", "l")
        m = _W.search(part)
        if m:
            g = _to_g(m.group(1), m.group(2))
            if g > 0:
                return g, m.group(2).lower() in ("ml", "l")
    return None, False


# ─────────────────────────── 행 다듬기 ───────────────────────────

def _storage(r: dict) -> Optional[str]:
    s = (r.get("storage") or "").strip()
    if s:
        return "실온" if s == "상온" else s
    m = re.search(r"냉장|냉동|실온|상온", r.get("item_nm") or "")   # 현대그린푸드는 단품명 괄호 안에 있음
    if not m:
        return None
    return "실온" if m.group(0) == "상온" else m.group(0)


def _origin(r: dict) -> Optional[str]:
    o = (r.get("origin") or "").strip()
    if o in ("국산", "국내"):
        return "국산"
    if o in ("수입", "원양"):
        return o
    if o:
        return o
    return None


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def shape(r: dict, latest_day: dict) -> dict:
    price = _num(r.get("unit_price"))
    taxable = (r.get("tax_type") or "") == "과세"
    price_tax = _num(r.get("unit_price_tax"))
    tax_estimated = False
    if price_tax is None and price is not None:
        price_tax = round(price * 1.1) if taxable else price   # 사조는 부가세 포함가가 없어 계산
        tax_estimated = taxable
    g, is_vol = pack_grams(r.get("spec"), r.get("unit"))
    per_kg = round(price / g * 1000) if (price is not None and g) else None
    per_kg_tax = round(price_tax / g * 1000) if (price_tax is not None and g) else None
    if per_kg is not None and per_kg > MAX_PER_KG:
        g, per_kg, per_kg_tax = None, None, None
    sup = r.get("supplier")
    last_seen = r.get("last_seen")
    return {
        "supplier": sup,
        "supplier_label": SUPPLIERS.get(sup, sup),
        "item_cd": r.get("item_cd"),
        "item_nm": r.get("item_nm"),
        "category": " › ".join(x for x in (r.get("lcls_nm"), r.get("mcls_nm"), r.get("dcls_nm")) if x) or None,
        "lcls_nm": r.get("lcls_nm"),
        "mcls_nm": r.get("mcls_nm"),
        "dcls_nm": r.get("dcls_nm"),
        "origin": _origin(r),
        "tax_type": r.get("tax_type"),
        "spec": r.get("spec"),
        "unit": r.get("unit"),
        "storage": _storage(r),
        "min_order_day": r.get("min_order_day"),
        "lead_days": _lead_days(r.get("min_order_day")),
        "unit_price": price,
        "unit_price_tax": price_tax,
        "tax_estimated": tax_estimated,
        "pack_g": g,
        "per_kg": per_kg,
        "per_kg_tax": per_kg_tax,
        "per_unit_label": "L당" if is_vol else "kg당",
        "last_seen": last_seen,
        "stale": bool(last_seen and latest_day.get(sup) and last_seen < latest_day[sup]),
    }


def _lead_days(v: Optional[str]) -> Optional[int]:
    m = re.search(r"D-(\d+)", v or "")
    return int(m.group(1)) if m else None


def _clean_terms(q: str):
    q = re.sub(r"[%_,()*\\]", " ", q or "")
    return [t for t in q.split() if t][:5]


def _latest_days(sb) -> dict:
    out = {}
    for sup in SUPPLIERS:
        rows = (sb.table("supplier_prices_latest").select("last_seen").eq("supplier", sup)
                .order("last_seen", desc=True).limit(1).execute().data or [])
        if rows:
            out[sup] = rows[0]["last_seen"]
    return out


def _relevance(item: dict, terms) -> tuple:
    """정확히 그 식재료(세분류·단품명 시작)가 먼저, 가공품·긴 이름은 뒤로."""
    if not terms:
        return (0, 0, len(item["item_nm"] or ""))
    name = re.sub(r"^\([^)]*\)|^\[[^\]]*\]", "", item["item_nm"] or "").strip()
    t0 = terms[0]
    exact_cat = 0 if (item.get("dcls_nm") or "") == t0 else 1
    starts = 0 if name.startswith(t0) else 1
    return (exact_cat, starts, int(item["stale"]), len(name))


# ─────────────────────────── API ───────────────────────────

@router.get("/summary")
def summary(user: dict = Security(require_viewer)):
    """공급사별 품목 수·기준일, 최근 반영일의 단가 변동 요약과 변동 폭 큰 품목."""
    sb = get_supabase()
    latest_day = _latest_days(sb)
    suppliers = []
    for sup, label in SUPPLIERS.items():
        day = latest_day.get(sup)
        total = 0
        if day:
            res = (sb.table("supplier_prices_latest").select("item_cd", count="exact", head=True)
                   .eq("supplier", sup).eq("last_seen", day).execute())
            total = res.count or 0
        upd = (sb.table("supplier_prices_latest").select("updated_at").eq("supplier", sup)
               .order("updated_at", desc=True).limit(1).execute().data or [])
        suppliers.append({"supplier": sup, "label": label, "base_day": day, "items": total,
                          "updated_at": upd[0]["updated_at"] if upd else None})

    # 가장 최근 변동일 (첫 실행일은 전부 'new' 라 의미가 없으므로 'changed' 가 있는 날 기준)
    last = (sb.table("supplier_price_history").select("changed_on").eq("change_type", "changed")
            .order("changed_on", desc=True).limit(1).execute().data or [])
    changes = {"day": None, "up": 0, "down": 0, "new": 0, "movers": []}
    if last:
        day = last[0]["changed_on"]
        rows = (sb.table("supplier_price_history")
                .select("supplier,item_cd,change_type,item_nm,spec,unit,prev_price,unit_price")
                .eq("changed_on", day).limit(FETCH_CAP).execute().data or [])
        movers = []
        for r in rows:
            if r["change_type"] == "new":
                changes["new"] += 1
                continue
            p0, p1 = _num(r.get("prev_price")), _num(r.get("unit_price"))
            if not p0 or p1 is None:
                continue
            pct = (p1 - p0) / p0 * 100
            if pct > 0:
                changes["up"] += 1
            elif pct < 0:
                changes["down"] += 1
            movers.append({**r, "supplier_label": SUPPLIERS.get(r["supplier"], r["supplier"]),
                           "prev_price": p0, "unit_price": p1, "pct": round(pct, 1)})
        movers.sort(key=lambda m: -abs(m["pct"]))
        changes.update(day=day, movers=movers[:12])
    return {"suppliers": suppliers, "changes": changes,
            "categories": _categories(sb, latest_day.get("hgreenfood"))}


def _categories(sb, day):
    """현대그린푸드 대분류 목록 (사조는 분류 정보가 없음)."""
    if not day:
        return []
    return ["농산품", "축산품", "수산품", "공산품"]


@router.get("/search")
def search(q: str = Query("", max_length=60),
           supplier: Optional[str] = Query(None),
           storage: Optional[str] = Query(None, description="냉장|냉동|실온"),
           origin: Optional[str] = Query(None, description="국산|수입"),
           category: Optional[str] = Query(None, description="대분류 (현대그린푸드만)"),
           tag: Optional[str] = Query(None, description="soft|lowsalt"),
           food_only: bool = Query(True),
           include_stale: bool = Query(False),
           sort: str = Query("relevance", pattern="^(relevance|per_kg|price|name)$"),
           vat: bool = Query(True),
           limit: int = Query(40, ge=1, le=200),
           offset: int = Query(0, ge=0),
           user: dict = Security(require_viewer)):
    terms = _clean_terms(q)
    if not terms and not tag and not category:
        return {"items": [], "total": 0, "counts": {}, "truncated": False, "best": {}, "terms": []}

    sb = get_supabase()
    latest_day = _latest_days(sb)
    qry = sb.table("supplier_prices_latest").select(COLS)
    for t in terms:                       # 띄어쓰기로 나눈 단어는 모두 포함 (AND)
        qry = qry.ilike("item_nm", f"%{t}%")
    if tag in TAGS:
        qry = qry.or_(",".join(f"item_nm.ilike.%{k}%" for k in TAGS[tag]))
    if supplier in SUPPLIERS:
        qry = qry.eq("supplier", supplier)
    if category:
        qry = qry.eq("lcls_nm", category)
    rows = qry.limit(FETCH_CAP).execute().data or []
    truncated = len(rows) >= FETCH_CAP

    items = []
    for r in rows:
        it = shape(r, latest_day)
        if not include_stale and it["stale"]:
            continue
        if food_only and (it["mcls_nm"] or "") in NON_FOOD_MCLS:
            continue
        if storage and it["storage"] != storage:
            continue
        if origin == "국산" and it["origin"] != "국산":
            continue
        if origin == "수입" and it["origin"] not in ("수입", "원양"):
            continue
        items.append(it)

    pk = "per_kg_tax" if vat else "per_kg"
    pp = "unit_price_tax" if vat else "unit_price"
    big = float("inf")
    if sort == "per_kg":
        items.sort(key=lambda i: (i[pk] is None, i[pk] or big))
    elif sort == "price":
        items.sort(key=lambda i: (i[pp] is None, i[pp] or big))
    elif sort == "name":
        items.sort(key=lambda i: i["item_nm"] or "")
    else:
        items.sort(key=lambda i: _relevance(i, terms))

    # 공급사별 kg당 최저 (관련도 상위 품목 안에서만 — 엉뚱한 가공품이 최저가로 잡히지 않게)
    best = {}
    pool = sorted(items, key=lambda i: _relevance(i, terms))[:60]
    for it in pool:
        v = it[pk]
        if v is None or it["per_unit_label"] != "kg당":
            continue
        cur = best.get(it["supplier"])
        if cur is None or v < cur[pk]:
            best[it["supplier"]] = it

    counts = {s: sum(1 for i in items if i["supplier"] == s) for s in SUPPLIERS}
    page = items[offset: offset + limit]
    _attach_recent_change(sb, page)
    return {"items": page, "total": len(items), "counts": counts, "truncated": truncated,
            "best": best, "terms": terms}


def _attach_recent_change(sb, items, days: int = 30):
    """화면에 보이는 품목에만 최근 30일 단가 변동을 붙인다."""
    if not items:
        return
    since = (date.today() - timedelta(days=days)).isoformat()
    by_sup = {}
    for it in items:
        by_sup.setdefault(it["supplier"], []).append(it["item_cd"])
    recent = {}
    for sup, codes in by_sup.items():
        rows = (sb.table("supplier_price_history")
                .select("item_cd,changed_on,prev_price,unit_price")
                .eq("supplier", sup).eq("change_type", "changed").gte("changed_on", since)
                .in_("item_cd", codes).order("changed_on", desc=True).execute().data or [])
        for r in rows:
            recent.setdefault((sup, r["item_cd"]), r)
    for it in items:
        r = recent.get((it["supplier"], it["item_cd"]))
        if r and _num(r.get("prev_price")):
            p0, p1 = _num(r["prev_price"]), _num(r["unit_price"])
            it["change"] = {"on": r["changed_on"], "prev": p0, "now": p1,
                            "pct": round((p1 - p0) / p0 * 100, 1)}


@router.get("/item/{supplier}/{item_cd}")
def item_detail(supplier: str, item_cd: str, user: dict = Security(require_viewer)):
    if supplier not in SUPPLIERS:
        raise HTTPException(status_code=404, detail="알 수 없는 공급사입니다.")
    sb = get_supabase()
    rows = (sb.table("supplier_prices_latest").select(COLS)
            .eq("supplier", supplier).eq("item_cd", item_cd).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(status_code=404, detail="품목을 찾을 수 없습니다.")
    it = shape(rows[0], _latest_days(sb))
    hist = (sb.table("supplier_price_history")
            .select("changed_on,change_type,prev_price,unit_price,prev_price_tax,unit_price_tax")
            .eq("supplier", supplier).eq("item_cd", item_cd)
            .order("changed_on").limit(400).execute().data or [])
    return {"item": it, "history": hist}
