from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Any, Optional
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from dependencies import get_supabase, get_current_user, get_kst_now

BUCKET = "nutrition-photos"
KST = ZoneInfo("Asia/Seoul")

router = APIRouter()

# ────────────────────────────────────────────
# 설문 진행 상황
# ────────────────────────────────────────────

@router.get("/progress")
def get_progress(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    elderly_id = user["elderly_id"]

    res = sb.table("survey_progress").select("*").eq("elderly_id", elderly_id).execute()
    if res.data:
        return res.data[0]

    # 없으면 생성
    new_progress = {
        "elderly_id": elderly_id,
        "surveyor_id": user["surveyor_id"],
        "nursing_home_id": user["nursing_home_id"],
        "basic_survey_completed": False,
        "nutrition_survey_completed": False,
        "satisfaction_survey_completed": False,
        "all_surveys_completed": False,
    }
    res = sb.table("survey_progress").insert(new_progress).execute()
    return res.data[0]


def _mark_complete(sb, elderly_id: str, field: str):
    """설문 완료 표시 및 전체 완료 여부 갱신"""
    sb.table("survey_progress").update({
        field: True,
        "last_updated": get_kst_now(),
    }).eq("elderly_id", elderly_id).execute()

    # 전체 완료 확인
    prog = sb.table("survey_progress").select(
        "basic_survey_completed,nutrition_survey_completed,satisfaction_survey_completed"
    ).eq("elderly_id", elderly_id).execute()

    if prog.data:
        p = prog.data[0]
        if p["basic_survey_completed"] and p["nutrition_survey_completed"] and p["satisfaction_survey_completed"]:
            sb.table("survey_progress").update({
                "all_surveys_completed": True,
                "last_updated": get_kst_now(),
            }).eq("elderly_id", elderly_id).execute()


def _mark_nutrition_complete(sb, elderly_id: str, data: dict):
    """영양 조사 완료 여부: 5일치 모두 배식량+잔반량+사진 입력됐는지 확인"""
    import json as _json

    meal_portions = data.get("meal_portions", {})
    plate_waste = data.get("plate_waste", {})
    photos = data.get("photos", {})

    if isinstance(meal_portions, str):
        meal_portions = _json.loads(meal_portions)
    if isinstance(plate_waste, str):
        plate_waste = _json.loads(plate_waste)
    if isinstance(photos, str):
        photos = _json.loads(photos)

    MEALS = ['아침', '간식1', '점심', '간식2', '저녁']

    # 각 일차별 완료 여부:
    # - 배식량(meal_portions): 해당 일차 데이터 있어야 함
    # - 잔반량(plate_waste): 해당 일차 데이터 있어야 함
    # - 사진: 각 끼니별 식전+식후 2장씩 = 10장 모두 있어야 함
    completed_days = []
    for day in range(1, 6):
        day_key = f"day{day}"
        mp = meal_portions.get(day_key, {})
        pw = plate_waste.get(day_key, {})

        has_portions = bool(mp)
        has_waste = bool(pw)

        # 사진: 해당 일차의 모든 끼니 식전+식후 확인
        photo_count = sum(
            1 for meal in MEALS
            for ptype in ['before', 'after']
            if photos.get(f"{day_key}_{meal}_{ptype}", {}).get('url')
        )
        has_photos = photo_count >= 10  # 5끼니 × 2장 = 10장

        if has_portions and has_waste and has_photos:
            completed_days.append(day)

    completed_count = len(completed_days)
    all_done = completed_count >= 5

    # completed_days 정보도 저장 (어느 일차까지 했는지)
    import json as _json
    sb.table("survey_progress").update({
        "nutrition_survey_completed": all_done,
        "nutrition_completed_days": completed_count,
        "last_updated": get_kst_now(),
    }).eq("elderly_id", elderly_id).execute()

    # 전체 완료 확인
    prog = sb.table("survey_progress").select(
        "basic_survey_completed,nutrition_survey_completed,satisfaction_survey_completed"
    ).eq("elderly_id", elderly_id).execute()

    if prog.data:
        p = prog.data[0]
        if p["basic_survey_completed"] and p["nutrition_survey_completed"] and p["satisfaction_survey_completed"]:
            sb.table("survey_progress").update({
                "all_surveys_completed": True,
                "last_updated": get_kst_now(),
            }).eq("elderly_id", elderly_id).execute()


def _upsert(sb, table: str, data: dict, elderly_id: str):
    existing = sb.table(table).select("id").eq("elderly_id", elderly_id).execute()
    if existing.data:
        sb.table(table).update(data).eq("elderly_id", elderly_id).execute()
    else:
        sb.table(table).insert(data).execute()


# ────────────────────────────────────────────
# 기초 조사표
# ────────────────────────────────────────────

@router.get("/basic")
def get_basic_survey(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    res = sb.table("basic_survey").select("*").eq("elderly_id", user["elderly_id"]).execute()
    return res.data[0] if res.data else {}


class BasicSurveyPayload(BaseModel):
    data: dict[str, Any]

@router.post("/basic")
def save_basic_survey(payload: BasicSurveyPayload, user: dict = Depends(get_current_user)):
    sb = get_supabase()
    elderly_id = user["elderly_id"]

    d = payload.data.copy()

    # JSON 필드 직렬화
    for field in ("diseases", "medications"):
        if field in d and isinstance(d[field], list):
            d[field] = json.dumps(d[field], ensure_ascii=False)

    d.update({
        "elderly_id": elderly_id,
        "surveyor_id": user["surveyor_id"],
        "nursing_home_id": user["nursing_home_id"],
        "updated_at": get_kst_now(),
    })

    _upsert(sb, "basic_survey", d, elderly_id)
    _mark_complete(sb, elderly_id, "basic_survey_completed")
    return {"success": True}


# ────────────────────────────────────────────
# 영양 조사표
# ────────────────────────────────────────────

@router.get("/nutrition")
def get_nutrition_survey(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    res = sb.table("nutrition_survey").select("*").eq("elderly_id", user["elderly_id"]).execute()
    return res.data[0] if res.data else {}


class NutritionSurveyPayload(BaseModel):
    data: dict[str, Any]

@router.post("/nutrition")
def save_nutrition_survey(payload: NutritionSurveyPayload, user: dict = Depends(get_current_user)):
    sb = get_supabase()
    elderly_id = user["elderly_id"]

    d = payload.data.copy()

    # completed_days는 nutrition_survey 테이블에 저장하지 않고 따로 처리
    completed_days = d.pop("completed_days", None)

    for field in ("meal_portions", "plate_waste"):
        if field in d and isinstance(d[field], dict):
            d[field] = json.dumps(d[field], ensure_ascii=False)

    d.update({
        "elderly_id": elderly_id,
        "surveyor_id": user["surveyor_id"],
        "nursing_home_id": user["nursing_home_id"],
        "updated_at": get_kst_now(),
    })

    _upsert(sb, "nutrition_survey", d, elderly_id)
    _mark_nutrition_complete(sb, elderly_id, payload.data)
    return {"success": True}


# ────────────────────────────────────────────
# 만족도 조사표
# ────────────────────────────────────────────

@router.get("/satisfaction")
def get_satisfaction_survey(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    res = sb.table("satisfaction_survey").select("*").eq("elderly_id", user["elderly_id"]).execute()
    return res.data[0] if res.data else {}


class SatisfactionSurveyPayload(BaseModel):
    data: dict[str, Any]

@router.post("/satisfaction")
def save_satisfaction_survey(payload: SatisfactionSurveyPayload, user: dict = Depends(get_current_user)):
    sb = get_supabase()
    elderly_id = user["elderly_id"]

    d = payload.data.copy()

    # completed_days는 nutrition_survey 테이블에 저장하지 않고 따로 처리
    completed_days = d.pop("completed_days", None)

    for field in ("preferred_food_groups", "preferred_cooking_methods", "bluefood_preferences",
                  "desired_cooking_types", "desired_seafood_types"):
        if field in d and isinstance(d[field], list):
            d[field] = json.dumps(d[field], ensure_ascii=False)

    d.update({
        "elderly_id": elderly_id,
        "surveyor_id": user["surveyor_id"],
        "nursing_home_id": user["nursing_home_id"],
        "updated_at": get_kst_now(),
    })

    _upsert(sb, "satisfaction_survey", d, elderly_id)
    _mark_complete(sb, elderly_id, "satisfaction_survey_completed")
    return {"success": True}


# ────────────────────────────────────────────
# 식사 사진 업로드 (Supabase Storage)
# ────────────────────────────────────────────

@router.post("/nutrition/upload-photo")
async def upload_photo(
    day: int = Form(...),
    meal: str = Form(...),
    photo_type: str = Form(...),   # "before" | "after"
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    sb = get_supabase()
    elderly_id = user["elderly_id"]

    # 파일 확장자 추출
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "heic", "webp"):
        raise HTTPException(status_code=400, detail="jpg/png/heic/webp 파일만 업로드 가능합니다.")

    ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    # 한글 끼니명 → 영문 변환 (Supabase Storage 키에 한글 불가)
    meal_map = {"아침": "breakfast", "간식1": "snack1", "점심": "lunch", "간식2": "snack2", "저녁": "dinner"}
    meal_en = meal_map.get(meal, meal.replace(" ", "_"))
    file_name = f"{elderly_id}_{photo_type}_day{day}_{meal_en}_{ts}.{ext}"

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="파일이 비어있습니다.")
    if len(contents) > 20 * 1024 * 1024:  # 20MB 제한
        raise HTTPException(status_code=400, detail="파일 크기는 20MB 이하여야 합니다.")

    try:
        sb.storage.from_(BUCKET).upload(
            file_name,
            contents,
            file_options={"content-type": file.content_type or "image/jpeg"},
        )
    except Exception as e:
        # 같은 파일명이 이미 있으면 덮어쓰기
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            sb.storage.from_(BUCKET).update(
                file_name,
                contents,
                file_options={"content-type": file.content_type or "image/jpeg"},
            )
        else:
            raise HTTPException(status_code=500, detail=f"스토리지 업로드 실패: {str(e)}")

    public_url = sb.storage.from_(BUCKET).get_public_url(file_name)
    return {"success": True, "file_name": file_name, "public_url": public_url}


@router.delete("/nutrition/delete-photo")
def delete_photo(
    file_name: str,
    user: dict = Depends(get_current_user),
):
    sb = get_supabase()
    # 본인 사진만 삭제 가능 (파일명이 elderly_id로 시작)
    if not file_name.startswith(user["elderly_id"] + "_"):
        raise HTTPException(status_code=403, detail="본인의 사진만 삭제할 수 있습니다.")
    try:
        sb.storage.from_(BUCKET).remove([file_name])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"삭제 실패: {str(e)}")
    return {"success": True}


# ────────────────────────────────────────────
# 블루푸드 선호도 조사
# ────────────────────────────────────────────

@router.get("/bluefood")
def get_bluefood_survey(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    res = sb.table("bluefood_survey").select("*").eq("elderly_id", user["elderly_id"]).execute()
    return res.data[0] if res.data else {}


class BluefoodSurveyPayload(BaseModel):
    data: dict[str, Any]

@router.post("/bluefood")
def save_bluefood_survey(payload: BluefoodSurveyPayload, user: dict = Depends(get_current_user)):
    sb = get_supabase()
    elderly_id = user["elderly_id"]

    d = payload.data.copy()
    for field in ("selected_ingredients", "selected_menus"):
        if field in d and not isinstance(d[field], str):
            d[field] = json.dumps(d[field], ensure_ascii=False)

    d.update({
        "elderly_id": elderly_id,
        "surveyor_id": user["surveyor_id"],
        "nursing_home_id": user["nursing_home_id"],
        "updated_at": get_kst_now(),
    })

    _upsert(sb, "bluefood_survey", d, elderly_id)
    _mark_complete(sb, elderly_id, "bluefood_survey_completed")
    return {"success": True}

# ── 아래 코드를 backend/routers/surveys.py 파일 맨 끝에 추가해주세요 ──

@router.get("/nutrition/meal-form")
def get_meal_form(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    res = sb.table("elderly_residents").select("meal_form").eq("id", user["elderly_id"]).execute()
    if res.data:
        return {"meal_form": res.data[0].get("meal_form")}
    return {"meal_form": None}