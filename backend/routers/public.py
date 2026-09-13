# -*- coding: utf-8 -*-
"""보호자용 공개 리포트 (알림톡 버튼 링크) — 토큰·만료일로 보호, 점수·척도는 노출하지 않음"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from dependencies import get_supabase

router = APIRouter()


@router.get("/report/{token}")
def guardian_report(token: str):
    sb = get_supabase()
    r = sb.table("care_notifications").select("*").eq("report_token", token).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")
    n = r.data[0]
    exp = datetime.fromisoformat(n["report_expires_at"].replace("Z", "+00:00"))
    if exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="열람 기간이 지났습니다. 시설에 문의해 주세요.")
    s = sb.table("care_solutions").select("content,guardian_message,status").eq("id", n["solution_id"]).execute().data
    if not s or s[0]["status"] not in ("approved", "sent"):
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")
    s = s[0]
    v = n["variables"]
    focus = []
    for a in s["content"].get("staff_actions", []):
        if a.get("category") and a["category"] not in focus and a["category"] != "재평가":
            focus.append(a["category"])
    return {"facility": v.get("시설명"), "resident": v.get("어르신"), "guardian": v.get("보호자"),
            "assessed_on": v.get("평가일"), "care_group": v.get("관리구분"), "focus": focus,
            "message": s["guardian_message"], "meal_guidance": s["content"].get("meal_guidance", [])[:4],
            "expires_on": v.get("만료일")}
