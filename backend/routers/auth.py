from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from dependencies import get_supabase, create_token, verify_password

router = APIRouter()

class LoginRequest(BaseModel):
    nursing_home_id: str
    surveyor_id: str
    elderly_id: str

class AdminLoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    token: str
    nursing_home_id: str
    surveyor_id: str
    elderly_id: str
    nursing_home_name: str

@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    sb = get_supabase()

    # 요양원 확인
    nh = sb.table("nursing_homes").select("id,name").eq("id", req.nursing_home_id).execute()
    if not nh.data:
        raise HTTPException(status_code=401, detail="요양원 ID가 존재하지 않습니다.")

    # 조사원 확인 (해당 요양원 소속)
    sv = sb.table("surveyors").select("id").eq("id", req.surveyor_id).eq("nursing_home_id", req.nursing_home_id).execute()
    if not sv.data:
        raise HTTPException(status_code=401, detail="조사원 ID가 존재하지 않거나 해당 요양원에 속하지 않습니다.")

    # 어르신 확인 (해당 요양원 소속)
    el = sb.table("elderly_residents").select("id").eq("id", req.elderly_id).eq("nursing_home_id", req.nursing_home_id).execute()
    if not el.data:
        raise HTTPException(status_code=401, detail="어르신 ID가 존재하지 않거나 해당 요양원에 속하지 않습니다.")

    token = create_token({
        "nursing_home_id": req.nursing_home_id,
        "surveyor_id": req.surveyor_id,
        "elderly_id": req.elderly_id,
        "is_admin": False,
    })

    return LoginResponse(
        token=token,
        nursing_home_id=req.nursing_home_id,
        surveyor_id=req.surveyor_id,
        elderly_id=req.elderly_id,
        nursing_home_name=nh.data[0]["name"],
    )

@router.post("/admin-login")
def admin_login(req: AdminLoginRequest):
    correct = os.getenv("ADMIN_PASSWORD", "admin123")
    if req.password != correct:
        raise HTTPException(status_code=401, detail="비밀번호가 올바르지 않습니다.")
    token = create_token({"is_admin": True})
    return {"token": token}


# ─────────────────────────── 요양원 담당자 로그인 ───────────────────────────

class StaffLoginRequest(BaseModel):
    staff_id: str
    password: str


@router.post("/staff-login")
def staff_login(req: StaffLoginRequest):
    sb = get_supabase()
    r = sb.table("facility_staff").select("*").eq("id", req.staff_id.strip()).execute()
    st = r.data[0] if r.data else None
    if not st or st.get("is_active") is False or not verify_password(req.password, st["password_hash"]):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    nh = sb.table("nursing_homes").select("id,name").eq("id", st["nursing_home_id"]).execute()
    token = create_token({"role": "staff", "staff_id": st["id"], "staff_name": st["name"],
                          "staff_role": st.get("role", "staff"), "nursing_home_id": st["nursing_home_id"],
                          "is_admin": False})
    return {"token": token, "staff_id": st["id"], "staff_name": st["name"], "role": "staff",
            "staff_role": st.get("role", "staff"), "nursing_home_id": st["nursing_home_id"],
            "nursing_home_name": nh.data[0]["name"] if nh.data else st["nursing_home_id"]}
