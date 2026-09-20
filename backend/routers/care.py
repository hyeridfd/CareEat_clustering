# -*- coding: utf-8 -*-
"""돌봄 관리 API — 유형·우선순위 평가, 솔루션, 보호자, 알림, 수행 기록 (요양원 담당자 전용)"""
from typing import Optional
import copy
import json
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from care import engine, priority as prio, solution as sol, notify, nutrition as nutri, retrieval as rag
from care.report import build_report
from care.data import fetch_all, fetch_surveys
from dependencies import create_token, get_supabase, require_staff, get_kst_now

router = APIRouter()


def jsonable(x):
    def conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, set):
            return list(o)
        return str(o)
    return json.loads(json.dumps(x, default=conv, ensure_ascii=False))


def _one(res, msg="찾을 수 없습니다."):
    if not res.data:
        raise HTTPException(status_code=404, detail=msg)
    return res.data[0]


def _resident(sb, home, eid):
    return _one(sb.table("elderly_residents").select("*").eq("id", eid).eq("nursing_home_id", home).execute(),
                "해당 요양원의 어르신이 아닙니다.")


def _display_name(r):
    return r.get("name") or r.get("elderly_name") or r["id"]


def _latest_by_elderly(rows):
    out = {}
    for r in rows:  # created_at desc 정렬 전제
        out.setdefault(r["elderly_id"], r)
    return out


def _model_info(model):
    return {"version": model.version, "k": model.k,
            "types": [model.type_info(model.code(i)) for i in range(model.k)]}


@router.get("/kakao-template")
def kakao_template(user: dict = Depends(require_staff)):
    """솔라피/카카오 템플릿 등록 화면에 입력할 내용 (현재 REPORT_BASE_URL 기준)"""
    return {**notify.template_for_registration(), "mode": notify._env("KAKAO_MODE", "dry_run"),
            "provider": notify._env("KAKAO_PROVIDER", "solapi")}


@router.get("/knowledge-status")
def knowledge_status(user: dict = Depends(require_staff)):
    """근거 문헌(RAG) 적재 현황 — 문헌별 문단 수·임베딩 수"""
    return rag.status()


@router.get("/llm-status")
def llm_status(user: dict = Depends(require_staff)):
    """LLM 설정 점검용 (키 값은 노출하지 않음)"""
    return sol.llm_status()


# ─────────────────────────── 현황 ───────────────────────────

@router.get("/overview")
def overview(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    nh = sb.table("nursing_homes").select("id,name").eq("id", home).execute()
    residents = fetch_all(sb, "elderly_residents", eq={"nursing_home_id": home})
    # 목록 화면은 features(식사기록·영양소) 를 쓰지 않으므로 필요한 열만 읽는다
    assess = _latest_by_elderly(fetch_all(
        sb, "care_assessments",
        "id,elderly_id,type_code,type_name,priority_score,priority_level,is_borderline,"
        "transition,model_version,created_at,priority_factors",
        eq={"nursing_home_id": home}, order="created_at", desc=True))
    sols = _latest_by_elderly(fetch_all(sb, "care_solutions", "id,elderly_id,status,created_at,generator",
                                        eq={"nursing_home_id": home}, order="created_at", desc=True))
    prog = {p["elderly_id"]: p for p in fetch_all(sb, "survey_progress", eq={"nursing_home_id": home})}
    try:
        model_info = _model_info(engine.load_model(engine.active_version(sb)))
    except Exception as e:
        model_info = {"error": str(e)}
    rows = []
    for r in residents:
        a = assess.get(r["id"])
        p = prog.get(r["id"], {})
        rows.append({
            "elderly_id": r["id"], "display_name": _display_name(r),
            "surveys": {"basic": bool(p.get("basic_survey_completed")),
                        "nutrition_days": p.get("nutrition_completed_days") or 0,
                        "satisfaction": bool(p.get("satisfaction_survey_completed"))},
            "assessment": a and {k: a[k] for k in ("id", "type_code", "type_name", "priority_score", "priority_level",
                                                   "is_borderline", "transition", "model_version", "created_at")},
            "top_factors": a and [f["label"] for f in a["priority_factors"] if f["points"] > 0][:3],
            "solution": sols.get(r["id"]),
        })
    rows.sort(key=lambda x: -(x["assessment"]["priority_score"] if x["assessment"] else -1))
    counts = {"high": 0, "medium": 0, "low": 0, "unassessed": 0}
    for x in rows:
        counts[x["assessment"]["priority_level"] if x["assessment"] else "unassessed"] += 1
    return {"facility": nh.data[0] if nh.data else {"id": home}, "model": model_info,
            "counts": counts, "residents": rows}


# ─────────────────────────── 목록 (솔루션·알림·보호자) ───────────────────────────

def _resident_names(sb, home):
    return {r["id"]: _display_name(r) for r in fetch_all(sb, "elderly_residents", eq={"nursing_home_id": home})}


@router.get("/solutions")
def list_solutions(status: Optional[str] = None, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    rows = fetch_all(sb, "care_solutions", eq={"nursing_home_id": home}, order="created_at", desc=True)
    if status:
        rows = [r for r in rows if r["status"] == status]
    names = _resident_names(sb, home)
    assess = {a["id"]: a for a in fetch_all(sb, "care_assessments", "id,type_code,type_name,priority_score,priority_level",
                                            eq={"nursing_home_id": home})}
    out = []
    for r in rows[:200]:
        a = assess.get(r["assessment_id"], {})
        out.append({"id": r["id"], "elderly_id": r["elderly_id"], "display_name": names.get(r["elderly_id"], r["elderly_id"]),
                    "status": r["status"], "generator": r["generator"], "created_at": r["created_at"],
                    "approved_at": r.get("approved_at"), "summary": (r["content"] or {}).get("summary", ""),
                    "guardian_message": r["guardian_message"], "flags": len(r.get("guardrail_flags") or []),
                    "type_code": a.get("type_code"), "type_name": a.get("type_name"),
                    "priority_score": a.get("priority_score"), "priority_level": a.get("priority_level")})
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("draft", "approved", "sent", "rejected")}
    return {"counts": counts, "solutions": out}


@router.get("/notifications")
def list_notifications(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    rows = fetch_all(sb, "care_notifications", eq={"nursing_home_id": home}, order="created_at", desc=True)[:200]
    names = _resident_names(sb, home)
    guardians = {g["id"]: g for g in fetch_all(sb, "guardians", eq={"nursing_home_id": home})}
    out = []
    for n in rows:
        g = guardians.get(n["guardian_id"], {})
        out.append({"id": n["id"], "elderly_id": n["elderly_id"], "display_name": names.get(n["elderly_id"], n["elderly_id"]),
                    "guardian_name": g.get("name"), "phone": notify.mask_phone(g.get("phone", "")),
                    "channel": n.get("channel"), "mode": n["mode"], "status": n["status"],
                    "created_at": n["created_at"], "rendered_text": n["rendered_text"],
                    "expires_at": n.get("report_expires_at"),
                    "error": (n.get("provider_response") or {}).get("reason")})
    stats = {"total": len(out), "sent": sum(1 for x in out if x["status"] == "sent"),
             "failed": sum(1 for x in out if x["status"] == "failed"),
             "previewed": sum(1 for x in out if x["status"] == "previewed")}
    return {"stats": stats, "notifications": out}


@router.get("/guardians")
def list_guardians(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    names = _resident_names(sb, home)
    rows = [g for g in fetch_all(sb, "guardians", eq={"nursing_home_id": home}) if g.get("is_active") is not False]
    return [{"id": g["id"], "elderly_id": g["elderly_id"], "display_name": names.get(g["elderly_id"], g["elderly_id"]),
             "name": g["name"], "relation": g.get("relation"), "phone": notify.mask_phone(g["phone"]),
             "consent_health_info": g.get("consent_health_info", False), "created_at": g.get("created_at")}
            for g in rows]


@router.get("/facility")
def facility_info(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    nh = sb.table("nursing_homes").select("*").eq("id", home).execute()
    residents = fetch_all(sb, "elderly_residents", eq={"nursing_home_id": home})
    staff = fetch_all(sb, "facility_staff", "id,name,role,is_active,created_at", eq={"nursing_home_id": home})
    try:
        model = _model_info(engine.load_model(engine.active_version(sb)))
    except Exception as e:
        model = {"error": str(e)}
    return {"facility": (nh.data[0] if nh.data else {"id": home}), "resident_count": len(residents),
            "staff": staff, "model": model,
            "me": {"staff_id": user.get("staff_id"), "name": user.get("staff_name"), "role": user.get("staff_role")}}


class ResidentIn(BaseModel):
    name: str
    elderly_id: Optional[str] = None
    meal_form: Optional[str] = None


@router.post("/residents")
def add_resident(req: ResidentIn, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    existing = fetch_all(sb, "elderly_residents", "id", eq={"nursing_home_id": home})
    eid = (req.elderly_id or "").strip()
    if not eid:
        seq = len(existing) + 1
        used = {r["id"] for r in existing}
        while f"{home}-{seq:03d}" in used:
            seq += 1
        eid = f"{home}-{seq:03d}"
    if sb.table("elderly_residents").select("id").eq("id", eid).execute().data:
        raise HTTPException(status_code=409, detail=f"이미 있는 어르신 ID입니다: {eid}")
    row = {"id": eid, "nursing_home_id": home, "name": req.name.strip()}
    if req.meal_form:
        row["meal_form"] = req.meal_form
    try:
        sb.table("elderly_residents").insert(row).execute()
    except Exception as e:  # name 컬럼이 없는 기존 스키마 대응
        if "name" in str(e):
            row.pop("name", None)
            sb.table("elderly_residents").insert(row).execute()
        else:
            raise
    return {"success": True, "elderly_id": eid}


@router.get("/residents/{eid}/report")
def resident_report(eid: str, user: dict = Depends(require_staff)):
    """담당자용 상세 리포트 (척도 점수·우선순위 포함)"""
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    a = sb.table("care_assessments").select("*").eq("elderly_id", eid).order("created_at", desc=True).limit(1).execute().data
    if not a:
        raise HTTPException(status_code=404, detail="먼저 유형·우선순위 평가를 실행하세요.")
    a = a[0]
    s = sb.table("care_solutions").select("*").eq("elderly_id", eid).order("created_at", desc=True).limit(1).execute().data
    try:
        tinfo = engine.load_model(a["model_version"]).type_info(a["type_code"])
    except Exception:
        tinfo = {"code": a["type_code"], "name": a["type_name"], "guardian_label": a["type_name"], "description": ""}
    return build_report(sb, home, eid, audience="staff", assessment=a,
                        solution=(s[0] if s else None), type_info=tinfo)


@router.post("/residents/{eid}/survey-token")
def survey_token(eid: str, user: dict = Depends(require_staff)):
    """담당자가 해당 어르신의 조사(설문) 화면을 바로 입력할 수 있는 토큰 발급."""
    sb, home = get_supabase(), user["scope_home"]
    r = _resident(sb, home, eid)
    surveyor_id = user.get("staff_id") or f"{home}_staff"
    if not sb.table("surveyors").select("id").eq("id", surveyor_id).execute().data:
        row = {"id": surveyor_id, "nursing_home_id": home}
        try:
            sb.table("surveyors").insert(row).execute()
        except Exception:  # name 등 필수 컬럼이 있는 스키마 대응
            sb.table("surveyors").insert({**row, "name": user.get("staff_name") or surveyor_id}).execute()
    token = create_token({"nursing_home_id": home, "surveyor_id": surveyor_id, "elderly_id": eid,
                          "is_admin": False, "mode": "staff_survey"})
    return {"token": token, "elderly_id": eid, "display_name": _display_name(r),
            "nursing_home_id": home, "surveyor_id": surveyor_id}


# ─────────────────────────── 평가 실행 ───────────────────────────

class AssessRequest(BaseModel):
    elderly_ids: Optional[list[str]] = None
    force: bool = False


@router.post("/assess")
def assess(req: AssessRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    try:
        model = engine.load_model(engine.active_version(sb))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"유형 모델을 불러올 수 없습니다: {e}")
    b, n, s = fetch_surveys(sb, home, req.elderly_ids)
    forms = {r["id"]: r.get("meal_form") for r in fetch_all(sb, "elderly_residents", eq={"nursing_home_id": home})}
    df = engine.build_features(b, n, s, meal_forms=forms)
    if df.empty:
        raise HTTPException(status_code=400, detail="평가할 기초조사 데이터가 없습니다.")
    res = model.assign(df)
    prev_all = _latest_by_elderly(fetch_all(sb, "care_assessments", eq={"nursing_home_id": home},
                                            in_={"elderly_id": df["elderly_id"].tolist()},
                                            order="created_at", desc=True))
    assessed, skipped, alerts = [], [], []
    for key, row in df.iterrows():
        eid = row["elderly_id"]
        a = res.loc[key]
        prev = prev_all.get(eid)
        upd = row.get("survey_updated_at")
        upd_iso = upd.isoformat() if upd is not None and not (isinstance(upd, float)) and str(upd) != "NaT" else None
        if (not req.force and prev and prev["model_version"] == model.version
                and prev.get("survey_updated_at") and upd_iso
                and not engine.features_stale(prev.get("features"))
                and datetime.fromisoformat(prev["survey_updated_at"]) >= datetime.fromisoformat(upd_iso)):
            skipped.append(eid)
            continue
        feats = engine.features_record(row)
        tinfo = model.type_info(a["type_code"])
        trans = engine.classify_transition(model, a["type_code"], prev)
        score, level, factors = prio.compute(feats, prev and prev.get("features"), tinfo, trans,
                                             bool(a["is_borderline"]))
        rec = jsonable({
            "elderly_id": eid, "nursing_home_id": home, "model_version": model.version,
            "type_code": a["type_code"], "type_name": tinfo["name"],
            "centroid_margin": a["centroid_margin"], "relative_margin": a["relative_margin"],
            "is_borderline": bool(a["is_borderline"]), "transition": {**trans, "second_type": a["second_code"],
                                                                     "deviations": a["deviations"]},
            "priority_score": score, "priority_level": level, "priority_factors": factors,
            "features": feats, "imputed_vars": list(a["imputed_vars"]), "survey_updated_at": upd_iso,
            "created_by": user["actor"],
        })
        sb.table("care_assessments").insert(rec).execute()
        assessed.append({"elderly_id": eid, "type_code": a["type_code"], "priority_score": score, "level": level})
        if trans["kind"] == "state_change":
            alerts.append({"elderly_id": eid, "from": trans.get("prev_type"), "to": a["type_code"]})
    return {"model_version": model.version, "assessed": assessed, "skipped": skipped, "type_changes": alerts}


# ─────────────────────────── 어르신 상세 ───────────────────────────

@router.get("/residents/{eid}")
def resident_detail(eid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    r = _resident(sb, home, eid)
    hist = sb.table("care_assessments").select("*").eq("elderly_id", eid).order("created_at", desc=True).limit(10).execute().data
    for h in hist[1:]:                       # 화면에서 쓰지 않는 식사 기록은 응답에서 덜어낸다
        fx = h.get("features")
        if isinstance(fx, dict):
            fx.pop("meal_log", None)
    sols = sb.table("care_solutions").select("*").eq("elderly_id", eid).order("created_at", desc=True).limit(10).execute().data
    gs = sb.table("guardians").select("*").eq("elderly_id", eid).eq("is_active", True).execute().data
    for g in gs:
        g["phone_masked"] = notify.mask_phone(g["phone"])
    notes = sb.table("care_notifications").select(
        "id,solution_id,guardian_id,mode,provider,rendered_text,status,created_at,report_expires_at"
    ).eq("elderly_id", eid).order("created_at", desc=True).limit(20).execute().data
    acts = sb.table("care_actions").select("*").eq("elderly_id", eid).order("recorded_at", desc=True).limit(30).execute().data
    type_info = None
    if hist:
        try:
            type_info = engine.load_model(hist[0]["model_version"]).type_info(hist[0]["type_code"])
        except Exception:
            type_info = {"code": hist[0]["type_code"], "name": hist[0]["type_name"]}
    nutrition = None
    if hist:
        f = hist[0].get("features") or {}
        nsum = f.get("nutrition") if isinstance(f.get("nutrition"), dict) else None
        if nsum is None and f.get("meal_log"):
            # 예전 평가에는 영양소가 없으므로 즉시 계산한다
            try:
                _, nsum = engine.nutri.enrich_meal_log(copy.deepcopy(f["meal_log"]), r.get("meal_form"), eid)
            except Exception:
                nsum = None
        if nsum:
            gender = "여자" if f.get("female") == 1 else "남자"
            fld = nutri.fields()
            keys = ["energy", "protein", "fiber", "ca", "na", "k"]
            nutrition = {"avg_day": nsum.get("avg_day") or {}, "n_days": nsum.get("n_days"),
                         "n_meals": nsum.get("n_meals"), "partial": bool(nsum.get("partial")),
                         "meals": nsum.get("meals") or [], "days": nsum.get("days") or [],
                         "fields": [{"key": k, **fld[k]} for k in keys if k in fld],
                         "targets": nutri.compare_targets(nsum.get("avg_day"), gender)}
    return {"resident": {"elderly_id": r["id"], "display_name": _display_name(r)},
            "type_info": type_info, "assessments": hist, "solutions": sols, "guardians": gs,
            "notifications": notes, "actions": acts, "nutrition": nutrition}


# ─────────────────────── 설문 데이터 점검 ───────────────────────
# 리포트에서 '–' 또는 '미실시'로 보이는 항목이 (1) 설문에 값이 없어서인지
# (2) 평가가 오래되어서인지 구분하기 위한 진단용 조회
BASIC_CHECK = [("age", "출생연도"), ("gender", "성별"), ("care_grade", "장기요양등급"), ("education", "학력"),
               ("height", "키"), ("weight", "체중"), ("systolic_bp", "수축기 혈압"), ("diastolic_bp", "이완기 혈압"),
               ("diseases", "진단 질환"), ("sitting_time", "좌식시간"), ("chewing_difficulty", "저작곤란"),
               ("swallowing_difficulty", "연하곤란"), ("meal_type", "식사형태"), ("eating_independence", "식사 자립도")]
NUTRITION_CHECK = [("meal_portions", "배식량 기록"), ("plate_waste", "잔반 기록")]
SAT_CHECK = [("overall_satisfaction", "전반 만족도"), ("portion_adequacy", "배식량 적정성"), ("food_quality", "음식 품질")]


def _empty(v):
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() in ("", "[]", "{}", "null")
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _check_row(row, fields):
    if not row:
        return {"exists": False, "updated_at": None, "missing": [l for _, l in fields], "groups": []}
    return {"exists": True, "updated_at": row.get("updated_at"),
            "missing": [l for f, l in fields if _empty(row.get(f))], "groups": []}


@router.get("/residents/{eid}/survey-check")
def survey_check(eid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    b, n, s = fetch_surveys(sb, home, [eid])
    b = b[0] if b else None
    out = {"basic": _check_row(b, BASIC_CHECK),
           "nutrition": _check_row(n[0] if n else None, NUTRITION_CHECK),
           "satisfaction": _check_row(s[0] if s else None, SAT_CHECK)}
    if b:
        groups = [("인지 기능 (K-MMSE-2)", engine.bc.MMSE_ITEMS),
                  ("우울 (GDS-SF)", [f"gds_{i}" for i in range(1, 16)]),
                  ("일상생활 수행 (K-MBI)", list(engine.bc.KMBI_SCORES)),
                  ("영양 (MNA-SF)", ["mna_bmi_category", "mna_appetite_change", "mna_weight_change",
                                    "mna_mobility", "mna_stress_illness", "mna_neuropsychological_problem"])]
        out["basic"]["groups"] = [{"name": nm, "filled": sum(0 if _empty(b.get(k)) else 1 for k in ks),
                                   "total": len(ks)} for nm, ks in groups]
    prev = sb.table("care_assessments").select("created_at,model_version,features").eq("elderly_id", eid) \
             .order("created_at", desc=True).limit(1).execute().data
    if prev:
        out["assessment"] = {"created_at": prev[0]["created_at"], "model_version": prev[0]["model_version"],
                             "stale": engine.features_stale(prev[0].get("features"))}
    else:
        out["assessment"] = None
    return out

# ─────────────────────────── 솔루션 ───────────────────────────

class SolutionRequest(BaseModel):
    provider: Optional[str] = None  # openai | anthropic | rules (미지정 시 LLM_PROVIDER)


@router.post("/residents/{eid}/solutions")
def create_solution(eid: str, req: SolutionRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    a = _one(sb.table("care_assessments").select("*").eq("elderly_id", eid).order("created_at", desc=True).limit(1).execute(),
             "먼저 유형·우선순위 평가를 실행하세요.")
    try:
        tinfo = engine.load_model(a["model_version"]).type_info(a["type_code"])
    except Exception:
        tinfo = {"code": a["type_code"], "name": a["type_name"], "guardian_label": a["type_name"], "description": ""}
    pr = {"score": a["priority_score"], "level": a["priority_level"], "factors": a["priority_factors"]}
    content, gen, flags, cands = sol.generate(a["features"], tinfo, pr, a.get("transition") or {},
                                              a["is_borderline"], req.provider)
    rec = jsonable({"assessment_id": a["id"], "elderly_id": eid, "nursing_home_id": home, "generator": gen,
                    "content": {**{k: v for k, v in content.items() if k != "guardian_message"},
                                "candidate_rules": [c["id"] for c in cands]},
                    "guardian_message": content["guardian_message"], "guardrail_flags": flags,
                    "status": "draft", "edited_by": user["actor"]})
    out = sb.table("care_solutions").insert(rec).execute()
    return out.data[0] if out.data else rec


class SolutionEdit(BaseModel):
    content: Optional[dict] = None
    guardian_message: Optional[str] = None


def _solution(sb, home, sid):
    return _one(sb.table("care_solutions").select("*").eq("id", sid).eq("nursing_home_id", home).execute(),
                "솔루션을 찾을 수 없습니다.")


@router.put("/solutions/{sid}")
def edit_solution(sid: str, req: SolutionEdit, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    s = _solution(sb, home, sid)
    upd = {"edited_by": user["actor"], "updated_at": get_kst_now(), "status": "draft",
           "approved_by": None, "approved_at": None}  # 수정 시 재승인 필요
    warnings = []
    if req.content is not None:
        upd["content"] = {**s["content"], **req.content}
    if req.guardian_message is not None:
        g = req.guardian_message.strip()
        warnings = sol._scan(g) + (["전문용어·코드 포함"] if sol.JARGON.search(g) else [])
        upd["guardian_message"] = g
    sb.table("care_solutions").update(jsonable(upd)).eq("id", sid).execute()
    return {"success": True, "warnings": warnings}


@router.post("/solutions/{sid}/approve")
def approve_solution(sid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    s = _solution(sb, home, sid)
    if s["status"] not in ("draft", "rejected"):
        raise HTTPException(status_code=400, detail=f"현재 상태({s['status']})에서는 승인할 수 없습니다.")
    sb.table("care_solutions").update({"status": "approved", "approved_by": user["actor"],
                                       "approved_at": get_kst_now()}).eq("id", sid).execute()
    return {"success": True}


@router.post("/solutions/{sid}/reject")
def reject_solution(sid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _solution(sb, home, sid)
    sb.table("care_solutions").update({"status": "rejected", "updated_at": get_kst_now()}).eq("id", sid).execute()
    return {"success": True}


# ─────────────────────────── 보호자 알림 ───────────────────────────

class SendRequest(BaseModel):
    guardian_ids: Optional[list[str]] = None


def _focus(content):
    cats = []
    for a in content.get("staff_actions", []):
        c = a.get("category")
        if c and c not in cats and c not in ("재평가",):
            cats.append(c)
    return ", ".join(cats[:3]) or "정기 관리"


@router.post("/solutions/{sid}/send")
def send_solution(sid: str, req: SendRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    s = _solution(sb, home, sid)
    if s["status"] not in ("approved", "sent"):
        raise HTTPException(status_code=400, detail="담당자 승인 후에만 보호자에게 보낼 수 있습니다.")
    r = _resident(sb, home, s["elderly_id"])
    a = _one(sb.table("care_assessments").select("*").eq("id", s["assessment_id"]).execute())
    q = sb.table("guardians").select("*").eq("elderly_id", s["elderly_id"]).eq("is_active", True)
    guardians = q.execute().data
    if req.guardian_ids:
        guardians = [g for g in guardians if g["id"] in req.guardian_ids]
    consented = [g for g in guardians if g.get("consent_health_info")]
    if not consented:
        raise HTTPException(status_code=400, detail="건강정보 수신에 동의한 보호자가 없습니다.")
    nh = sb.table("nursing_homes").select("name").eq("id", home).execute()
    try:
        tinfo = engine.load_model(a["model_version"]).type_info(a["type_code"])
    except Exception:
        tinfo = {"guardian_label": a["type_name"]}
    try:
        sender, mode = notify.get_sender()
    except Exception as e:  # 실발송 모드인데 키 설정이 빠진 경우 등
        raise HTTPException(status_code=500, detail=f"알림 발송 설정 오류: {e}")
    results = []
    for g in consented:
        token, expires, link = notify.new_report_token()
        variables = {"시설명": nh.data[0]["name"] if nh.data else home, "어르신": _display_name(r),
                     "보호자": g["name"], "평가일": a["created_at"][:10],
                     "관리구분": tinfo.get("guardian_label") or a["type_name"],
                     "돌봄중점": _focus(s["content"]), "만료일": expires.strftime("%Y-%m-%d"), "토큰": token}
        text, extra = notify.render("CARE_REPORT_V1", variables)
        variables = {**variables, "링크": link}
        try:
            resp = sender.send(g["phone"], "CARE_REPORT_V1", text, extra)
            status = resp["status"]
        except Exception as e:
            resp, status = {"error": str(e)}, "failed"
        if mode == "sms":  # 미리보기·기록도 실제 문자 본문으로
            text = notify.SolapiSmsSender.sms_text(text, extra)
        rec = {"solution_id": sid, "guardian_id": g["id"], "elderly_id": s["elderly_id"], "nursing_home_id": home,
               "channel": "sms" if mode == "sms" else "kakao_alimtalk", "mode": mode, "provider": sender.name, "template_code": "CARE_REPORT_V1", "variables": variables,
               "rendered_text": text, "report_token": token, "report_expires_at": expires.isoformat(),
               "status": status, "provider_response": resp, "sent_by": user["actor"]}
        sb.table("care_notifications").insert(jsonable(rec)).execute()
        results.append({"guardian": g["name"], "phone": notify.mask_phone(g["phone"]), "status": status,
                        "mode": mode, "text": text, "button": extra["button"], "report_url": link,
                        "error": (resp.get("response") or {}).get("reason") or resp.get("error")})
    if any(x["status"] == "sent" for x in results):
        sb.table("care_solutions").update({"status": "sent", "updated_at": get_kst_now()}).eq("id", sid).execute()
    skipped = [g["name"] for g in guardians if not g.get("consent_health_info")]
    return {"mode": mode, "results": results, "skipped_no_consent": skipped}


# ─────────────────────────── 보호자 관리 ───────────────────────────

class GuardianIn(BaseModel):
    name: str
    relation: Optional[str] = None
    phone: str
    consent_health_info: bool = False


@router.post("/residents/{eid}/guardians")
def add_guardian(eid: str, req: GuardianIn, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    try:
        phone = notify.normalize_phone(req.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    rec = {"elderly_id": eid, "nursing_home_id": home, "name": req.name, "relation": req.relation,
           "phone": phone, "consent_health_info": req.consent_health_info, "is_active": True,
           "consent_at": datetime.now(timezone.utc).isoformat() if req.consent_health_info else None}
    out = sb.table("guardians").insert(rec).execute()
    return out.data[0] if out.data else rec


@router.put("/guardians/{gid}")
def update_guardian(gid: str, req: GuardianIn, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    g = _one(sb.table("guardians").select("*").eq("id", gid).eq("nursing_home_id", home).execute())
    try:
        phone = notify.normalize_phone(req.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    upd = {"name": req.name, "relation": req.relation, "phone": phone,
           "consent_health_info": req.consent_health_info}
    if req.consent_health_info and not g.get("consent_health_info"):
        upd["consent_at"] = datetime.now(timezone.utc).isoformat()
    if not req.consent_health_info:
        upd["consent_at"] = None
    sb.table("guardians").update(upd).eq("id", gid).execute()
    return {"success": True}


@router.delete("/guardians/{gid}")
def remove_guardian(gid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _one(sb.table("guardians").select("id").eq("id", gid).eq("nursing_home_id", home).execute())
    sb.table("guardians").update({"is_active": False}).eq("id", gid).execute()
    return {"success": True}


# ─────────────────────────── 돌봄 수행 기록 ───────────────────────────

class ActionIn(BaseModel):
    action: str
    status: str = "done"
    outcome_note: Optional[str] = None
    solution_id: Optional[str] = None


@router.post("/residents/{eid}/actions")
def add_action(eid: str, req: ActionIn, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _resident(sb, home, eid)
    rec = {"elderly_id": eid, "nursing_home_id": home, "solution_id": req.solution_id, "action": req.action,
           "status": req.status, "outcome_note": req.outcome_note, "recorded_by": user["actor"]}
    out = sb.table("care_actions").insert(rec).execute()
    return out.data[0] if out.data else rec
