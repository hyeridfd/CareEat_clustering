# -*- coding: utf-8 -*-
"""보호자용 공개 리포트 (알림톡 버튼 링크) — 토큰·만료일로 보호, 점수·척도는 노출하지 않음"""
from datetime import datetime, timezone

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

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


# ─────────────────────────── 시설 가입 신청 (공개) ───────────────────────────

class FacilityApplication(BaseModel):
    facility_name: str
    facility_kind: Optional[str] = None
    ltc_code: Optional[str] = None
    address: Optional[str] = None
    resident_count: Optional[int] = None
    manager_name: str
    manager_role: Optional[str] = None
    manager_phone: str
    manager_email: Optional[str] = None
    desired_staff_id: Optional[str] = None
    message: Optional[str] = None


@router.post("/facility-apply")
def facility_apply(req: FacilityApplication):
    d = req.model_dump()
    d["facility_name"] = (d["facility_name"] or "").strip()
    d["manager_name"] = (d["manager_name"] or "").strip()
    phone = re.sub(r"\D", "", d.get("manager_phone") or "")
    if len(d["facility_name"]) < 2:
        raise HTTPException(status_code=400, detail="기관명을 정확히 입력해 주세요.")
    if not re.fullmatch(r"0\d{8,10}", phone):
        raise HTTPException(status_code=400, detail="연락처 형식을 확인해 주세요.")
    d["manager_phone"] = phone
    if d.get("desired_staff_id"):
        sid = d["desired_staff_id"].strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{4,30}", sid):
            raise HTTPException(status_code=400, detail="희망 ID는 영문 소문자·숫자·밑줄 4~30자로 입력해 주세요.")
        d["desired_staff_id"] = sid
    d["status"] = "pending"
    sb = get_supabase()
    recent = sb.table("facility_applications").select("id").eq("manager_phone", phone).eq("status", "pending").execute()
    if recent.data:
        raise HTTPException(status_code=409, detail="같은 연락처로 접수된 신청이 검토 중입니다. 안내를 기다려 주세요.")
    sb.table("facility_applications").insert(d).execute()
    return {"success": True}
