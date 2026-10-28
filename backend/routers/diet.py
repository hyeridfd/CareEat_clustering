# -*- coding: utf-8 -*-
"""맞춤 식단 설계 API (솔루션 > 맞춤 식단 설계) — 요양원 담당자 전용

  실행        POST /runs            → 백그라운드에서 일반식 최적화 · 대체찬 · 배식량 계산 (수 분)
  조회        GET  /status · /runs/{id} · /runs/{id}/servings/{elderly_id}
  영양사 검토  POST /runs/{id}/approve · PUT /runs/{id}/menu (메뉴 교체 → 개인화·배식만 다시 계산)
  설정        GET/PUT /inventory · GET /preference · POST /preference/refresh · GET /residents · PUT /residents/{id}/settings
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from care.data import fetch_all
from dependencies import get_supabase, require_staff, get_kst_now

router = APIRouter()
STALE_MIN = 30          # 이 시간 넘게 '실행 중'이면 멈춘 것으로 보고 새 실행 허용


def _jsonable(x):
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


def _load_inputs(sb, home):
    residents = fetch_all(sb, "elderly_residents", eq={"nursing_home_id": home})
    rows = fetch_all(sb, "care_assessments", "elderly_id,features,created_at",
                     eq={"nursing_home_id": home}, order="created_at", desc=True)
    assess = {}
    for r in rows:
        assess.setdefault(r["elderly_id"], r)
    settings = {r["elderly_id"]: r for r in fetch_all(sb, "diet_resident_settings", eq={"nursing_home_id": home})}
    inv = sb.table("diet_inventory").select("*").eq("nursing_home_id", home).execute().data
    pref = sb.table("diet_preferences").select("*").eq("nursing_home_id", home).execute().data
    return residents, assess, settings, (inv[0] if inv else None), (pref[0] if pref else None)


def _load_ehr(sb, home):
    """어르신 기록 탭의 약·알레르기 → {elderly_id: {medications, allergies}} (약물·알레르기 에이전트 입력)"""
    out = {}
    try:
        for m in fetch_all(sb, "resident_medications", "elderly_id,name,dose,food_caution,is_active",
                           eq={"nursing_home_id": home}):
            if m.get("is_active") is not False:
                out.setdefault(m["elderly_id"], {}).setdefault("medications", []).append(m)
        for a in fetch_all(sb, "resident_allergies", "elderly_id,allergen,severity,reaction", eq={"nursing_home_id": home}):
            out.setdefault(a["elderly_id"], {}).setdefault("allergies", []).append(a)
    except Exception:
        traceback.print_exc()                         # 기록 탭 테이블이 없어도 식단 설계는 진행
    return out


def _save_result(sb, run_id, out):
    servings = out.pop("servings", {}) or {}
    menu, metrics = out.pop("menu"), out.pop("metrics")
    sb.table("diet_servings").delete().eq("run_id", run_id).execute()
    batch = []
    for eid, meals in servings.items():
        batch.append({"run_id": run_id, "elderly_id": eid, "meals": meals})
        if len(batch) >= 20:
            sb.table("diet_servings").insert(_jsonable(batch)).execute(); batch = []
    if batch:
        sb.table("diet_servings").insert(_jsonable(batch)).execute()
    sb.table("diet_runs").update(_jsonable({
        "status": "done", "progress": "완료", "menu": menu, "metrics": metrics, "result": out,
        "updated_at": get_kst_now()})).eq("id", run_id).execute()


CANCEL = set()                      # 멈추기 요청된 실행 id (같은 서버 프로세스)


class Cancelled(Exception):
    pass


def _check_cancel(sb, run_id, state):
    """멈추기 요청 확인 — 메모리 표시 우선, 10초마다 DB 상태도 확인(서버 재시작·다중 프로세스 대비)"""
    if run_id in CANCEL:
        raise Cancelled()
    now = time.time()
    if now - state["checked"] >= 10:
        state["checked"] = now
        try:
            st = sb.table("diet_runs").select("status").eq("id", run_id).execute().data
            if st and st[0]["status"] == "cancelled":
                raise Cancelled()
        except Cancelled:
            raise
        except Exception:
            pass


def _progress_writer(sb, run_id):
    last = [0.0]
    state = {"checked": time.time()}

    def say(msg):
        _check_cancel(sb, run_id, state)
        now = time.time()
        if now - last[0] >= 3:            # DB 쓰기는 3초에 한 번까지
            last[0] = now
            try:
                sb.table("diet_runs").update({"progress": msg, "updated_at": get_kst_now()}).eq("id", run_id).execute()
            except Exception:
                pass
    return say


def _job(run_id, home, preset, seed, menu=None):
    from diet import pipeline as P
    sb = get_supabase()
    try:
        _check_cancel(sb, run_id, {"checked": 0})
        sb.table("diet_runs").update({"status": "running", "progress": "데이터 불러오는 중",
                                      "updated_at": get_kst_now()}).eq("id", run_id).execute()
        residents, assess, settings, inv, pref = _load_inputs(sb, home)
        ehr = _load_ehr(sb, home)
        say = _progress_writer(sb, run_id)
        if menu is None:
            out = P.run_design(residents, assess, settings, inv, pref, preset=preset, seed=seed, progress=say, ehr=ehr)
        else:
            out = P.redo_personalization(menu, residents, assess, settings, inv, pref, progress=say, ehr=ehr)
        sb.table("diet_runs").update({"progress": "결과 저장 중", "updated_at": get_kst_now()}).eq("id", run_id).execute()
        _check_cancel(sb, run_id, {"checked": 0})
        _save_result(sb, run_id, out)
    except Cancelled:
        sb.table("diet_runs").update({"status": "cancelled", "progress": "중지됨",
                                      "updated_at": get_kst_now()}).eq("id", run_id).execute()
    except Exception as e:
        traceback.print_exc()
        sb.table("diet_runs").update({"status": "failed", "error": str(e)[:2000], "progress": "실패",
                                      "updated_at": get_kst_now()}).eq("id", run_id).execute()
    finally:
        CANCEL.discard(run_id)


def _busy(sb, home):
    rows = sb.table("diet_runs").select("id,status,updated_at").eq("nursing_home_id", home) \
        .in_("status", ["queued", "running"]).execute().data or []
    now = datetime.now(timezone.utc)
    for r in rows:
        try:
            upd = datetime.fromisoformat(str(r["updated_at"]).replace("Z", "+00:00"))
        except Exception:
            return r
        if now - upd < timedelta(minutes=STALE_MIN):
            return r
    return None


# ─────────────────────────── 실행 · 조회 ───────────────────────────

class RunRequest(BaseModel):
    preset: str = "standard"            # quick | standard | thorough
    seed: int = 42


@router.post("/runs")
def start_run(req: RunRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    if _busy(sb, home):
        raise HTTPException(status_code=409, detail="이미 식단 설계가 진행 중입니다. 끝난 뒤 다시 실행하세요.")
    inv = sb.table("diet_inventory").select("nursing_home_id,items,start_date").eq("nursing_home_id", home).execute().data
    pref = sb.table("diet_preferences").select("nursing_home_id,updated_at").eq("nursing_home_id", home).execute().data
    row = _one(sb.table("diet_runs").insert({
        "nursing_home_id": home, "status": "queued", "progress": "대기 중", "created_by": user["actor"],
        "params": {"preset": req.preset, "seed": req.seed,
                   "inventory_used": bool(inv and inv[0].get("items")), "preference_used": bool(pref),
                   "start_date": (inv[0].get("start_date") if inv else None),
                   "preference_updated_at": pref[0]["updated_at"] if pref else None}}).execute())
    threading.Thread(target=_job, args=(row["id"], home, req.preset, req.seed), daemon=True).start()
    return {"id": row["id"], "status": "queued"}


@router.get("/status")
def status(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    runs = sb.table("diet_runs").select("id,status,progress,params,created_at,updated_at,approved_at,approved_by,parent_run_id,error,start_date") \
        .eq("nursing_home_id", home).order("created_at", desc=True).limit(12).execute().data or []
    inv = sb.table("diet_inventory").select("items,start_date,updated_at").eq("nursing_home_id", home).execute().data
    pref = sb.table("diet_preferences").select("updated_at,report").eq("nursing_home_id", home).execute().data
    residents = fetch_all(sb, "elderly_residents", "id", eq={"nursing_home_id": home})
    assessed = {r["elderly_id"] for r in fetch_all(sb, "care_assessments", "elderly_id", eq={"nursing_home_id": home})}
    p = pref[0] if pref else None
    return {
        "runs": runs,
        "residents_total": len(residents), "residents_ready": len({r["id"] for r in residents} & assessed),
        "inventory": inv and {"count": len(inv[0].get("items") or []), "start_date": inv[0].get("start_date"),
                              "updated_at": inv[0].get("updated_at")},
        "preference": p and {"updated_at": p["updated_at"],
                             **{k: (p.get("report") or {}).get(k) for k in ("n_records", "n_menus_observed", "n_residents",
                                                                            "facility_mean", "period")}},
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    return _one(sb.table("diet_runs").select("*").eq("id", run_id).eq("nursing_home_id", home).execute(),
                "식단 설계 결과를 찾을 수 없습니다.")


@router.get("/runs/{run_id}/servings/{eid}")
def get_servings(run_id: str, eid: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    get_run(run_id, user)
    return _one(sb.table("diet_servings").select("*").eq("run_id", run_id).eq("elderly_id", eid).execute(),
                "이 어르신의 배식표가 없습니다.")


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, user: dict = Depends(require_staff)):
    """계산 중인 식단 설계 멈추기 — 진행 중인 단계가 끝나는 대로(보통 수 초~십여 초) 중지"""
    sb = get_supabase()
    run = get_run(run_id, user)
    if run["status"] not in ("queued", "running"):
        raise HTTPException(status_code=400, detail="계산 중인 설계만 멈출 수 있습니다.")
    CANCEL.add(run_id)
    sb.table("diet_runs").update({"status": "cancelled", "progress": "중지 요청됨",
                                  "updated_at": get_kst_now()}).eq("id", run_id).execute()
    return {"ok": True}


class ApproveRequest(BaseModel):
    start_date: Optional[str] = None        # 식단 1일차 날짜 (재고 추적 예상 사용량 기준)
    auto_receive: bool = True               # 주간 발주 구매량을 주차별 입고로 자동 기록


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, req: Optional[ApproveRequest] = None, user: dict = Depends(require_staff)):
    sb = get_supabase()
    run = get_run(run_id, user)
    if run["status"] not in ("done", "approved"):
        raise HTTPException(status_code=400, detail="완료된 설계만 승인할 수 있습니다.")
    start = (req.start_date if req else None) or (run.get("params") or {}).get("start_date")
    if start:
        try:
            start = datetime.fromisoformat(str(start)[:10]).date().isoformat()
        except ValueError:
            raise HTTPException(status_code=400, detail="식단 시작일 형식이 올바르지 않습니다 (YYYY-MM-DD).")
    sb.table("diet_runs").update({"status": "approved", "approved_by": user["actor"], "approved_at": get_kst_now(),
                                  "start_date": start, "updated_at": get_kst_now()}).eq("id", run_id).execute()
    n = 0
    if start and (req is None or req.auto_receive):
        n = _receive_plan(sb, user, {**run, "start_date": start})
    return {"ok": True, "start_date": start, "received": n}


def _receive_plan(sb, user, run) -> int:
    """승인 식단의 주간 발주량을 입고로 기록. 이 식단 시작일 이후의 이전 자동입고는 지우고 새로 넣는다."""
    from diet.stock import receive_plan_events, AUTO_NOTE
    home = user["scope_home"]
    start = datetime.fromisoformat(str(run["start_date"])[:10]).date()
    full = run if (run.get("result") or {}).get("purchase") else get_run(run["id"], user)
    rows = receive_plan_events(full, start)
    if not rows:
        return 0
    old = sb.table("diet_stock_events").select("id,event_date,note").eq("nursing_home_id", home) \
        .eq("kind", "입고").execute().data or []
    first = min(r["event_date"] for r in rows)
    for o in old:
        if str(o.get("note") or "").startswith(AUTO_NOTE) and str(o["event_date"]) >= first:
            sb.table("diet_stock_events").delete().eq("id", o["id"]).execute()
    for i in range(0, len(rows), 200):
        sb.table("diet_stock_events").insert([{**r, "nursing_home_id": home, "created_by": user["actor"]}
                                              for r in rows[i:i + 200]]).execute()
    return len(rows)


@router.post("/runs/{run_id}/receive-plan")
def receive_plan(run_id: str, user: dict = Depends(require_staff)):
    """이미 승인한 식단의 주간 발주량을 입고로 (다시) 기록"""
    sb = get_supabase()
    run = get_run(run_id, user)
    if run["status"] != "approved" or not run.get("start_date"):
        raise HTTPException(status_code=400, detail="시작일을 정해 승인한 식단만 입고로 반영할 수 있습니다.")
    if not (run.get("result") or {}).get("purchase"):
        raise HTTPException(status_code=400, detail="이 식단에는 주간 발주 계산이 없습니다. 식단 설계를 다시 실행해 승인하세요.")
    return {"ok": True, "received": _receive_plan(sb, user, run)}


class MenuChange(BaseModel):
    일차: str
    끼니: str
    칸: str           # 밥 · 국 · 주찬 · 부찬1 · 부찬2 · 김치
    메뉴: str


class MenuEditRequest(BaseModel):
    changes: list[MenuChange]


@router.put("/runs/{run_id}/menu")
def edit_menu(run_id: str, req: MenuEditRequest, user: dict = Depends(require_staff)):
    """영양사가 메뉴를 바꾸면 새 설계(수정본)를 만들고 지표·대체찬·배식만 다시 계산한다."""
    from diet.pipeline import menu_options
    sb, home = get_supabase(), user["scope_home"]
    run = get_run(run_id, user)
    if not run.get("menu"):
        raise HTTPException(status_code=400, detail="식단표가 없는 설계입니다.")
    if _busy(sb, home):
        raise HTTPException(status_code=409, detail="다른 식단 설계가 진행 중입니다.")
    opts = menu_options()
    cat = {"밥": "밥", "국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "김치": "김치"}
    menu = [dict(r) for r in run["menu"]]
    idx = {(r["일차"], r["끼니"]): r for r in menu}
    for c in req.changes:
        if c.칸 not in cat or c.메뉴 not in opts.get(cat[c.칸], []):
            raise HTTPException(status_code=400, detail=f"후보 메뉴가 아닙니다: {c.칸} {c.메뉴}")
        r = idx.get((c.일차, c.끼니))
        if not r:
            raise HTTPException(status_code=400, detail=f"식단표에 없는 끼니입니다: {c.일차} {c.끼니}")
        r[c.칸] = c.메뉴
    new = _one(sb.table("diet_runs").insert({
        "nursing_home_id": home, "status": "queued", "progress": "수정본 계산 대기", "created_by": user["actor"],
        "parent_run_id": run_id, "params": {**(run.get("params") or {}), "edited": [c.model_dump() for c in req.changes]},
    }).execute())
    threading.Thread(target=_job, args=(new["id"], home, None, None, menu), daemon=True).start()
    return {"id": new["id"], "status": "queued"}


@router.get("/menu-options")
def get_menu_options(user: dict = Depends(require_staff)):
    from diet.pipeline import menu_options
    return menu_options()


# ─────────────────────────── 재고 ───────────────────────────

class InventoryRequest(BaseModel):
    items: list[dict]
    start_date: Optional[str] = None


@router.get("/inventory")
def get_inventory(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    rows = sb.table("diet_inventory").select("*").eq("nursing_home_id", home).execute().data
    return rows[0] if rows else {"nursing_home_id": home, "items": [], "start_date": None}


@router.put("/inventory")
def put_inventory(req: InventoryRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    items = []
    for x in req.items:
        name = str(x.get("식재료명") or "").strip()
        try:
            g = float(x.get("재고량(g)") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"재고량은 숫자로 입력하세요: {name}")
        if name and g > 0:
            items.append({"식재료명": name, "재고량(g)": g, "유통기한": x.get("유통기한") or None, "비고": x.get("비고") or ""})
    sb.table("diet_inventory").upsert({"nursing_home_id": home, "items": items, "start_date": req.start_date,
                                       "updated_by": user["actor"], "updated_at": get_kst_now()}).execute()
    return {"ok": True, "count": len(items)}


# ─────────────────────────── 시설 선호도 ───────────────────────────

@router.get("/preference")
def get_preference(user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    rows = sb.table("diet_preferences").select("updated_at,report,updated_by").eq("nursing_home_id", home).execute().data
    return rows[0] if rows else None


@router.post("/preference/refresh")
def refresh_preference(user: dict = Depends(require_staff)):
    """평가 기록의 끼니별 잔반(목측 → 섭취율)으로 시설 선호 점수를 다시 계산"""
    from diet.pipeline import refresh_preference as refresh
    sb, home = get_supabase(), user["scope_home"]
    residents, assess, _, _, _ = _load_inputs(sb, home)
    try:
        res = refresh(assess, residents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sb.table("diet_preferences").upsert(_jsonable({
        "nursing_home_id": home, "pool_scores": res["pool_scores"], "product_scores": res["product_scores"],
        "report": res["report"], "updated_by": user["actor"], "updated_at": get_kst_now()})).execute()
    return {"ok": True, "report": res["report"]}


# ─────────────────────────── 어르신 식단 설정 ───────────────────────────

@router.get("/residents")
def residents(user: dict = Depends(require_staff)):
    from diet.pipeline import build_profiles
    sb, home = get_supabase(), user["scope_home"]
    res, assess, settings, _, _ = _load_inputs(sb, home)
    _, meta, skipped = build_profiles(res, assess, settings)
    rows = [{"elderly_id": k, **v, "note": (settings.get(k) or {}).get("note")} for k, v in meta.items()]
    rows.sort(key=lambda x: x["display_name"])
    return {"residents": _jsonable(rows), "skipped": skipped}


class SettingsRequest(BaseModel):
    no_spicy: bool = False
    note: Optional[str] = None


@router.put("/residents/{eid}/settings")
def put_settings(eid: str, req: SettingsRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _one(sb.table("elderly_residents").select("id").eq("id", eid).eq("nursing_home_id", home).execute(),
         "해당 요양원의 어르신이 아닙니다.")
    sb.table("diet_resident_settings").upsert({"elderly_id": eid, "nursing_home_id": home, "no_spicy": req.no_spicy,
                                               "note": req.note, "updated_at": get_kst_now()}).execute()
    return {"ok": True}


# ─────────────────────────── 재고 추적 (입고 · 실사 · 폐기 + 승인 식단 예상 사용) ───────────────────────────

STOCK_KINDS = ("입고", "실사", "폐기")


def _kst_today():
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date()


def _stock_inputs(sb, home):
    events = fetch_all(sb, "diet_stock_events", eq={"nursing_home_id": home}, order="event_date")
    runs = sb.table("diet_runs").select("id,start_date,approved_at,menu,result").eq("nursing_home_id", home) \
        .eq("status", "approved").execute().data or []
    runs = [r for r in runs if r.get("start_date")]
    for r in runs:                                   # 재고 계산엔 일별 사용량만 필요
        r["result"] = {"daily_usage": (r.get("result") or {}).get("daily_usage") or {}}
    return events, runs


def _date_arg(date):
    if not date:
        return _kst_today()
    try:
        return datetime.fromisoformat(str(date)[:10]).date()
    except ValueError:
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).")


@router.get("/stock/report")
def stock_report(date: Optional[str] = None, user: dict = Depends(require_staff)):
    """매일 아침 재고 리포트 — 추정 재고 · 오늘/7일 사용 예정 · 유통기한 임박 · 부족 예상 · 실사 필요"""
    from diet.stock import report
    sb, home = get_supabase(), user["scope_home"]
    events, runs = _stock_inputs(sb, home)
    return _jsonable(report(events, runs, _date_arg(date)))


@router.get("/stock/snapshot")
def stock_snapshot(date: Optional[str] = None, user: dict = Depends(require_staff)):
    """해당 날짜 아침 추정 재고 → 식단 설계용 재고 표로 불러오기"""
    from diet.stock import snapshot
    sb, home = get_supabase(), user["scope_home"]
    events, runs = _stock_inputs(sb, home)
    day = _date_arg(date)
    return {"date": day.isoformat(), "items": snapshot(events, runs, day)}


@router.get("/stock/events")
def stock_events(limit: int = 200, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    return sb.table("diet_stock_events").select("*").eq("nursing_home_id", home) \
        .order("event_date", desc=True).order("created_at", desc=True).limit(min(limit, 1000)).execute().data or []


class StockEventItem(BaseModel):
    식재료명: str
    수량: float                       # g
    유통기한: Optional[str] = None
    비고: Optional[str] = None


class StockEventRequest(BaseModel):
    date: Optional[str] = None
    kind: str                         # 입고 · 실사 · 폐기
    items: list[StockEventItem]
    auto_expiry: bool = True          # 입고·실사에서 유통기한을 비우면 식재료 종류별 추정값으로 채움


@router.post("/stock/events")
def add_stock_events(req: StockEventRequest, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    if req.kind not in STOCK_KINDS:
        raise HTTPException(status_code=400, detail="종류는 입고 · 실사 · 폐기 중 하나입니다.")
    from diet.shelf_life import estimate_expiry
    day_d = _date_arg(req.date)
    day = day_d.isoformat()
    rows = []
    for x in req.items:
        nm = x.식재료명.strip()
        if not nm or x.수량 < 0 or (req.kind != "실사" and x.수량 == 0):
            continue
        ex = None
        if x.유통기한:
            try:
                ex = datetime.fromisoformat(str(x.유통기한)[:10]).date().isoformat()
            except ValueError:
                raise HTTPException(status_code=400, detail=f"유통기한 형식이 올바르지 않습니다: {nm}")
        note = x.비고 or None
        if not ex and req.auto_expiry and req.kind in ("입고", "실사") and x.수량 > 0:
            e, why = estimate_expiry(nm, day_d)
            ex, note = e.isoformat(), " · ".join(t for t in (note, why) if t)
        rows.append({"nursing_home_id": home, "event_date": day, "kind": req.kind, "ingredient": nm,
                     "qty_g": round(float(x.수량), 1), "expiry": ex, "note": note, "created_by": user["actor"]})
    if not rows:
        raise HTTPException(status_code=400, detail="저장할 식재료가 없습니다.")
    sb.table("diet_stock_events").insert(rows).execute()
    return {"ok": True, "count": len(rows)}


@router.delete("/stock/events/{event_id}")
def delete_stock_event(event_id: str, user: dict = Depends(require_staff)):
    sb, home = get_supabase(), user["scope_home"]
    _one(sb.table("diet_stock_events").select("id").eq("id", event_id).eq("nursing_home_id", home).execute(),
         "기록을 찾을 수 없습니다.")
    sb.table("diet_stock_events").delete().eq("id", event_id).eq("nursing_home_id", home).execute()
    return {"ok": True}
