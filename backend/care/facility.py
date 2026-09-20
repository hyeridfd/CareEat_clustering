# -*- coding: utf-8 -*-
"""
Care-Eat Scan — 시설 영양 프로파일

  개인 평가(care_assessments.features)를 시설 단위 지표로 집계한다.
  개인 리포트가 "이 어르신은 어떤가"라면, 여기는 "우리 시설은 어떤가"다.

  산출물
    risks     위험군 비율 (영양위험·저체중·저작연하·저섭취 …)  ← Insight 의 입력
    nutrients 영양소별 기준 미달자 비율
    diseases  질환 prevalence
    texture   식형태 수요 분포
    intake    끼니별·일자별·음식군별 평균 섭취율
    menus     메뉴(일자×끼니×음식군) 단위 섭취율 랭킹 ← 식단 개편 후보
    groups    식형태군·유형별 섭취 차이

  ※ 잔반 데이터의 출처는 지금 목측법이지만, 나중에 푸드스캐너가 들어와도
    intake/menus 계산식은 그대로 쓸 수 있도록 입력 형태만 맞추면 된다.
"""
from __future__ import annotations

import copy
import time
from collections import Counter, defaultdict

from .data import fetch_all
from . import nutrition as nutri
from . import facility_rules as frules

_CACHE: dict = {}
_TTL = 120.0

MEAL_LABEL = {"breakfast": "아침", "lunch": "점심", "dinner": "저녁", "snack": "간식"}
SLOT_LABEL = {"rice": "밥·죽", "soup": "국·탕", "main": "주찬", "side": "부찬", "kimchi": "김치"}
TEXTURE_LABEL = {0: "일반식", 1: "다진식", 2: "갈은식", 3: "유동식"}


def _n(f, k):
    v = (f or {}).get(k)
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _pct(num: int, den: int) -> float | None:
    return None if not den else round(100 * num / den, 1)


# ─────────────────────────── 위험군 정의 ───────────────────────────
# (키, 라벨, 판정함수, 설명) — Insight 규칙이 이 키를 조건으로 쓴다.
RISKS = [
    ("malnourished", "영양불량 (MNA-SF 0–7)",
     lambda f: (_n(f, "mna_sf") is not None and _n(f, "mna_sf") <= 7)),
    ("malnutrition_risk", "영양불량 위험 (MNA-SF 0–11)",
     lambda f: (_n(f, "mna_sf") is not None and _n(f, "mna_sf") <= 11)),
    ("underweight", "저체중 (BMI 18.5 미만)",
     lambda f: (_n(f, "bmi") is not None and _n(f, "bmi") < 18.5)),
    ("obese", "비만 (BMI 25 이상)",
     lambda f: (_n(f, "bmi") is not None and _n(f, "bmi") >= 25)),
    ("chewing", "씹기 어려움",
     lambda f: _n(f, "chewing_difficulty") == 1),
    ("swallowing", "삼킴 어려움",
     lambda f: _n(f, "swallowing_difficulty") == 1),
    ("texture_need", "식형태 조정 필요",
     lambda f: (_n(f, "texture_level") or 0) >= 1),
    ("eating_help", "식사 도움 필요",
     lambda f: (_n(f, "eating_dependence") or 0) >= 1),
    ("low_intake", "저섭취 (전체 섭취율 75% 미만)",
     lambda f: (_n(f, "intake_total") is not None and _n(f, "intake_total") < 75)),
    ("very_low_intake", "심한 저섭취 (50% 미만)",
     lambda f: (_n(f, "intake_total") is not None and _n(f, "intake_total") < 50)),
    ("adl_low", "일상생활 수행 저하 (K-MBI 40 미만)",
     lambda f: (_n(f, "kmbi_score") is not None and _n(f, "kmbi_score") < 40)),
    ("depressed", "우울 의심 (GDS-SF 6점 이상)",
     lambda f: (_n(f, "gds") is not None and _n(f, "gds") >= 6)),
    ("low_satisfaction", "급식 만족 낮음 (3점 이하)",
     lambda f: (_n(f, "sat_overall") is not None and _n(f, "sat_overall") <= 3)),
]


def _risk_block(featlist: list) -> list:
    out = []
    for key, label, test in RISKS:
        hit = [f for f in featlist if test(f)]
        out.append({"key": key, "label": label, "n": len(hit),
                    "pct": _pct(len(hit), len(featlist))})
    return out


# ─────────────────────────── 영양소 ───────────────────────────

def _nutrient_block(featlist: list) -> list:
    """영양소별 '기준 대비 80% 미만' 인원 비율. 나트륨은 '130% 초과'."""
    fld = nutri.fields()
    keys = ["energy", "protein", "fiber", "ca", "fe", "k", "vd", "vc", "b12", "na"]
    short, cnt = defaultdict(int), defaultdict(int)
    for f in featlist:
        n = (f or {}).get("nutrition")
        if not isinstance(n, dict) or not n.get("avg_day"):
            continue
        gender = "여자" if _n(f, "female") == 1 else "남자"
        for t in nutri.compare_targets(n["avg_day"], gender, _n(f, "age")):
            if t["key"] not in keys:
                continue
            cnt[t["key"]] += 1
            over = t["pct"] > 130 if t["key"] == "na" else t["pct"] < 80
            if over:
                short[t["key"]] += 1
    out = []
    for k in keys:
        if not cnt[k]:
            continue
        meta = fld.get(k, {})
        out.append({"key": k, "label": meta.get("label", k), "unit": meta.get("unit", ""),
                    "direction": "초과" if k == "na" else "부족",
                    "n": short[k], "denom": cnt[k], "pct": _pct(short[k], cnt[k])})
    return sorted(out, key=lambda x: -(x["pct"] or 0))


# ─────────────────────────── 식사·메뉴 ───────────────────────────

def _intake_block(featlist: list) -> dict:
    """끼니별·음식군별 평균 섭취율 (개인 features 의 집계)."""
    comp = {"intake_rice": "밥·죽", "intake_soup": "국·탕", "intake_main": "주찬",
            "intake_side": "부찬", "intake_kimchi": "김치"}
    def avg(key):
        vals = [_n(f, key) for f in featlist]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None, len(vals)

    total, n_total = avg("intake_total")
    comps = []
    for k, label in comp.items():
        v, n = avg(k)
        comps.append({"key": k, "label": label, "value": v, "n": n})
    return {"total": total, "n": n_total,
            "components": sorted(comps, key=lambda x: (x["value"] is None, x["value"]))}


def _menu_block(featlist: list, meal_forms: dict | None = None) -> dict:
    """식단표 × 개인 잔반 → 끼니·일자·메뉴(슬롯) 단위 시설 평균 섭취율.

    meal_log 의 각 끼니에 음식군별 섭취율이 들어 있으므로,
    (일자, 끼니, 음식군) 좌표마다 전원의 값을 모아 평균한다.
    그 좌표의 메뉴명은 식단표(menu_plan)에서 가져온다.
    """
    cell = defaultdict(list)      # (day, meal, slot) -> [섭취율]
    meal_rate = defaultdict(list)  # meal -> [끼니 전체 섭취율]
    day_rate = defaultdict(list)   # day  -> [끼니 전체 섭취율]

    names: dict = {}               # (day, meal, slot) -> 메뉴명 (개인 기록에 이미 들어 있다)
    for f in featlist:
        log = (f or {}).get("meal_log")
        if not isinstance(log, list):
            continue
        for rec in log:
            if not isinstance(rec, dict):
                continue
            day, meal = rec.get("day"), rec.get("meal")
            if day is None or not meal:
                continue
            item_rates = []
            for item in (rec.get("items") or []):
                slot, rate = item.get("slot"), item.get("rate")
                if not slot or rate is None:
                    continue
                cell[(day, meal, slot)].append(float(rate))
                item_rates.append(float(rate))
                if item.get("name"):
                    names.setdefault((day, meal, slot), item["name"])
            # 끼니 전체 섭취율 — 기록에 없으면 음식군 평균으로 갈음
            r = rec.get("rate")
            r = float(r) if r is not None else (sum(item_rates) / len(item_rates) if item_rates else None)
            if r is not None:
                meal_rate[meal].append(r)
                day_rate[day].append(r)

    menus = []
    for (day, meal, slot), vals in cell.items():
        if not vals:
            continue
        menus.append({
            "day": day, "meal": meal, "meal_label": MEAL_LABEL.get(meal, meal),
            "slot": slot, "slot_label": SLOT_LABEL.get(slot, slot),
            "menu": names.get((day, meal, slot)),
            "rate": round(sum(vals) / len(vals), 1), "n": len(vals),
        })
    menus.sort(key=lambda x: (x["rate"], -x["n"]))

    # 같은 메뉴가 여러 날 나오면 하나로 묶는다 — 식단 개편은 메뉴 단위로 판단한다
    agg = defaultdict(lambda: {"vals": [], "n": 0, "cells": 0, "slots": set(), "meals": set(), "days": set()})
    for m in menus:
        key = m["menu"] or f"{m['slot_label']} (메뉴명 없음)"
        a = agg[key]
        a["vals"].append(m["rate"] * m["n"])
        a["n"] += m["n"]
        a["cells"] += 1
        a["slots"].add(m["slot_label"])
        a["meals"].add(m["meal_label"])
        a["days"].add(m["day"])
    by_menu = [{"menu": k,
                "rate": round(sum(a["vals"]) / a["n"], 1) if a["n"] else None,
                "n": a["n"], "cells": a["cells"],
                "slot_label": " · ".join(sorted(a["slots"])),
                "meal_label": " · ".join(sorted(a["meals"])),
                "days": sorted(a["days"])}
               for k, a in agg.items() if a["n"]]
    by_menu.sort(key=lambda x: (x["rate"], -x["n"]))

    return {
        "by_meal": [{"meal": m, "label": MEAL_LABEL.get(m, m),
                     "rate": round(sum(v) / len(v), 1), "n": len(v)}
                    for m, v in sorted(meal_rate.items()) if v],
        "by_day": [{"day": d, "rate": round(sum(v) / len(v), 1), "n": len(v)}
                   for d, v in sorted(day_rate.items()) if v],
        "worst": by_menu[:10],           # 메뉴 단위 (식단 개편 후보)
        "best": list(reversed(by_menu[-5:])) if by_menu else [],
        "worst_cells": menus[:10],       # 일자×끼니 단위 (언제 문제였는지)
        "n_menus": len(by_menu),
        "n_cells": len(menus),
    }


def _group_block(featlist: list) -> dict:
    """식형태군·유형별 섭취 차이 — 운영 단위로 볼 수 있게."""
    by_tex = defaultdict(list)
    for f in featlist:
        v = _n(f, "intake_total")
        if v is None:
            continue
        by_tex[int(_n(f, "texture_level") or 0)].append(v)
    return {"by_texture": [{"level": lv, "label": TEXTURE_LABEL.get(lv, str(lv)),
                            "rate": round(sum(v) / len(v), 1), "n": len(v)}
                           for lv, v in sorted(by_tex.items())]}


def _disease_block(featlist: list) -> list:
    c = Counter()
    for f in featlist:
        for d in ((f or {}).get("diseases") or []):
            name = str(d).strip()
            if name:
                c[name] += 1
    n = len(featlist)
    return [{"name": k, "n": v, "pct": _pct(v, n)} for k, v in c.most_common(15)]


def _texture_block(featlist: list) -> list:
    c = Counter()
    for f in featlist:
        lv = _n(f, "texture_level")
        if lv is not None:
            c[int(lv)] += 1
    n = sum(c.values())
    return [{"level": lv, "label": TEXTURE_LABEL.get(lv, str(lv)),
             "n": c[lv], "pct": _pct(c[lv], n)} for lv in sorted(c)]


# ─────────────────────────── 진입점 ───────────────────────────

def build_profile(sb, home: str, use_cache: bool = True) -> dict:
    hit = _CACHE.get(home)
    if use_cache and hit and time.time() - hit[0] < _TTL:
        return hit[1]

    residents = fetch_all(sb, "elderly_residents", "id", eq={"nursing_home_id": home})
    latest = {}
    for row in fetch_all(sb, "care_assessments", "elderly_id,type_code,type_name,features,created_at",
                         eq={"nursing_home_id": home}, order="created_at", desc=True):
        latest.setdefault(row["elderly_id"], row)

    # 예전 평가에는 섭취 영양소가 저장돼 있지 않다. 개인 리포트와 같은 방식으로
    # 식사 기록에서 즉석 계산해 채운 뒤 집계한다 (저장은 재평가 때 이뤄진다).
    featlist, healed = [], 0
    gaps = {"no_assessment": [], "no_meal_log": [], "nutrition_failed": [], "ok": 0}
    for r in residents:
        if r["id"] not in latest:
            gaps["no_assessment"].append(r["id"])

    for eid, row in latest.items():
        f = row.get("features")
        if not isinstance(f, dict):
            gaps["no_assessment"].append(eid)
            continue
        has_nut = isinstance(f.get("nutrition"), dict) and bool(f["nutrition"].get("avg_day"))
        if not has_nut:
            if not f.get("meal_log"):
                gaps["no_meal_log"].append(eid)
            else:
                try:
                    _log, live = nutri.enrich_meal_log(copy.deepcopy(f["meal_log"]), f.get("meal_form"), eid)
                except Exception:
                    live = None
                if live:
                    f = {**f, "nutrition": live}
                    healed += 1
                    has_nut = True
                else:
                    gaps["nutrition_failed"].append(eid)
        if has_nut:
            gaps["ok"] += 1
        featlist.append(f)
    types = Counter(r.get("type_name") or r.get("type_code") for r in latest.values())

    out = {
        "facility_id": home,
        "n_residents": len(residents),
        "n_assessed": len(featlist),
        "coverage_pct": _pct(len(featlist), len(residents)),
        "assessed_on": max((r.get("created_at") or "")[:10] for r in latest.values()) if latest else None,
        "risks": _risk_block(featlist),
        "nutrients": _nutrient_block(featlist),
        "nutrition_recomputed": healed,
        # 영양소 집계에서 누가 왜 빠졌는지 — 분모가 기대보다 작을 때 원인을 바로 본다
        "data_gaps": {
            "nutrition_ok": gaps["ok"],
            "no_assessment": len(gaps["no_assessment"]),
            "no_meal_log": len(gaps["no_meal_log"]),
            "nutrition_failed": len(gaps["nutrition_failed"]),
            "no_assessment_ids": sorted(gaps["no_assessment"])[:20],
            "no_meal_log_ids": sorted(gaps["no_meal_log"])[:20],
            "nutrition_failed_ids": sorted(gaps["nutrition_failed"])[:20],
        },
        "diseases": _disease_block(featlist),
        "texture": _texture_block(featlist),
        "intake": _intake_block(featlist),
        "menus": _menu_block(featlist),
        "groups": _group_block(featlist),
        "types": [{"name": k, "n": v, "pct": _pct(v, len(latest))} for k, v in types.most_common()],
    }
    out["priorities"] = frules.analyze(out)
    _CACHE[home] = (time.time(), out)
    return out
