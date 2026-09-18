# -*- coding: utf-8 -*-
"""
어르신 건강·식사 리포트 구성
  - audience="guardian": 보호자용 (점수·척도명 대신 쉬운 단계 표현, 우선순위 점수 비공개)
  - audience="staff":    담당자용 (척도 점수·우선순위 요인·시설 평균 비교까지)
두 화면이 같은 구조를 쓰도록 서버에서 한 번에 만들어 준다.
"""
from __future__ import annotations

import copy
import time
from statistics import mean

from .data import fetch_all
from . import nutrition as nutri

GENDER = {1.0: "여성", 0.0: "남성"}
CARE_GRADE = {1: "1등급", 2: "2등급", 3: "3등급", 4: "4등급 이상"}
EDU = {0: "무학", 1: "초등학교 졸업", 2: "중학교 졸업", 3: "고등학교 졸업", 4: "대학 졸업 이상"}
TEXTURE = ["일반식", "다진식", "갈은식(믹서식)", "유동식"]
EATING = ["스스로 드심", "부분 도움 필요", "전적인 도움 필요"]

# 단계 구분: (기준함수, 단계, 톤) — 톤: good | warn | bad
BANDS = {
    "nutrition": lambda v: ("영양불량", "bad") if v <= 7 else (("영양불량 위험", "warn") if v <= 11 else ("양호", "good")),
    "cognition": lambda v: ("중등도 이상 저하", "bad") if v < 18 else (("경도 저하", "warn") if v < 24 else ("정상 범위", "good")),
    "adl": lambda v: ("많은 도움 필요", "bad") if v < 50 else (("부분 도움 필요", "warn") if v < 80 else ("대부분 자립", "good")),
    "mood": lambda v: ("우울감 높음", "bad") if v >= 8 else (("주의", "warn") if v >= 5 else ("양호", "good")),
    "activity": lambda v: ("거의 없음", "bad") if v < 1 else (("부족", "warn") if v < 600 else ("충분", "good")),
    "intake": lambda v: ("낮음", "bad") if v < 50 else (("주의", "warn") if v < 75 else ("양호", "good")),
    "bmi": lambda v: ("저체중", "bad") if v < 18.5 else (("정상", "good") if v < 25 else ("과체중", "warn")),
    "satisfaction": lambda v: ("낮음", "bad") if v <= 2.5 else (("보통", "warn") if v < 4 else ("높음", "good")),
}


def _n(f, k):
    v = (f or {}).get(k)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _band(kind, v):
    if v is None:
        return {"label": "미실시", "tone": "none"}
    label, tone = BANDS[kind](v)
    return {"label": label, "tone": tone}


def _round(v, d=0):
    if v is None:
        return None
    return round(v, d) if d else round(v)


# 시설 전체 최신 평가 캐시 — 같은 시설 리포트를 연달아 열 때 매번 다시 읽지 않는다.
_PEER_CACHE: dict[str, tuple[float, dict]] = {}
_PEER_TTL = 60.0


def _facility_latest(sb, home: str) -> dict:
    hit = _PEER_CACHE.get(home)
    now = time.time()
    if hit and now - hit[0] < _PEER_TTL:
        return hit[1]
    latest = {}
    for row in fetch_all(sb, "care_assessments",
                         "elderly_id,type_code,type_name,features,model_version,created_at",
                         eq={"nursing_home_id": home}, order="created_at", desc=True):
        latest.setdefault(row["elderly_id"], row)
    _PEER_CACHE[home] = (now, latest)
    return latest



def build_report(sb, home: str, eid: str, audience: str = "guardian",
                 assessment: dict | None = None, solution: dict | None = None,
                 facility_name: str | None = None, type_info: dict | None = None,
                 guardian_name: str | None = None, type_meta: dict | None = None) -> dict:
    staff = audience == "staff"
    a = assessment or {}
    f = a.get("features") or {}
    prev = None
    hist = (sb.table("care_assessments").select("id,elderly_id,created_at,features,type_code")
            .eq("elderly_id", eid).order("created_at", desc=True).limit(8).execute().data or [])
    if len(hist) > 1:
        prev = hist[1].get("features") or {}

    res = sb.table("elderly_residents").select("*").eq("id", eid).execute().data
    res = res[0] if res else {"id": eid}
    if not facility_name:
        nh = sb.table("nursing_homes").select("name").eq("id", home).execute().data
        facility_name = nh[0]["name"] if nh else home

    # ── 시설 내 유형 분포 · 평균 (같은 모델 버전의 최신 평가 기준) ──
    peers = [r for r in _facility_latest(sb, home).values() if r.get("model_version") == a.get("model_version")]
    dist = {}
    for r in peers:
        d = dist.setdefault(r["type_code"], {"code": r["type_code"], "name": r.get("type_name"), "count": 0})
        d["count"] += 1
    distribution = sorted(dist.values(), key=lambda x: x["code"])
    for d in distribution:
        d["is_self"] = d["code"] == a.get("type_code")
        if not staff:  # 보호자 화면은 쉬운 표현(관리 구분)으로
            d["name"] = ((type_meta or {}).get(d["code"], {}) or {}).get("guardian_label") or d["name"]

    def peer_avg(key):
        vals = [v for v in ((r.get("features") or {}).get(key) for r in peers) if isinstance(v, (int, float))]
        return mean(vals) if vals else None

    # ── 기본 정보 ──
    resident = {
        "elderly_id": eid,
        "display_name": res.get("name") or res.get("elderly_name") or eid,
        "age": _round(_n(f, "age")),
        "gender": GENDER.get(_n(f, "female")),
        "care_grade": CARE_GRADE.get(int(_n(f, "care_grade"))) if _n(f, "care_grade") else None,
        "education": EDU.get(int(_n(f, "education_level"))) if _n(f, "education_level") is not None else None,
        "meal_form": f.get("meal_form") or (TEXTURE[int(_n(f, "texture_level"))] if _n(f, "texture_level") is not None else None),
        "chewing": _n(f, "chewing_difficulty") == 1,
        "swallowing": _n(f, "swallowing_difficulty") == 1,
        "eating": EATING[int(_n(f, "eating_dependence"))] if _n(f, "eating_dependence") is not None else None,
        "diseases": f.get("diseases") or [],
        "medications": f.get("medications") or [],
    }

    # ── 상태 단계 (보호자·담당자 공통, 점수는 담당자만) ──
    def status(key, kind, label, value, scale=None, note=None):
        b = _band(kind, value)
        item = {"key": key, "title": label, "band": b["label"], "tone": b["tone"], "note": note}
        if staff and value is not None:
            item["value"] = _round(value, 1)
            item["scale"] = scale
        return item

    statuses = [
        status("nutrition", "nutrition", "영양 상태", _n(f, "mna_sf"), "MNA-SF 0–14"),
        status("intake", "intake", "식사 섭취", _n(f, "intake_total"), "5일 평균 섭취율 %"),
        status("adl", "adl", "일상생활 수행", _n(f, "kmbi_pct"), "K-MBI %"),
        status("cognition", "cognition", "인지 기능", _n(f, "mmse"), "K-MMSE-2 0–30"),
        status("mood", "mood", "기분·정서", _n(f, "gds"), "GDS-SF 0–15"),
        status("activity", "activity", "신체 활동", _n(f, "met_total"), "IPAQ MET-분/주"),
    ]

    # ── 신체 계측 ──
    w, pw = _n(f, "weight_kg"), _n(prev, "weight_kg")
    anthro = {
        "height": _round(_n(f, "height_cm"), 1), "weight": _round(w, 1), "bmi": _round(_n(f, "bmi"), 1),
        "bmi_band": _band("bmi", _n(f, "bmi")),
        "weight_change": _round(w - pw, 1) if (w and pw) else None,
        "sbp": _round(_n(f, "sbp")), "dbp": _round(_n(f, "dbp")),
    }

    # ── 섭취 ──
    meals = [("아침", "intake_breakfast"), ("점심", "intake_lunch"), ("저녁", "intake_dinner"), ("간식", "intake_snack")]
    comps = [("밥·죽", "intake_rice"), ("국·탕", "intake_soup"), ("주찬", "intake_main"), ("부찬", "intake_side"), ("김치", "intake_kimchi")]
    intake = {
        "total": _round(_n(f, "intake_total")),
        "band": _band("intake", _n(f, "intake_total")),
        "days": _round(_n(f, "n_days")),
        "meals": [{"label": l, "value": _round(_n(f, k))} for l, k in meals],
        "components": [{"label": l, "value": _round(_n(f, k))} for l, k in comps],
        "prev_total": _round(_n(prev, "intake_total")),
        "has_nutrition": _n(f, "has_nutrition") == 1,
        "log": [],
    }

    # ── 식사 기록 + 섭취 영양소 ──
    # 예전 평가에는 메뉴명·영양소가 없으므로, 없으면 여기서 즉시 계산해 채운다.
    meal_log = copy.deepcopy(f.get("meal_log") or [])
    nsum = f.get("nutrition") if isinstance(f.get("nutrition"), dict) else None
    if meal_log and (nsum is None or not any(it.get("name") for c in meal_log for it in (c.get("items") or []))):
        try:
            meal_log, live = nutri.enrich_meal_log(meal_log, res.get("meal_form"), eid)
            nsum = nsum or live
        except Exception:
            pass
    intake["log"] = meal_log
    low_meals = [m["label"] for m in intake["meals"] if m["value"] is not None and m["value"] < 70]
    intake["low_meals"] = low_meals

    # ── 섭취 영양소 (식단표 × 배식량 × 목측법) ──
    nutrition_out = None
    if nsum:
        gender = resident.get("gender")
        fld = nutri.fields()
        keys = ["energy", "protein", "fat", "carb", "fiber", "na", "ca", "fe", "k", "vc", "vd", "b12"]
        if not staff:
            keys = ["energy", "protein", "fiber", "ca", "na"]
        nutrition_out = {
            "fields": [{"key": k, **fld[k]} for k in keys if k in fld],
            "avg_day": nsum.get("avg_day") or {},
            "days": nsum.get("days") or [],
            "meals": nsum.get("meals") or [],
            "n_days": nsum.get("n_days"),
            "n_meals": nsum.get("n_meals"),
            "partial": bool(nsum.get("partial")),
            "targets": [t for t in nutri.compare_targets(nsum.get("avg_day"), gender)
                        if staff or t["key"] in keys],
        }

    # ── 급식 만족·선호 ──
    prefs = [l for l, k in (("생선·해산물", "pref_seafood"), ("고기류", "pref_meat"), ("과일", "pref_fruit"),
                            ("채소·나물", "pref_vegetable")) if _n(f, k) == 1]
    satisfaction = {
        "overall": _round(_n(f, "sat_overall"), 1), "portion": _round(_n(f, "sat_portion"), 1),
        "quality": _round(_n(f, "sat_quality"), 1), "band": _band("satisfaction", _n(f, "sat_overall")),
        "prefs": prefs, "comment": (f.get("improvement_text") or "").strip() or None,
    }

    # ── 시설 평균 대비 ──
    comparison = []
    rows = [("영양 상태 (MNA-SF)" if staff else "영양 상태", "mna_sf", "점", 0, 14),
            ("일상생활 수행 (K-MBI)" if staff else "일상생활 수행", "kmbi_pct", "%", 0, 100),
            ("전체 식사 섭취율", "intake_total", "%", 0, 100),
            ("급식 만족", "sat_overall", "점", 1, 5),
            ("체질량지수 (BMI)" if staff else "체질량지수", "bmi", "", 14, 32)]
    for label, key, unit, lo, hi in rows:
        self_v, avg = _n(f, key), peer_avg(key)
        if self_v is None:
            continue
        comparison.append({"label": label, "self": round(self_v, 1), "facility_avg": round(avg, 1) if avg else None,
                           "unit": unit, "min": lo, "max": hi})

    # ── 돌봄 제안 ──
    sol = solution or {}
    content = sol.get("content") or {}
    solution_out = {
        "guardian_message": sol.get("guardian_message"),
        "meal_guidance": content.get("meal_guidance") or [],
        "monitoring": content.get("monitoring") or [],
        "actions": [{"category": x.get("category"), "action": x.get("action"), "why": x.get("why")}
                    for x in (content.get("staff_actions") or [])],
        "status": sol.get("status"),
        "updated_at": sol.get("updated_at") or sol.get("created_at"),
    }
    if staff:
        solution_out["summary"] = content.get("summary")

    out = {
        "audience": audience,
        "facility": {"id": home, "name": facility_name},
        "guardian_name": guardian_name,
        "resident": resident,
        "assessed_on": (a.get("created_at") or "")[:10],
        "survey_start": (f.get("survey_start") or "")[:10] or None,
        "type": {**(type_info or {"code": a.get("type_code"), "name": a.get("type_name")}),
                 "distribution": distribution, "peer_total": len(peers)},
        "statuses": statuses,
        "anthropometry": anthro,
        "intake": intake,
        "nutrition": nutrition_out,
        "satisfaction": satisfaction,
        "comparison": comparison,
        "solution": solution_out,
        "model_version": a.get("model_version"),
    }
    if staff:
        out["priority"] = {"score": a.get("priority_score"), "level": a.get("priority_level"),
                           "factors": a.get("priority_factors") or []}
        out["transition"] = a.get("transition")
        out["is_borderline"] = a.get("is_borderline")
        out["history"] = [{"created_at": h["created_at"][:10], "type_code": h["type_code"],
                           "intake_total": _round((h.get("features") or {}).get("intake_total")),
                           "weight_kg": _round((h.get("features") or {}).get("weight_kg"), 1),
                           "mna_sf": _round((h.get("features") or {}).get("mna_sf"), 1)} for h in hist[:6]]
    return out
