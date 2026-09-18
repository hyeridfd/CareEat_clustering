# -*- coding: utf-8 -*-
"""
어르신 기본정보·진단·약물·알레르기 (프로필 탭) 와 이력 타임라인 (이력 탭)

care.py 와 같은 규칙을 따른다:
  · 모든 조회·쓰기는 require_staff 로 시설 범위를 잡고 nursing_home_id 로 격리
  · 어르신 소유권은 _resident() 로 매번 확인
  · 응답은 dict 그대로, 요청 바디만 Pydantic
"""
import json
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from care import ocr
from dependencies import get_supabase, require_staff

router = APIRouter()
KST = ZoneInfo("Asia/Seoul")


def _now() -> str:
    return datetime.now(KST).isoformat()


def _resident(sb, home: str, eid: str) -> dict:
    r = (sb.table("elderly_residents").select("*")
         .eq("id", eid).eq("nursing_home_id", home).limit(1).execute())
    if not r.data:
        raise HTTPException(status_code=404, detail="어르신을 찾을 수 없습니다.")
    return r.data[0]


def _owned(sb, table: str, home: str, eid: str, rid: str) -> dict:
    r = (sb.table(table).select("*")
         .eq("id", rid).eq("elderly_id", eid).eq("nursing_home_id", home).limit(1).execute())
    if not r.data:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")
    return r.data[0]


# ─────────────────── 설문에서 채울 수 있는 값 ───────────────────
# 기초조사표·보호자 등록 정보에서 프로필 빈칸을 미리 채워 준다.
# 담당자가 확인하고 '저장'을 눌러야 실제로 저장된다.
_GENDER = {"여자": "female", "여성": "female", "남자": "male", "남성": "male"}
_LTC = {"1등급": "1등급", "2등급": "2등급", "3등급": "3등급", "4등급 이상": "4등급 이상",
        "4등급": "4등급", "5등급": "5등급", "인지지원등급": "인지지원등급"}
_TEXTURE = {"일반식": 0, "다진식": 1, "갈은식(믹서식)": 2, "갈은식": 2, "유동식": 3}


def _json_list(x):
    """리스트, JSON 문자열, 문자열로 한 번 더 감싸인 JSON 모두 받아 문자열 목록으로 돌려준다."""
    for _ in range(3):
        if isinstance(x, list):
            return [str(i).strip() for i in x if str(i).strip()]
        if not isinstance(x, str) or not x.strip():
            return []
        try:
            x = json.loads(x)
        except json.JSONDecodeError:
            return []
    return []


def _survey_source(sb, home: str, eid: str) -> dict:
    """기초조사표 + 등록된 보호자에서 프로필 기본값과 진단·복약 목록을 뽑는다."""
    b = (sb.table("basic_survey")
         .select("age,gender,care_grade,education,meal_type,diseases,medications,updated_at")
         .eq("elderly_id", eid).limit(1).execute().data or [None])[0]
    g = (sb.table("guardians").select("name,relation,phone")
         .eq("elderly_id", eid).eq("nursing_home_id", home).eq("is_active", True)
         .limit(1).execute().data or [None])[0]

    defaults, birth_year = {}, None
    if b:
        try:
            y = int(float(b.get("age")))
            birth_year = y if 1900 < y < 2100 else None
        except (TypeError, ValueError):
            birth_year = None
        if b.get("gender") in _GENDER:
            defaults["gender"] = _GENDER[b["gender"]]
        if b.get("care_grade") in _LTC:
            defaults["ltc_grade"] = _LTC[b["care_grade"]]
        if b.get("meal_type") in _TEXTURE:
            defaults["texture_level"] = _TEXTURE[b["meal_type"]]
        if str(b.get("education") or "").strip():
            defaults["education"] = str(b["education"]).strip()
    if g:
        if g.get("name"):
            defaults["guardian_name"] = g["name"]
        if g.get("relation"):
            defaults["guardian_relation"] = g["relation"]
        if g.get("phone"):
            defaults["guardian_phone"] = g["phone"]

    diseases = [d for d in _json_list(b.get("diseases") if b else None) if d not in ("없음", "기타")]
    meds = _json_list(b.get("medications") if b else None)
    return {"defaults": defaults, "birth_year": birth_year, "diseases": diseases,
            "medications": meds, "survey_at": (b or {}).get("updated_at")}


# ─────────────────────────── 요청 모델 ───────────────────────────

class ProfileIn(BaseModel):
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    admit_date: Optional[str] = None
    room: Optional[str] = None
    ltc_grade: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_relation: Optional[str] = None
    guardian_phone: Optional[str] = None
    texture_level: Optional[int] = None
    thickener: Optional[str] = None
    therapeutic_diet: Optional[str] = None
    education: Optional[str] = None
    alcohol: Optional[str] = None
    smoking: Optional[str] = None
    banned_foods: Optional[list] = None
    notes: Optional[str] = None


class ConditionIn(BaseModel):
    name: str
    status: str = "active"
    diagnosed_on: Optional[str] = None
    note: Optional[str] = None


class MedicationIn(BaseModel):
    name: str
    dose: Optional[str] = None
    schedule: list = []
    started_on: Optional[str] = None
    ended_on: Optional[str] = None
    is_active: bool = True
    food_caution: Optional[str] = None
    note: Optional[str] = None


class AllergyIn(BaseModel):
    allergen: str
    severity: str = "mild"
    reaction: Optional[str] = None
    note: Optional[str] = None


# ─────────────────────────── 프로필 ───────────────────────────

@router.get("/residents/{eid}/profile")
def get_profile(eid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    res = _resident(sb, home, eid)

    prof = (sb.table("resident_profiles").select("*")
            .eq("elderly_id", eid).limit(1).execute().data or [None])[0]
    conditions = (sb.table("resident_conditions").select("*")
                  .eq("elderly_id", eid).eq("nursing_home_id", home)
                  .order("created_at", desc=True).execute().data or [])
    medications = (sb.table("resident_medications").select("*")
                   .eq("elderly_id", eid).eq("nursing_home_id", home)
                   .order("is_active", desc=True).order("created_at", desc=True).execute().data or [])
    allergies = (sb.table("resident_allergies").select("*")
                 .eq("elderly_id", eid).eq("nursing_home_id", home)
                 .order("created_at", desc=True).execute().data or [])

    # 설문에서 이미 받은 진단 정보는 참고용으로 같이 내려 준다 (직접 입력과 구분)
    latest = (sb.table("care_assessments").select("features, created_at")
              .eq("elderly_id", eid).eq("nursing_home_id", home)
              .order("created_at", desc=True).limit(1).execute().data or [])
    survey_dx = []
    if latest:
        f = latest[0].get("features") or {}
        labels = {"dx_dementia": "치매", "dx_diabetes": "당뇨", "dx_hypertension": "고혈압",
                  "dx_parkinson": "파킨슨", "dx_stroke": "뇌혈관질환", "dx_depression": "우울증"}
        survey_dx = [label for k, label in labels.items() if f.get(k)]

    src = _survey_source(sb, home, eid)
    have_c = {c["name"] for c in conditions}
    have_m = {m["name"] for m in medications}
    return {"resident": res, "profile": prof, "conditions": conditions,
            "medications": medications, "allergies": allergies,
            "survey_diagnoses": survey_dx or src["diseases"],
            "survey_defaults": src["defaults"],
            "survey_birth_year": src["birth_year"],
            "survey_import": {"conditions": [d for d in src["diseases"] if d not in have_c],
                              "medications": [m for m in src["medications"] if m not in have_m]},
            "survey_updated_at": latest[0]["created_at"] if latest else src["survey_at"]}


@router.put("/residents/{eid}/profile")
def save_profile(eid: str, req: ProfileIn, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    rec = {k: v for k, v in req.model_dump().items() if v is not None}
    rec.update({"elderly_id": eid, "nursing_home_id": home,
                "updated_by": user["actor"], "updated_at": _now()})
    out = sb.table("resident_profiles").upsert(rec, on_conflict="elderly_id").execute()
    return out.data[0] if out.data else rec


# ─────────────────── 진단 · 약물 · 알레르기 (같은 모양) ───────────────────

_LISTS = {
    "conditions": ("resident_conditions", ConditionIn),
    "medications": ("resident_medications", MedicationIn),
    "allergies": ("resident_allergies", AllergyIn),
}


def _add(kind: str, eid: str, body: dict, user: dict):
    table, _ = _LISTS[kind]
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    rec = {**body, "elderly_id": eid, "nursing_home_id": home, "recorded_by": user["actor"]}
    out = sb.table(table).insert(rec).execute()
    return out.data[0] if out.data else rec


def _update(kind: str, eid: str, rid: str, body: dict, user: dict):
    table, _ = _LISTS[kind]
    sb, home = get_supabase(), user["scope_home"]
    _owned(sb, table, home, eid, rid)
    out = sb.table(table).update(body).eq("id", rid).execute()
    return out.data[0] if out.data else body


def _delete(kind: str, eid: str, rid: str, user: dict):
    table, _ = _LISTS[kind]
    sb, home = get_supabase(), user["scope_home"]
    _owned(sb, table, home, eid, rid)
    sb.table(table).delete().eq("id", rid).execute()
    return {"deleted": rid}


@router.post("/residents/{eid}/conditions")
def add_condition(eid: str, req: ConditionIn, user: dict = Depends(require_staff)):
    return _add("conditions", eid, req.model_dump(), user)


@router.put("/residents/{eid}/conditions/{rid}")
def update_condition(eid: str, rid: str, req: ConditionIn, user: dict = Depends(require_staff)):
    return _update("conditions", eid, rid, req.model_dump(), user)


@router.delete("/residents/{eid}/conditions/{rid}")
def delete_condition(eid: str, rid: str, user: dict = Depends(require_staff)):
    return _delete("conditions", eid, rid, user)


@router.post("/residents/{eid}/medications")
def add_medication(eid: str, req: MedicationIn, user: dict = Depends(require_staff)):
    return _add("medications", eid, req.model_dump(), user)


@router.put("/residents/{eid}/medications/{rid}")
def update_medication(eid: str, rid: str, req: MedicationIn, user: dict = Depends(require_staff)):
    return _update("medications", eid, rid, req.model_dump(), user)


@router.delete("/residents/{eid}/medications/{rid}")
def delete_medication(eid: str, rid: str, user: dict = Depends(require_staff)):
    return _delete("medications", eid, rid, user)


@router.post("/residents/{eid}/allergies")
def add_allergy(eid: str, req: AllergyIn, user: dict = Depends(require_staff)):
    return _add("allergies", eid, req.model_dump(), user)


@router.delete("/residents/{eid}/allergies/{rid}")
def delete_allergy(eid: str, rid: str, user: dict = Depends(require_staff)):
    return _delete("allergies", eid, rid, user)


# ─────────────────────────── 이력 ───────────────────────────

SURVEYS = [("basic_survey", "기본 조사"), ("nutrition_survey", "영양 조사"),
           ("satisfaction_survey", "급식 만족도"), ("bluefood_survey", "블루푸드 조사")]

# 추이로 보여 줄 지표 — (키, 이름, 단위, 좋은 방향, 축 최댓값)
TREND = [
    ("mna_sf", "MNA-SF", "점", "up", 14),
    ("bmi", "BMI", "kg/m²", "up", None),
    ("intake_total", "전체 섭취율", "%", "up", 100),
    ("kmbi_pct", "K-MBI", "%", "up", 100),
    ("gds", "GDS-SF", "점", "down", 15),
    ("sat_overall", "급식 만족", "점", "up", 5),
]


def _ts(row: dict) -> Optional[str]:
    for k in ("created_at", "updated_at", "recorded_at", "submitted_at"):
        if row.get(k):
            return row[k]
    return None



@router.post("/residents/{eid}/import-from-survey")
def import_from_survey(eid: str, user: dict = Depends(require_staff)):
    """기초조사표의 진단·복약 목록을 진단·복약 기록으로 옮긴다 (이미 있는 이름은 건너뛴다)."""
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    src = _survey_source(sb, home, eid)
    have_c = {c["name"] for c in (sb.table("resident_conditions").select("name")
                                  .eq("elderly_id", eid).eq("nursing_home_id", home).execute().data or [])}
    have_m = {m["name"] for m in (sb.table("resident_medications").select("name")
                                  .eq("elderly_id", eid).eq("nursing_home_id", home).execute().data or [])}
    actor = user["actor"]
    rows_c = [{"elderly_id": eid, "nursing_home_id": home, "name": n, "status": "active",
               "note": "기초조사표에서 가져옴", "recorded_by": actor}
              for n in src["diseases"] if n not in have_c]
    rows_m = [{"elderly_id": eid, "nursing_home_id": home, "name": n, "schedule": [], "is_active": True,
               "note": "기초조사표에서 가져옴", "recorded_by": actor}
              for n in src["medications"] if n not in have_m]
    if rows_c:
        sb.table("resident_conditions").insert(rows_c).execute()
    if rows_m:
        sb.table("resident_medications").insert(rows_m).execute()
    return {"conditions": len(rows_c), "medications": len(rows_m)}



@router.get("/ocr-status")
def ocr_status(user: dict = Depends(require_staff)):
    """약봉투 판독에 쓰는 모델 확인용"""
    return ocr.ocr_status()


@router.post("/residents/{eid}/medications/ocr")
async def read_medication_photo(eid: str, file: UploadFile = File(...),
                                provider: Optional[str] = None,
                                user: dict = Depends(require_staff)):
    """약봉투·처방전 사진에서 약 이름을 읽어 후보로 돌려준다 (저장하지 않음)."""
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    data = await file.read()
    try:
        return ocr.read_medication_image(data, file.content_type, provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"사진을 읽지 못했습니다: {str(e)[:160]}")


@router.get("/residents/{eid}/history")
def history(eid: str, user: dict = Depends(require_staff)):
    """설문·평가·솔루션·발송·돌봄기록을 한 줄기로 모으고, 지표 추이를 함께 돌려준다."""
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    events = []

    # 설문 — 테이블이 없거나 컬럼이 달라도 이력 전체가 죽지 않도록 각각 감싼다
    for table, label in SURVEYS:
        try:
            rows = sb.table(table).select("*").eq("elderly_id", eid).execute().data or []
        except Exception:                                   # noqa: BLE001
            continue
        for r in rows:
            t = _ts(r)
            if t:
                events.append({"at": t, "kind": "survey", "title": f"{label} 작성", "detail": None})

    for a in (sb.table("care_assessments")
              .select("id, created_at, type_code, type_name, priority_level, priority_score, model_version, is_borderline")
              .eq("elderly_id", eid).eq("nursing_home_id", home)
              .order("created_at", desc=True).limit(100).execute().data or []):
        events.append({"at": a["created_at"], "kind": "assessment",
                       "title": f"유형 평가 · {a.get('type_name') or a['type_code']}",
                       "detail": f"우선순위 {a['priority_level']} ({a['priority_score']:.0f}점)"
                                 + (" · 경계 사례" if a.get("is_borderline") else ""),
                       "ref": a["id"]})

    for s in (sb.table("care_solutions").select("id, created_at, approved_at, status, generator")
              .eq("elderly_id", eid).eq("nursing_home_id", home)
              .order("created_at", desc=True).limit(100).execute().data or []):
        events.append({"at": s["created_at"], "kind": "solution", "title": "돌봄 솔루션 생성",
                       "detail": f"생성기 {s.get('generator') or '-'}", "ref": s["id"]})
        if s.get("approved_at"):
            events.append({"at": s["approved_at"], "kind": "approval", "title": "솔루션 승인",
                           "detail": None, "ref": s["id"]})

    for n in (sb.table("care_notifications").select("id, created_at, status, channel, mode")
              .eq("elderly_id", eid).eq("nursing_home_id", home)
              .order("created_at", desc=True).limit(100).execute().data or []):
        events.append({"at": n["created_at"], "kind": "notification", "title": "보호자 안내 발송",
                       "detail": f"{n.get('status')} · {n.get('mode')}", "ref": n["id"]})

    for c in (sb.table("care_actions").select("id, recorded_at, action, status, outcome_note")
              .eq("elderly_id", eid).eq("nursing_home_id", home)
              .order("recorded_at", desc=True).limit(100).execute().data or []):
        events.append({"at": c["recorded_at"], "kind": "action", "title": c["action"],
                       "detail": {"done": "수행", "planned": "예정", "skipped": "미수행"}.get(c["status"]),
                       "ref": c["id"]})

    events.sort(key=lambda e: e["at"], reverse=True)

    # 지표 추이 — 평가 시점마다 남은 features 값을 뽑는다 (오래된 것부터)
    series_rows = (sb.table("care_assessments").select("created_at, features")
                   .eq("elderly_id", eid).eq("nursing_home_id", home)
                   .order("created_at").limit(60).execute().data or [])
    trends = []
    for key, label, unit, better, axis_max in TREND:
        points = [{"at": r["created_at"], "v": float((r.get("features") or {})[key])}
                  for r in series_rows if (r.get("features") or {}).get(key) is not None]
        if points:
            trends.append({"key": key, "label": label, "unit": unit, "better": better,
                           "axis_max": axis_max, "points": points})

    return {"events": events[:200], "trends": trends}
