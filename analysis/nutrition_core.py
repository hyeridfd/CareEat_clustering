# -*- coding: utf-8 -*-
"""
5일치 식단 · 배식량 · 목측법(잔반) → 섭취 영양소 계산 코어

계산식
    섭취 영양소(어르신, 일자, 끼니, 슬롯)
      = 메뉴 1인분 영양소 × 배식계수 × 섭취율
    배식계수 = 실제 배식량(g) ÷ 1인 제공량(g)
    섭취율   = 1 − 잔반등급/4        (0 다먹음, 1 25%, 2 50%, 3 75%, 4 모두 남김)

1인 제공량(분모) 규칙  ※ '조사 기본 배식량을 1인분으로' 방식
    밥/죽 슬롯 : 밥 계열(일반밥*) → '일반밥/일반찬'의 밥 배식량
                 죽 계열(죽*, 갈죽*) → '죽/일반찬'의 죽 배식량
    김치2      : '일반밥/일반찬(백김치)'의 김치2 배식량
    그 외      : '일반밥/일반찬'의 해당 슬롯 배식량
    → 같은 메뉴를 형태만 바꿔 덜 담는 경우(다진찬·갈찬)가 계수에 그대로 반영된다.
"""
from __future__ import annotations
import json, re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
MEALS = ["아침", "점심", "저녁"]
SLOT_ORDER = ["밥/죽", "국/탕", "주찬", "부찬1", "부찬2", "김치1", "김치2"]
WASTE_LEVELS = {0: 1.00, 1: 0.75, 2: 0.50, 3: 0.25, 4: 0.00}   # 잔반등급 → 섭취율

# 설문 표기 → CAN Pro 음식명
NAME_ALIAS = {
    "흰밥": "쌀밥",
    "흰죽": "죽:흰죽",
    "닭+배추죽": "닭배추죽_HS",
    "꼬시래기무무무침": "꼬시래기무무침_HS",   # 설문 쪽 오타
}
# 1·2일차 '영양죽'의 실제 메뉴 (확인 전 임시값 — override_juk.json 으로 덮어씀)
JUK_OVERRIDE_FILE = HERE / "juk_override.json"


# ─────────────────────────── 메뉴 영양성분 ───────────────────────────

def load_menu_nutrients(csv_path) -> pd.DataFrame:
    """CAN Pro 재료별 결과 CSV → 음식명 × 영양소 (1인분 레시피 합계)."""
    df = pd.read_csv(csv_path, encoding="cp949")
    meta = ["식사군", "음식분류", "음식코드", "음식명", "재료코드", "재료명"]
    # 같은 음식이 여러 끼니에 중복 입력된 행 제거
    # (치커리겉절이처럼 끼니별로 재료량이 1g 단위로 다른 경우가 있어 첫 등장 레시피를 기준으로 삼는다)
    df = df.drop_duplicates(subset=["음식코드", "재료코드"], keep="first")
    nums = [c for c in df.columns if c not in meta]
    out = df.groupby("음식명", as_index=True)[nums].sum()
    return out.rename(columns={"재료량(g)": "총량(g)"})


# ─────────────────────────── 식단표 · 배식량 ───────────────────────────

def load_plan(path=None):
    j = json.loads(Path(path or HERE / "menu_plan.json").read_text(encoding="utf-8"))
    return j["MEAL_FOODS_BY_DAY"], j["DEFAULT_PORTIONS"]


def _juk_override():
    if JUK_OVERRIDE_FILE.exists():
        return json.loads(JUK_OVERRIDE_FILE.read_text(encoding="utf-8"))
    return {}


def parse_rice_slot(text: str):
    """'잡곡밥/영양죽(콩나물죽) (HS09: 흰죽)' → (밥메뉴, 죽메뉴, {어르신ID: 대체죽})"""
    per_person = {}
    for ids, alt in re.findall(r"\(((?:HS[0-9]+[,\s]*)+):\s*([^)]+)\)", text):
        for pid in re.findall(r"HS[0-9]+", ids):
            per_person[pid] = alt.strip()
    base = re.sub(r"\((?:HS[0-9]+[,\s]*)+:[^)]+\)", "", text).strip()
    rice, _, juk = base.partition("/")
    m = re.search(r"\((.+?)\)", juk)
    juk = (m.group(1) if m else re.sub(r"\(.*\)", "", juk)).strip()
    return rice.strip(), juk, per_person


def resolve_menu(name: str, day=None, meal=None) -> str:
    name = NAME_ALIAS.get(name, name)
    if name == "영양죽":
        ov = _juk_override().get(f"{day}-{meal}")
        if ov:
            return NAME_ALIAS.get(ov, ov)
    return name


def _norm(name: str) -> str:
    return re.sub(r"[\s_]", "", str(name)).replace("*", "").replace(":", "")


def match_name(name: str, menu_index: dict) -> str | None:
    return menu_index.get(_norm(name))


def build_menu_index(menu_nut: pd.DataFrame) -> dict:
    """CAN Pro 음식명 색인. '_HS' 접미사를 뗀 표기로도 찾을 수 있게 한다."""
    idx = {}
    for n in menu_nut.index:
        k = _norm(n)
        idx.setdefault(k, n)
        if k.endswith("HS"):
            idx.setdefault(k[:-2], n)
    return idx


# ─────────────────────────── 슬롯 · 배식량 ───────────────────────────

def reference_portion(portions, day, meal, slot):
    """슬롯별 1인 제공량(분모)."""
    p = portions[str(day)][meal]
    if slot == "밥/죽":
        return None  # 밥/죽은 형태에 따라 달라 form_reference() 에서 처리
    if slot == "김치2":
        return p.get("일반밥/일반찬(백김치)", {}).get("김치2")
    return p.get("일반밥/일반찬", {}).get(slot)


def form_reference(portions, day, meal, form):
    """밥/죽 슬롯의 분모 (밥 계열 / 죽 계열)."""
    p = portions[str(day)][meal]
    base = form.split("/")[0]
    src = "일반밥/일반찬" if base.startswith("일반밥") else "죽/일반찬"
    return p.get(src, {}).get("밥/죽")


def meal_slots(plan, portions, day, meal, form, elderly_id=None):
    """(슬롯, 메뉴표기, 기준배식량, 기본배식량) 목록."""
    items = {it["food"]: it["menu"] for it in plan[str(day)][meal]}
    served = portions[str(day)][meal].get(form, {})
    rows = []
    for slot, g in served.items():
        raw = items.get(slot)
        if raw is None:
            continue
        if slot == "밥/죽":
            rice, juk, per_person = parse_rice_slot(raw)
            is_juk = not form.split("/")[0].startswith("일반밥")
            name = juk if is_juk else rice
            if is_juk and elderly_id in per_person:
                name = per_person[elderly_id]
            ref = form_reference(portions, day, meal, form)
        else:
            name = raw
            ref = reference_portion(portions, day, meal, slot)
        rows.append({"슬롯": slot, "메뉴표기": name, "기준배식량(g)": ref, "기본배식량(g)": g})
    return sorted(rows, key=lambda r: SLOT_ORDER.index(r["슬롯"]) if r["슬롯"] in SLOT_ORDER else 99)


def intake_rate(waste):
    """잔반등급 → 섭취율. '추후섭취'·결측은 None."""
    try:
        return WASTE_LEVELS[int(waste)]
    except (TypeError, ValueError, KeyError):
        return None

# ─────────────────────────── 배식계수 ───────────────────────────
# METHOD='A' : 각 식사형태의 기본 배식량을 그 메뉴 1인분으로 본다 (조사 기본값 기준)
# METHOD='C' : 밥/죽·국/탕만 A와 같고, 주찬·부찬·김치는 레시피 총량을 1인 제공량으로 본다
#              (찬류는 조리 수율이 1에 가까워 배식량 ÷ 레시피 총량이 실제 제공 비율에 가깝다)
METHOD = "A"
_RATIO_SLOTS = ("밥/죽", "국/탕")


def serving_factor(slot, portion_g, reference_g, recipe_total_g, method=None):
    method = method or METHOD
    if portion_g is None:
        return None
    if method == "C" and slot not in _RATIO_SLOTS:
        return (portion_g / recipe_total_g) if recipe_total_g else None
    return (portion_g / reference_g) if reference_g else None
