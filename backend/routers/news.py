# -*- coding: utf-8 -*-
"""
고령·돌봄 뉴스 브리핑

돌봄 데이터와 달리 뉴스는 전 시설 공통이라 nursing_home_id 로 격리하지 않는다.
  · 조회 — 로그인한 담당자·관리자 모두 열람
  · 수집 — 관리자 토큰, 또는 X-Cron-Secret 헤더(GitHub Actions 예약 실행)
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query, Security
from fastapi.security import HTTPAuthorizationCredentials

from dependencies import decode_token, get_supabase, security
from news import collect as nc
from news import summarize as ns

router = APIRouter()
KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger("uvicorn.error")


# ─────────────────────────── 권한 ───────────────────────────

def require_viewer(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """뉴스는 시설 구분이 없으므로 로그인만 확인한다 (require_staff 와 달리 시설 범위를 요구하지 않음)."""
    user = decode_token(credentials.credentials)
    if user.get("role") == "staff":
        return {**user, "actor": f"staff:{user['staff_id']}"}
    if user.get("is_admin"):
        return {**user, "actor": "admin"}
    raise HTTPException(status_code=403, detail="로그인이 필요합니다.")


def _authorize_collect(authorization: Optional[str], cron_secret: Optional[str]) -> str:
    """예약 실행용 공유 비밀번호, 운영 관리자, 또는 시설 관리자(manager)."""
    expected = nc._key("NEWS_CRON_SECRET")
    if cron_secret and expected and cron_secret == expected:
        return "cron"
    if authorization and authorization.lower().startswith("bearer "):
        user = decode_token(authorization.split(" ", 1)[1])
        if user.get("is_admin"):
            return "admin"
        if user.get("role") == "staff" and user.get("staff_role") == "manager":
            return f"staff:{user.get('staff_id')}"
        raise HTTPException(status_code=403, detail="시설 관리자 권한이 필요합니다.")
    raise HTTPException(status_code=401, detail="인증이 필요합니다.")


def _today() -> str:
    return datetime.now(KST).date().isoformat()


# ─────────────────────────── 조회 ───────────────────────────

@router.get("/dates")
def list_dates(limit: int = Query(60, ge=1, le=180), user: dict = Security(require_viewer)):
    """브리핑이 있는 날짜 목록 (최신순)."""
    sb = get_supabase()
    rows = (sb.table("news_briefings").select("brief_date, article_count, collected_at")
            .order("brief_date", desc=True).limit(limit).execute().data or [])
    return {"dates": rows}


@router.get("/daily")
def daily(date: Optional[str] = Query(None, description="YYYY-MM-DD, 생략하면 가장 최근 날짜"),
          category: Optional[str] = Query(None),
          user: dict = Security(require_viewer)):
    """하루치 브리핑과 기사 목록."""
    sb = get_supabase()

    if not date:
        latest = (sb.table("news_briefings").select("brief_date")
                  .order("brief_date", desc=True).limit(1).execute().data or [])
        if not latest:
            return {"date": None, "briefing": [], "articles": [], "counts": {}}
        date = latest[0]["brief_date"]

    brief = (sb.table("news_briefings").select("*")
             .eq("brief_date", date).limit(1).execute().data or [])

    q = (sb.table("news_articles")
         .select("id, title, press, url, category, summary, is_key, published_at")
         .eq("brief_date", date))
    if category and category != "전체":
        q = q.eq("category", category)
    articles = q.order("published_at", desc=True).limit(200).execute().data or []

    all_rows = (sb.table("news_articles").select("category")
                .eq("brief_date", date).limit(500).execute().data or [])
    counts = {"전체": len(all_rows)}
    for c in nc.CATEGORIES:
        counts[c] = sum(1 for r in all_rows if r["category"] == c)

    b = brief[0] if brief else {}
    return {"date": date, "briefing": b.get("lines") or [], "generator": b.get("generator"),
            "collected_at": b.get("collected_at"), "articles": articles, "counts": counts}


@router.get("/status")
def status(user: dict = Security(require_viewer)):
    """설정 진단 — 키 값은 노출하지 않고 존재 여부만."""
    return {"search_api": nc.api_status(), "llm": ns.llm_status(),
            "cron_secret_set": bool(nc._key("NEWS_CRON_SECRET"))}


# ─────────────────────────── 수집 ───────────────────────────

@router.post("/collect")
def run_collect(hours: int = Query(24, ge=1, le=168),
                authorization: Optional[str] = Header(None),
                x_cron_secret: Optional[str] = Header(None)):
    """기사를 모아 요약하고 그날의 브리핑을 저장한다. 같은 날짜로 다시 돌리면 덮어쓴다."""
    actor = _authorize_collect(authorization, x_cron_secret)
    sb = get_supabase()
    t0 = time.monotonic()
    log.info("[뉴스] 수집 시작 (요청자 %s, 최근 %d시간)", actor, hours)

    try:
        articles, errors = nc.collect(hours=hours)
    except Exception as e:                                  # noqa: BLE001
        log.error("[뉴스] 수집 실패: %s", e)
        raise HTTPException(status_code=502, detail=f"뉴스 수집 실패: {e}")
    log.info("[뉴스] 수집 완료 %d건 (%.1f초, 오류 %d건)", len(articles), time.monotonic() - t0, len(errors))

    if not articles:
        raise HTTPException(status_code=404,
                            detail="수집된 기사가 없습니다. " + (f"오류: {errors[:2]}" if errors else ""))

    t1 = time.monotonic()
    summarized, briefing, generator = ns.summarize(articles)
    log.info("[뉴스] 요약 완료 %d건, 브리핑 %d줄 (%.1f초, %s)",
             len(summarized), len(briefing), time.monotonic() - t1, generator)
    today = _today()

    # 기사가 brief_date 를 참조하므로 브리핑 행을 먼저 만든다.
    # 같은 날짜를 다시 돌리면 이전 기사를 지우고 새로 넣는다.
    sb.table("news_briefings").upsert({
        "brief_date": today, "lines": briefing, "article_count": len(summarized),
        "generator": generator, "collected_at": datetime.now(KST).isoformat(),
    }, on_conflict="brief_date").execute()
    sb.table("news_articles").delete().eq("brief_date", today).execute()

    rows = [{"brief_date": today, "published_at": a["published_at"], "title": a["title"][:500],
             "press": a.get("press"), "url": a["url"], "url_key": a["url_key"],
             "category": a["category"], "summary": a.get("summary"),
             "is_key": bool(a.get("is_key"))}
            for a in summarized]
    for i in range(0, len(rows), 100):                      # 큰 배열은 나눠서 넣는다
        sb.table("news_articles").insert(rows[i:i + 100]).execute()

    if len(rows) != len(summarized):
        sb.table("news_briefings").update({"article_count": len(rows)}).eq("brief_date", today).execute()

    log.info("[뉴스] 저장 완료 %s — %d건 (전체 %.1f초)", today, len(rows), time.monotonic() - t0)
    return {"date": today, "collected": len(articles), "saved": len(rows),
            "briefing_lines": len(briefing), "generator": generator,
            "errors": errors[:5], "actor": actor}


@router.delete("/daily")
def delete_day(date: str = Query(..., description="YYYY-MM-DD"),
               authorization: Optional[str] = Header(None),
               x_cron_secret: Optional[str] = Header(None)):
    """오래된 브리핑 정리용."""
    _authorize_collect(authorization, x_cron_secret)
    sb = get_supabase()
    sb.table("news_articles").delete().eq("brief_date", date).execute()
    sb.table("news_briefings").delete().eq("brief_date", date).execute()
    return {"deleted": date}
