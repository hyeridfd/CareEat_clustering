# -*- coding: utf-8 -*-
"""
섭취 영양소 산출

    섭취 영양소 = 메뉴 1인분 영양소 × 배식계수 × 섭취율
    배식계수  = 밥/죽·국/탕 → 배식량 ÷ 식사형태별 1인 제공량
                그 외(주찬·부찬·김치) → 배식량 ÷ 레시피 총량
    섭취율    = 1 − 잔반등급/4  (조사 목측법. meal_log 의 rate 를 그대로 쓴다)

메뉴 영양성분은 CAN Pro 산출 결과를, 식단표·배식량은 조사 앱 설정을 그대로 옮겨 둔
nutrition_data/*.json 에서 읽는다. 간식은 CAN Pro 자료가 없어 제외한다.
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "nutrition_data"
MAIN_MEALS = ("아침", "점심", "저녁")
RATIO_SLOTS = ("밥/죽", "국/탕")          # 1인 제공량을 분모로 쓰는 슬롯
SLOT_ORDER = ["밥/죽", "국/탕", "주찬", "부찬1", "부찬2", "김치1", "김치2"]


@lru_cache(maxsize=1)
def _menus():
    d = json.loads((DATA / "menu_nutrients.json").read_text(encoding="utf-8"))
    idx = {}
    for name in d["menus"]:
        k = re.sub(r"[\s_]", "", name).replace("*", "").replace(":", "")
        idx.setdefault(k, name)
        if k.endswith("HS"):
            idx.setdefault(k[:-2], name)
    return d["fields"], d["menus"], idx


@lru_cache(maxsize=1)
def _plan():
    d = json.loads((DATA / "menu_plan.json").read_text(encoding="utf-8"))
    return d["MEAL_FOODS_BY_DAY"], d["DEFAULT_PORTIONS"], d.get("JUK_OVERRIDE", {})


@lru_cache(maxsize=1)
def _targets():
    return json.loads((DATA / "nutrition_targets.json").read_text(encoding="utf-8"))


def fields() -> dict:
    """지표 키 → {label, unit, digits}"""
    return _menus()[0]


ALIAS = {"흰밥": "쌀밥", "흰죽": "죽:흰죽", "닭+배추죽": "닭배추죽_HS",
         "꼬시래기무무무침": "꼬시래기무무침_HS"}


def _match(name):
    _, menus, idx = _menus()
    key = re.sub(r"[\s_]", "", str(name)).replace("*", "").replace(":", "")
    return idx.get(key)


def _parse_rice(text):
    """'잡곡밥/영양죽(콩나물죽) (HS09: 흰죽)' → (밥, 죽, {어르신ID: 대체죽})"""
    per = {}
    for ids, alt in re.findall(r"\(((?:HS[0-9]+[,\s]*)+):\s*([^)]+)\)", text):
        for pid in re.findall(r"HS[0-9]+", ids):
            per[pid] = alt.strip()
    base = re.sub(r"\((?:HS[0-9]+[,\s]*)+:[^)]+\)", "", text).strip()
    rice, _, juk = base.partition("/")
    m = re.search(r"\((.+?)\)", juk)
    return rice.strip(), (m.group(1) if m else re.sub(r"\(.*\)", "", juk)).strip(), per


def slot_menu(day, meal, slot, meal_form, elderly_id=None):
    """(일자, 끼니, 슬롯, 식사형태) → CAN Pro 음식명. 모르면 None."""
    plan, _, juk = _plan()
    items = {it["food"]: it["menu"] for it in (plan.get(str(day), {}).get(meal) or [])}
    raw = items.get(slot)
    if raw is None:
        return None
    if slot == "밥/죽":
        rice, jk, per = _parse_rice(raw)
        is_juk = not str(meal_form or "").split("/")[0].startswith("일반밥")
        name = jk if is_juk else rice
        if is_juk and elderly_id in per:
            name = per[elderly_id]
        if name == "영양죽":
            name = juk.get(f"{day}-{meal}", name)
    else:
        name = raw
    return _match(ALIAS.get(name, name))


def reference_portion(day, meal, slot, meal_form):
    """C 방식에서 밥/죽·국/탕의 분모로 쓰는 1인 제공량(g)."""
    _, port, _ = _plan()
    p = (port.get(str(day), {}) or {}).get(meal) or {}
    if slot == "밥/죽":
        base = str(meal_form or "").split("/")[0]
        src = "일반밥/일반찬" if base.startswith("일반밥") else "죽/일반찬"
        return (p.get(src) or {}).get("밥/죽")
    if slot == "김치2":
        return (p.get("일반밥/일반찬(백김치)") or {}).get("김치2")
    return (p.get("일반밥/일반찬") or {}).get(slot)


def item_nutrients(day, meal, slot, portion_g, rate_pct, meal_form, elderly_id=None):
    """슬롯 한 칸의 섭취 영양소. (메뉴명, {지표: 값}) 반환."""
    _, menus, _ = _menus()
    name = slot_menu(day, meal, slot, meal_form, elderly_id)
    if not name or portion_g is None:
        return None, None
    nut = menus.get(name)
    if not nut:
        return name, None
    if slot in RATIO_SLOTS:
        ref = reference_portion(day, meal, slot, meal_form)
    else:
        ref = nut.get("g")
    if not ref:
        return name, None
    factor = float(portion_g) / float(ref) * (float(rate_pct or 0) / 100)
    return name, {k: v * factor for k, v in nut.items() if k != "g"}


def _add(acc, nut):
    for k, v in (nut or {}).items():
        acc[k] = acc.get(k, 0.0) + v


def _round(d, digits_of):
    return {k: round(v, 2 if digits_of.get(k, 0) else 1) for k, v in d.items()}


def enrich_meal_log(meal_log, meal_form, elderly_id=None):
    """
    meal_log(일자×끼니 기록)의 각 칸에 메뉴명과 섭취 영양소를 채워 넣고,
    끼니별·일자별 평균 영양소 요약을 함께 돌려준다.
    """
    if not isinstance(meal_log, list) or not meal_log:
        return meal_log, None
    fld = fields()
    digits = {k: v.get("digits", 1) for k, v in fld.items()}
    per_day, per_meal, cells = {}, {}, 0
    for cell in meal_log:
        day, meal = cell.get("day"), cell.get("meal")
        if meal not in MAIN_MEALS:
            continue
        tot = {}
        for it in cell.get("items") or []:
            name, nut = item_nutrients(day, meal, it.get("slot"), it.get("g"), it.get("rate"),
                                       meal_form, elderly_id)
            if name:
                it["name"] = name.replace("_HS", "")
            if nut:
                it["nut"] = _round({k: nut[k] for k in ("energy", "protein", "na") if k in nut}, digits)
                _add(tot, nut)
        if tot:
            cell["nut"] = _round(tot, digits)
            cells += 1
            _add(per_day.setdefault(day, {}), tot)
            _add(per_meal.setdefault(meal, {}), tot)
    if not cells:
        return meal_log, None
    days = sorted(per_day)
    n_day = max(len(days), 1)
    avg_day = {k: v / n_day for k, v in _sum_all(per_day.values()).items()}
    meal_counts = {m: sum(1 for c in meal_log if c.get("meal") == m and c.get("nut")) for m in MAIN_MEALS}
    summary = {
        "days": [{"day": d, **_round(per_day[d], digits)} for d in days],
        "meals": [{"meal": m, **_round({k: v / max(meal_counts[m], 1) for k, v in per_meal[m].items()}, digits)}
                  for m in MAIN_MEALS if m in per_meal],
        "avg_day": _round(avg_day, digits),
        "n_days": len(days),
    }
    return meal_log, summary


def _sum_all(dicts):
    out = {}
    for d in dicts:
        _add(out, d)
    return out


def targets(gender=None):
    t = _targets()
    base = t["female"] if str(gender or "").startswith("여") else t["male"]
    return base, t["kind"]


def compare_targets(avg_day, gender=None):
    """1일 평균 섭취량을 권장섭취량과 비교. [{key,label,unit,value,target,pct,kind,band}]"""
    if not avg_day:
        return []
    fld = fields()
    base, kind = targets(gender)
    out = []
    for k, tgt in base.items():
        v = avg_day.get(k)
        if v is None or not tgt:
            continue
        pct = 100 * v / tgt
        kd = kind.get(k, "rda")
        if kd == "limit":
            band = "good" if pct <= 100 else ("warn" if pct <= 130 else "bad")
        else:
            band = "bad" if pct < 60 else ("warn" if pct < 80 else "good")
        meta = fld.get(k, {})
        out.append({"key": k, "label": meta.get("label", k), "unit": meta.get("unit", ""),
                    "value": round(v, 2 if meta.get("digits", 0) else 1),
                    "target": tgt, "pct": round(pct), "kind": kd, "band": band})
    return out
