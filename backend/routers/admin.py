from typing import Optional
from fastapi import APIRouter, Depends
from dependencies import get_supabase, require_admin, hash_password
from fastapi import HTTPException
from pydantic import BaseModel

router = APIRouter()

@router.get("/nursing-homes")
def get_nursing_homes(user: dict = Depends(require_admin)):
    sb = get_supabase()
    res = sb.table("nursing_homes").select("*").execute()
    return res.data

@router.get("/surveyors")
def get_surveyors(user: dict = Depends(require_admin)):
    sb = get_supabase()
    res = sb.table("surveyors").select("*").execute()
    return res.data

@router.get("/elderly")
def get_elderly(user: dict = Depends(require_admin)):
    sb = get_supabase()
    res = sb.table("elderly_residents").select("*").execute()
    return res.data

@router.get("/progress")
def get_all_progress(user: dict = Depends(require_admin)):
    sb = get_supabase()
    res = sb.table("survey_progress").select("*").execute()
    data = res.data

    total = len(data)
    if total == 0:
        return {"rows": [], "stats": {}}

    stats = {
        "total": total,
        "basic_completed": sum(1 for r in data if r.get("basic_survey_completed")),
        "nutrition_completed": sum(1 for r in data if r.get("nutrition_survey_completed")),
        "satisfaction_completed": sum(1 for r in data if r.get("satisfaction_survey_completed")),
        "all_completed": sum(1 for r in data if r.get("all_surveys_completed")),
    }
    return {"rows": data, "stats": stats}

@router.get("/survey-data/{survey_type}")
def get_survey_data(survey_type: str, user: dict = Depends(require_admin)):
    table_map = {
        "basic": "basic_survey",
        "nutrition": "nutrition_survey",
        "satisfaction": "satisfaction_survey",
    }
    table = table_map.get(survey_type)
    if not table:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="잘못된 설문 유형입니다.")
    sb = get_supabase()
    res = sb.table(table).select("*").execute()
    return res.data


# ─────────────────────────── 요양원 담당자 계정 ───────────────────────────

class StaffCreate(BaseModel):
    id: str
    nursing_home_id: str
    name: str
    password: str
    role: str = "staff"


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/staff")
def list_staff(user: dict = Depends(require_admin)):
    sb = get_supabase()
    return sb.table("facility_staff").select("id,nursing_home_id,name,role,is_active,created_at").execute().data


@router.post("/staff")
def create_staff(req: StaffCreate, user: dict = Depends(require_admin)):
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")
    sb = get_supabase()
    if sb.table("facility_staff").select("id").eq("id", req.id).execute().data:
        raise HTTPException(status_code=409, detail="이미 존재하는 담당자 ID입니다.")
    if not sb.table("nursing_homes").select("id").eq("id", req.nursing_home_id).execute().data:
        raise HTTPException(status_code=404, detail="요양원 ID가 없습니다.")
    sb.table("facility_staff").insert({"id": req.id, "nursing_home_id": req.nursing_home_id, "name": req.name,
                                       "role": req.role, "is_active": True, "password_hash": hash_password(req.password)}).execute()
    return {"success": True}


@router.put("/staff/{staff_id}")
def update_staff(staff_id: str, req: StaffUpdate, user: dict = Depends(require_admin)):
    d = {k: v for k, v in req.model_dump().items() if v is not None and k != "password"}
    if req.password:
        if len(req.password) < 8:
            raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")
        d["password_hash"] = hash_password(req.password)
    if not d:
        return {"success": True}
    get_supabase().table("facility_staff").update(d).eq("id", staff_id).execute()
    return {"success": True}


# ─────────────────────────── 유형 모델 ───────────────────────────

@router.get("/type-models")
def list_models(user: dict = Depends(require_admin)):
    return get_supabase().table("type_models").select("*").order("created_at", desc=True).execute().data


@router.post("/type-models/{version}/activate")
def activate_model(version: str, user: dict = Depends(require_admin)):
    sb = get_supabase()
    if not sb.table("type_models").select("version").eq("version", version).execute().data:
        raise HTTPException(status_code=404, detail="모델 버전이 없습니다.")
    sb.table("type_models").update({"is_active": False}).neq("version", version).execute()
    sb.table("type_models").update({"is_active": True}).eq("version", version).execute()
    return {"success": True}
