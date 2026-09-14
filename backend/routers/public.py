# -*- coding: utf-8 -*-
"""보호자용 공개 리포트 (알림톡 버튼 링크) — 토큰·만료일로 보호, 점수·척도는 노출하지 않음"""
from datetime import datetime, timezone

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from care import engine
from care.report import build_report
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
    sol = sb.table("care_solutions").select("*").eq("id", n["solution_id"]).execute().data
    if not sol or sol[0]["status"] not in ("approved", "sent"):
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")
    sol = sol[0]
    a = sb.table("care_assessments").select("*").eq("id", sol["assessment_id"]).execute().data
    a = a[0] if a else {}
    type_meta = None
    try:
        m = engine.load_model(a.get("model_version"))
        tinfo = m.type_info(a["type_code"])
        type_meta = {m.code(i): m.type_info(m.code(i)) for i in range(m.k)}
    except Exception:
        tinfo = {"code": a.get("type_code"), "name": a.get("type_name"),
                 "guardian_label": a.get("type_name"), "description": ""}
    v = n["variables"] or {}
    rep = build_report(sb, n["nursing_home_id"], n["elderly_id"], audience="guardian",
                       assessment=a, solution=sol, facility_name=v.get("시설명"),
                       type_info=tinfo, guardian_name=v.get("보호자"), type_meta=type_meta)
    rep["expires_on"] = v.get("만료일")
    if v.get("어르신"):
        rep["resident"]["display_name"] = v["어르신"]
    return rep


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
