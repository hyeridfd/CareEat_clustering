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
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from urllib.parse import quote

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
        "category_auto": r.get("scls_nm") == "자동분류",   # 사조: 품목명으로 추정한 분류
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
    """대분류 목록 (사조는 crawler 가 품목명으로 추정해 채운 값)."""
    if not day:
        return []
    return ["농산품", "축산품", "수산품", "공산품"]


def _ym_ok(v: Optional[str]) -> Optional[str]:
    return v if v and re.fullmatch(r"\d{4}-\d{2}", v) else None


def search_core(sb, q="", supplier=None, storage=None, origin=None, category=None, mcls=None, tax=None,
                tag=None, food_only=True, include_stale=False, sort="relevance", vat=True):
    """조건에 맞는 품목 전체(정렬까지). 화면 검색과 엑셀 내보내기가 같이 쓴다."""
    terms = _clean_terms(q)
    if not terms and not tag and not category and not mcls:
        return None
    latest_day = _latest_days(sb)
    # 공급사마다 따로 가져온다 (한 번에 가져오면 상한이 한 공급사 행으로 다 차서 다른 공급사가 빠짐)
    rows, truncated = [], False
    for sup in ([supplier] if supplier in SUPPLIERS else list(SUPPLIERS)):
        qry = sb.table("supplier_prices_latest").select(COLS).eq("supplier", sup)
        for t in terms:                   # 띄어쓰기로 나눈 단어는 모두 포함 (AND)
            qry = qry.ilike("item_nm", f"%{t}%")
        if tag in TAGS:
            qry = qry.or_(",".join(f"item_nm.ilike.%{k}%" for k in TAGS[tag]))
        if category:
            qry = qry.eq("lcls_nm", category)
        if mcls:
            qry = qry.eq("mcls_nm", mcls)
        part = qry.limit(FETCH_CAP).execute().data or []
        truncated = truncated or len(part) >= FETCH_CAP
        rows += part

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
        if tax and (it["tax_type"] or "") != tax:
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
    return {"items": items, "terms": terms, "truncated": truncated, "best": best, "counts": counts, "pk": pk}


def attach_period(sb, items, date_from: Optional[str], date_to: Optional[str], chunk: int = 150):
    """품목마다 기간(월) 월평균 단가 통계를 붙인다: period = {avg, min, max, first, last, pct, months}."""
    date_from, date_to = _ym_ok(date_from), _ym_ok(date_to)
    if not items or not (date_from or date_to):
        return {}
    by_sup = {}
    for it in items:
        by_sup.setdefault(it["supplier"], []).append(it["item_cd"])
    series = {}
    for sup, codes in by_sup.items():
        for i in range(0, len(codes), chunk):
            qry = (sb.table("supplier_price_monthly").select("item_cd,month,avg_price")
                   .eq("supplier", sup).in_("item_cd", codes[i:i + chunk]))
            if date_from:
                qry = qry.gte("month", f"{date_from}-01")
            if date_to:
                qry = qry.lte("month", f"{date_to}-01")
            for r in qry.order("month").limit(10000).execute().data or []:
                v = _num(r.get("avg_price"))
                if v:
                    series.setdefault((sup, r["item_cd"]), []).append((r["month"][:7], v))
    for it in items:
        sr = series.get((it["supplier"], it["item_cd"]))
        if not sr:
            it["period"] = None
            continue
        vals = [v for _, v in sr]
        it["period"] = {"avg": round(sum(vals) / len(vals)), "min": round(min(vals)), "max": round(max(vals)),
                        "first": round(sr[0][1]), "last": round(sr[-1][1]),
                        "first_month": sr[0][0], "last_month": sr[-1][0],
                        "pct": round((sr[-1][1] / sr[0][1] - 1) * 100, 1) if len(sr) > 1 else None,
                        "months": len(sr)}
    return series


@router.get("/search")
def search(q: str = Query("", max_length=60),
           supplier: Optional[str] = Query(None),
           storage: Optional[str] = Query(None, description="냉장|냉동|실온"),
           origin: Optional[str] = Query(None, description="국산|수입"),
           category: Optional[str] = Query(None, description="대분류 (사조는 자동 추정 분류)"),
           mcls: Optional[str] = Query(None, description="중분류"),
           tax: Optional[str] = Query(None, description="면세|과세"),
           tag: Optional[str] = Query(None, description="soft|lowsalt"),
           date_from: Optional[str] = Query(None, description="기간 시작 YYYY-MM"),
           date_to: Optional[str] = Query(None, description="기간 끝 YYYY-MM"),
           food_only: bool = Query(True),
           include_stale: bool = Query(False),
           sort: str = Query("relevance", pattern="^(relevance|per_kg|price|name|period_up|period_down)$"),
           vat: bool = Query(True),
           limit: int = Query(40, ge=1, le=200),
           offset: int = Query(0, ge=0),
           user: dict = Security(require_viewer)):
    sb = get_supabase()
    base_sort = sort if sort in ("relevance", "per_kg", "price", "name") else "relevance"
    res = search_core(sb, q, supplier, storage, origin, category, mcls, tax, tag, food_only, include_stale,
                      base_sort, vat)
    if res is None:
        return {"items": [], "total": 0, "counts": {}, "truncated": False, "best": {}, "terms": []}
    items = res["items"]
    if sort in ("period_up", "period_down"):
        # 기간 변동률 순: 전체 품목에 기간 통계가 필요하다 (최대 공급사당 1,000개)
        attach_period(sb, items, date_from, date_to)
        sign = -1 if sort == "period_up" else 1
        items.sort(key=lambda i: (i.get("period") is None or i["period"]["pct"] is None,
                                  sign * ((i.get("period") or {}).get("pct") or 0)))
        page = items[offset: offset + limit]
    else:
        page = items[offset: offset + limit]
        attach_period(sb, page, date_from, date_to)
    _attach_recent_change(sb, page)
    dist, stats = _distribution(items, res["terms"], res["pk"]) if offset == 0 else (None, None)
    return {"items": page, "total": len(items), "counts": res["counts"], "truncated": res["truncated"],
            "best": res["best"], "terms": res["terms"], "dist": dist, "stats": stats,
            "period": {"from": _ym_ok(date_from), "to": _ym_ok(date_to)}}


@router.get("/months")
def months(user: dict = Security(require_viewer)):
    """월별 집계가 있는 달 목록 (기간 선택용)."""
    sb = get_supabase()
    rows = (sb.table("supplier_category_monthly").select("month").eq("mcls_nm", "전체")
            .order("month").limit(5000).execute().data or [])
    ms = sorted({r["month"][:7] for r in rows})
    return {"months": ms}


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    i = (len(sorted_vals) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo))


def _distribution(items, terms, pk, cap: int = 400):
    """검색 결과의 kg당 가격 분포 (화면의 점 그래프용). 관련도 상위 cap 개만."""
    pool = [i for i in sorted(items, key=lambda i: _relevance(i, terms))
            if i[pk] is not None and i["per_unit_label"] == "kg당"][:cap]
    dist = [{"s": i["supplier"], "v": i[pk], "cd": i["item_cd"], "nm": i["item_nm"], "spec": i["spec"]}
            for i in pool]
    stats = {}
    for sup in SUPPLIERS:
        vals = sorted(d["v"] for d in dist if d["s"] == sup)
        if vals:
            stats[sup] = {"n": len(vals), "min": vals[0], "max": vals[-1], "p25": _quantile(vals, .25),
                          "median": _quantile(vals, .5), "p75": _quantile(vals, .75)}
    return dist, stats


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
    monthly, season = _item_monthly(sb, supplier, item_cd)
    return {"item": it, "history": hist, "monthly": monthly, "seasonal": season}


# ─────────────────────────── 월별 · 계절 ───────────────────────────
# price-crawler/monthly.py 가 채우는 supplier_price_monthly(품목 월평균), supplier_category_monthly(분류 월 지수)

def seasonal_profile(series):
    """[(YYYY-MM, 값)] → 달(1~12)별 '그해 평균 대비 %'의 여러 해 평균.
    10개월 이상 있는 해만 쓴다. 쓸 수 있는 해가 없으면 None."""
    by_year = {}
    for ym, v in series:
        if v:
            by_year.setdefault(ym[:4], {})[int(ym[5:7])] = float(v)
    devs = {m: [] for m in range(1, 13)}
    years = []
    for y, months in sorted(by_year.items()):
        if len(months) < 10:
            continue
        avg = sum(months.values()) / len(months)
        years.append(y)
        for m, v in months.items():
            devs[m].append((v / avg - 1) * 100)
    if not years:
        return None
    prof = [round(sum(d) / len(d), 1) if d else None for m, d in sorted(devs.items())]
    return {"years": years, "pct": prof}


def _yoy(series, i):
    """series[i] 의 12개월 전 대비 %."""
    ym = series[i][0]
    prev = f"{int(ym[:4]) - 1}{ym[4:]}"
    for p_ym, p_v in series:
        if p_ym == prev and p_v:
            return round((series[i][1] / p_v - 1) * 100, 1)
    return None


@router.get("/trends")
def trends(lcls: Optional[str] = Query(None, description="대분류, 생략하면 대분류별 요약"),
           mcls: str = Query("전체"),
           user: dict = Security(require_viewer)):
    """분류 월 지수: 공급사별 시계열, 전월·전년 대비, 계절 패턴. 분류 목록(groups)도 함께."""
    sb = get_supabase()
    rows = (sb.table("supplier_category_monthly")
            .select("supplier,lcls_nm,mcls_nm,month,idx,mom_pct,n_items,n_compared,up_share,down_share,"
                    "kg_median,kg_p25,kg_p75,kg_n")
            .order("month").limit(20000).execute().data or [])
    if not rows:
        return {"months": 0, "groups": [], "overview": [], "series": {}, "seasonal": {}}

    months = sorted({r["month"][:7] for r in rows})
    groups = {}
    for r in rows:
        if r["mcls_nm"] != "전체":
            g = groups.setdefault((r["lcls_nm"], r["mcls_nm"]), 0)
            groups[(r["lcls_nm"], r["mcls_nm"])] = max(g, r["n_items"] or 0)
    group_list = [{"lcls": k[0], "mcls": k[1], "n": n} for k, n in sorted(groups.items(), key=lambda x: (x[0][0], -x[1]))]

    def series_of(sup, l, m):
        return [(r["month"][:7], float(r["idx"]) if r["idx"] is not None else None, r)
                for r in rows if r["supplier"] == sup and r["lcls_nm"] == l and r["mcls_nm"] == m]

    # 대분류별 요약 카드: 최근 달 지수, 전월·전년 대비
    overview = []
    for l in ("농산품", "축산품", "수산품", "공산품"):
        for sup in SUPPLIERS:
            s = series_of(sup, l, "전체")
            if not s:
                continue
            last = s[-1]
            overview.append({"lcls": l, "supplier": sup, "month": last[0], "idx": last[1],
                             "mom_pct": last[2]["mom_pct"], "yoy_pct": _yoy([(a, b) for a, b, _ in s], len(s) - 1),
                             "spark": [b for _, b, _ in s[-12:]]})

    series, seasonal = {}, {}
    if lcls:
        for sup in SUPPLIERS:
            s = series_of(sup, lcls, mcls)
            if not s:
                continue
            pairs = [(a, b) for a, b, _ in s]
            series[sup] = [{"month": a, "idx": b, "mom_pct": r["mom_pct"], "n_items": r["n_items"],
                            "n_compared": r["n_compared"], "up_share": r["up_share"], "down_share": r["down_share"],
                            "yoy_pct": _yoy(pairs, i), "kg_median": _num(r.get("kg_median")),
                            "kg_p25": _num(r.get("kg_p25")), "kg_p75": _num(r.get("kg_p75")), "kg_n": r.get("kg_n")}
                           for i, (a, b, r) in enumerate(s)]
            seasonal[sup] = seasonal_profile(pairs)
        # 이 분류 안에서 많이 변한 품목 (crawler 의 monthly.movers 가 미리 계산)
        try:
            mv = (sb.table("supplier_category_movers").select("*")
                  .eq("lcls_nm", lcls).eq("mcls_nm", mcls).order("rank").limit(500).execute().data or [])
        except Exception:  # noqa: BLE001  (테이블이 아직 없을 때)
            mv = []
        movers = {}
        for r in mv:
            movers.setdefault(r["period"], {}).setdefault(r["kind"], []).append(
                {**r, "supplier_label": SUPPLIERS.get(r["supplier"], r["supplier"])})
    else:
        movers = {}
    return {"months": len(months), "first": months[0], "last": months[-1],
            "groups": group_list, "overview": overview, "series": series, "seasonal": seasonal, "movers": movers}


def _item_monthly(sb, supplier: str, item_cd: str):
    rows = (sb.table("supplier_price_monthly").select("month,avg_price,min_price,max_price,days")
            .eq("supplier", supplier).eq("item_cd", item_cd).order("month").limit(60).execute().data or [])
    out = [{"month": r["month"][:7], "avg": _num(r["avg_price"]), "min": _num(r["min_price"]),
            "max": _num(r["max_price"]), "days": r["days"]} for r in rows]
    pairs = [(r["month"], r["avg"]) for r in out]
    for i, r in enumerate(out):
        r["mom_pct"] = round((r["avg"] / out[i - 1]["avg"] - 1) * 100, 1) if i and out[i - 1]["avg"] else None
        r["yoy_pct"] = _yoy(pairs, i)
    return out, seasonal_profile(pairs)



# ─────────────────────────── 엑셀 내보내기 ───────────────────────────
def _excel():
    """엑셀 모듈은 버튼을 누를 때만 불러온다 (openpyxl 문제로 단가 검색 전체가 멈추지 않게)."""
    try:
        from routers import prices_excel
    except ModuleNotFoundError as e:
        if e.name not in ("routers", "routers.prices_excel"):
            raise HTTPException(status_code=500, detail=f"엑셀 기능에 필요한 모듈이 없습니다: {e.name}")
        import prices_excel  # 테스트에서 routers 폴더를 직접 경로에 넣었을 때
    return prices_excel

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXPORT_CAP = 3000


def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type=XLSX,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


def _months_between(a: Optional[str], b: Optional[str]):
    if not (a and b):
        return []
    y, m = int(a[:4]), int(a[5:7])
    out = []
    while f"{y}-{m:02d}" <= b and len(out) < 120:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


@router.get("/export/search")
def export_search(q: str = Query("", max_length=60),
                  supplier: Optional[str] = Query(None), storage: Optional[str] = Query(None),
                  origin: Optional[str] = Query(None), category: Optional[str] = Query(None),
                  mcls: Optional[str] = Query(None), tax: Optional[str] = Query(None),
                  tag: Optional[str] = Query(None),
                  date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                  sort: str = Query("relevance", pattern="^(relevance|per_kg|price|name|period_up|period_down)$"),
                  vat: bool = Query(True),
                  user: dict = Security(require_viewer)):
    """검색 결과 전체(최대 3,000개)를 엑셀로."""
    sb = get_supabase()
    base_sort = sort if sort in ("relevance", "per_kg", "price", "name") else "relevance"
    res = search_core(sb, q, supplier, storage, origin, category, mcls, tax, tag, True, False, base_sort, vat)
    if res is None:
        raise HTTPException(status_code=400, detail="검색어나 분류를 하나 이상 정해 주세요.")
    items = res["items"][:EXPORT_CAP]
    date_from, date_to = _ym_ok(date_from), _ym_ok(date_to)
    series = attach_period(sb, items, date_from, date_to)
    if sort in ("period_up", "period_down"):
        sign = -1 if sort == "period_up" else 1
        items.sort(key=lambda i: (i.get("period") is None or i["period"]["pct"] is None,
                                  sign * ((i.get("period") or {}).get("pct") or 0)))
    months = _months_between(date_from, date_to) or sorted({m for sr in series.values() for m, _ in sr})
    sup_lab = SUPPLIERS.get(supplier, "전체")
    tag_lab = {"soft": "부드러운 식감", "lowsalt": "저염·저당"}.get(tag, "")
    conditions = [("품목명", q or "—"), ("부류(대분류)", category or "전체"), ("품목(중분류)", mcls or "전체"),
                  ("공급사", sup_lab), ("보관", storage or "전체"), ("원산지", origin or "전체"),
                  ("과세", tax or "전체"), ("묶음", tag_lab or "—"),
                  ("기간", f"{date_from or '처음'} ~ {date_to or '최근'}"),
                  ("단가 기준", "부가세 포함" if vat else "부가세 별도(공급가)"),
                  ("품목 수", f"{len(items):,}개" + (" (상한 3,000개)" if len(res["items"]) > EXPORT_CAP else ""))]
    data = _excel().build_search_xlsx(items, series, months, conditions, vat)
    name = "_".join(x for x in ["식자재단가", q.strip().replace(" ", "-") or category or "", mcls or "",
                                date_from or "", date_to or ""] if x)
    return _xlsx_response(data, f"{name}.xlsx")


@router.get("/export/trends")
def export_trends(lcls: str = Query(...), mcls: str = Query("전체"),
                  date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
                  user: dict = Security(require_viewer)):
    """분류 시세 동향(지수·kg당 중앙값·계절·많이 변한 품목)을 엑셀로."""
    data = trends(lcls=lcls, mcls=mcls, user=user)
    date_from, date_to = _ym_ok(date_from), _ym_ok(date_to)
    if date_from or date_to:
        for s, pts in (data.get("series") or {}).items():
            data["series"][s] = [p for p in pts if (not date_from or p["month"] >= date_from)
                                 and (not date_to or p["month"] <= date_to)]
    conditions = [("분류", lcls if mcls == "전체" else f"{lcls} › {mcls}"),
                  ("기간", f"{date_from or data.get('first') or '처음'} ~ {date_to or data.get('last') or '최근'}"),
                  ("공급사", ", ".join(SUPPLIERS[s] for s in (data.get("series") or {}))),
                  ("기준", "월평균 공급가(부가세 별도)")]
    xbytes = _excel().build_trends_xlsx(data, lcls, mcls, conditions)
    name = f"시세동향_{lcls}{'' if mcls == '전체' else '_' + mcls.replace('/', '-')}"
    return _xlsx_response(xbytes, f"{name}.xlsx")
