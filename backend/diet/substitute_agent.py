"""
substitute_agent.py  ─  질환 맞춤 대체찬 (고령친화우수식품)   [2026-10-19 개편]
=====================================================================
[흐름]  기본 일반식(시설 공통) → 식사형태 규칙(meal_form.py: 죽식 죽 · 백김치) 적용
        → 대상 입소자(당뇨·고혈압·치매)의 끼니를 개인 기준으로 점검
        → 기준을 벗어나게 만드는 반찬을 고령친화우수식품으로 교체 (끼니당 최대 2개)

[대체 판단] 위반 점수 V (클수록 대체 필요)
  · 초과: 나트륨·당류·포화지방·지방·단백질(신장) — 개인 상한이 기본 일반식보다 엄격한 항목만, 10% 넘게 초과 시
  · 부족: 열량(개인 목표) · 단백질 · 식이섬유 · 칼륨(고혈압) — 하한보다 10% 넘게 부족 시   ← 신규
  · 치매: 뇌건강 식재료(등푸른생선·들깨 / 달걀·두부·콩·돼지고기·닭·시금치·브로콜리)가 한 끼에 하나도 없으면 +0.3   ← 신규
  · 선호도: 제품 선택 시 (제품 − 기존 반찬) 시설 선호 점수 차이를 가산 (facility_preference.py)   ← 신규
            개인 기피 반찬 대체는 끔(TRIGGERS["dislike"]) — 선호는 시설 단위로 일반식(f3)에서 반영
  · 물성: 대체 사유가 아님 → 다진찬 '다지기', 갈찬 '갈기'로 조리법만 표기   ← 변경

[제약]
  · 끼니당 최대 MAX_SUBS_PER_MEAL(2)개 (죽·백김치는 식사형태 규칙이라 한도에 포함 안 함)
  · 같은 입소자에게 같은 제품은 NO_REPEAT_DAYS(14)일 안에 다시 쓰지 않음
  · 교체 칸: 국·주찬·부찬1·부찬2 (밥·김치 제외) — 제품의 Meal_Category와 같은 칸만
  · 끼니 단위 안전장치: 교체 후 개인 상한(나트륨 포함) 초과분이 늘어나면 제외
  · 반찬 단위 나트륨 비교(SODIUM_UP_MAX)는 끔 — 끼니 단위 안전장치로 대신함

[제품 데이터] data/사랑과선행_추출결과.xlsx (100g당 영양 × '1인분'(g) ÷ 100 = 1인분 영양)
  · '1인분' 열이 비어 있는 제품은 제외 (기본 중량으로 추정하지 않음)
  · 열량·단백질·지방·포화지방·당류·나트륨 중 하나라도 없으면 제외 (빈 값을 0으로 보면 '저염·저당'으로 오인)
"""
import os
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
import re
import pandas as pd
from . import registry
from .state import MealPlanState
from .meal_rules import ONE_DISH_RICE_LABEL

PRODUCT_XLSX       = os.path.join(DATA_DIR, "products.json")   # [서버] 사랑과선행_추출결과.xlsx → JSON 변환본
PRODUCT_XLSX_OLD   = os.path.join(DATA_DIR, "고령친화우수식품_대체찬.xlsx")  # 이전 193개 정리본 (형식 자동 인식)
REQUIRED_NUTS      = ["energy", "protein", "fat", "sat_fat", "sugar", "sodium"]  # 하나라도 없으면 제외 (0으로 오인 방지)
COOK_BY_TEXTURE    = {"다진찬": "다지기", "갈찬": "갈기"}   # 조리법 칸이 비어 있으면 입소자 식사형태로 결정
MAX_SUBS_PER_MEAL  = 2
NO_REPEAT_DAYS     = 14
MIN_GAIN           = 0.02      # V가 이 이상 줄어야 교체
SODIUM_UP_MAX      = None      # [2026-10-19] 끔 (None). 숫자를 넣으면 기존 반찬 대비 나트륨 증가 상한(mg)
GUARD_SLACK        = 0.02      # 대체 후 다른 기준 초과분 증가 허용치 (사실상 악화 금지)
TOLERANCE          = 0.10      # 개인 기준을 10% 넘게 초과할 때만 위반으로 봄
# 대체를 일으키는 항목 (True/False로 켜고 끔)
TRIGGERS = {
    "sodium":  True,   # 개인 나트륨 상한이 기본 일반식보다 엄격할 때만 (나이별 KDRI가 같으면 해당 없음)
    "sugar":   True,   # 당뇨: 당류 ≤ 열량 10%
    "sat_fat": True,   # 개인 포화지방 상한이 기본보다 엄격할 때만
    "fat":     True,   # 개인 지방 상한이 기본보다 엄격할 때만
    "protein": True,   # 신장질환: 단백질 ≤ 열량 10%
    "texture": False,  # [2026-10-19] 물성은 대체 사유 아님 → 조리법(다지기·갈기)으로 처리
    # ── [2026-10-19] 부족 · 치매 · 선호도 ──
    "energy_low":    True,   # 개인 목표 열량 부족
    "protein_low":   True,   # 단백질 하한(개인·기본 중 높은 값) 부족
    "fiber_low":     True,   # 식이섬유 하한 부족
    "potassium_low": True,   # 칼륨 하한(고혈압) 부족
    "dementia":      True,   # 치매: 뇌건강 식재료 없는 끼니
    "dislike":       False,  # [2026-10-19] 개인 기피 반찬 → 끔 (선호는 시설 단위로 일반식 단계에서 반영)
    "safety":        True,   # [다중 에이전트] 약물·알레르기 에이전트의 피할 식재료가 든 반찬 → 최우선 대체
}
SAFETY_W           = 5.0       # 피할 식재료 반찬 1개당 위반 점수 (영양 위반보다 항상 먼저 바뀌도록 크게)
SAFETY_NO_REPEAT   = 3         # 안전 때문에 바꿀 때는 같은 제품 재사용 간격을 3일로 줄임 (맞는 제품이 적어서)
TARGET_DISEASES    = ("당뇨병", "고혈압")   # + 치매(p.dementia) → 대체 대상
DEMENTIA_W         = 0.3
DISLIKE_W          = 0.3
PERSONAL_DISLIKE   = 0.6       # 개인 선호 점수가 이보다 낮으면 기피 반찬
PREF_W             = 0.5       # 제품 선택 시 (제품 선호 − 기존 반찬 선호) 가중치
PRODUCT_PREF       = 0.7       # 제품 선호 점수 기본값 (product_preference_scores.json 없을 때)
USE_PERSONAL_PREF  = False     # [2026-10-19] False: 시설 선호도만 사용 (개인 점수는 기록·보고용)
# 뇌건강 식재료 (레시피 원재료명 시작 문자열 / 제품명 포함 문자열)
BRAIN_OMEGA3 = ("고등어", "꽁치", "삼치", "연어", "정어리", "참치(통조림)", "전갱이", "청어", "방어", "임연수", "갈치", "들깨", "들기름")
BRAIN_B      = ("달걀", "계란", "두부", "순두부", "연두부", "돼지고기", "닭", "시금치", "브로콜리", "검정콩", "대두", "콩(")
BRAIN_PRODUCT_KW = ("계란", "달걀", "닭", "돼지", "돈", "목살", "미트볼", "너비아니", "두부", "생선", "고등어", "삼치")
SLOTS              = ["밥", "국", "주찬", "부찬1", "부찬2", "김치"]
REPLACEABLE        = {"국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬"}
TEXTURE_SENSITIVE  = ("다진찬", "갈찬")
NUT_KEYS           = ["energy", "protein", "fat", "sat_fat", "sugar", "sodium", "carb", "potassium", "fiber"]

_PRODUCTS = None


def _num(v):
    """'-'·빈칸·문자 → None, '1,234' → 1234.0"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    t = str(v).replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _read_product_table(path: str) -> list:
    """두 형식 모두 [{name, maker, stage, slot, grams, cook, per100{...}}] 로 변환
    · 사랑과선행_추출결과.xlsx : 첫 시트, 'Meal_Category'(주찬/부찬/국/밥), '1인분' (g, 열 이름이 '1인분'으로 시작)
    · 고령친화우수식품_대체찬.xlsx : '제품목록' 시트(header=5행), '대체 칸', '사용', '1회 배식량(g)', '조리법'"""
    if path.endswith(".json"):                     # [서버] 이미 변환된 제품 목록
        import json
        return json.load(open(path, encoding="utf-8"))
    xl = pd.ExcelFile(path)
    if "제품목록" in xl.sheet_names:
        df = pd.read_excel(xl, sheet_name="제품목록", header=4)
        name_col, slot_col, use_col = "제품명", "대체 칸", "사용"
    else:
        df = pd.read_excel(xl, sheet_name=0)
        name_col, slot_col, use_col = "지정제품명", "Meal_Category", None
    df.columns = [str(c).split("\n")[0].strip() for c in df.columns]
    nut_col = {}
    for c in df.columns:                     # '열량 (Kcal/100g)' / '열량' → 앞 단어로 매칭
        head = c.split("(")[0].split(" ")[0].strip()
        key = {"열량": "energy", "탄수화물": "carb", "단백질": "protein", "지방": "fat", "포화지방": "sat_fat",
               "당류": "sugar", "나트륨": "sodium", "칼륨": "potassium"}.get(head)
        if key and key not in nut_col:
            nut_col[key] = c
    # [2026-10-19] '1인분' · '1인분 양(...)' · '1회 배식량(g)' 모두 인식 (총양(g)_5인분 같은 열은 제외)
    g_col = next((c for c in df.columns if c.startswith("1인분") or c.startswith("1회 배식량")), None)
    if g_col is None:
        raise ValueError(f"{path}: '1인분' 열을 찾을 수 없습니다 (열 이름이 '1인분'으로 시작해야 함)")
    rows = []
    for _, r in df.iterrows():
        name = r.get(name_col)
        if pd.isna(name) or not str(name).strip():
            continue
        if use_col and str(r.get(use_col, "")).strip().upper() != "Y":
            continue
        cook = r.get("조리법") if "조리법" in df.columns else None
        rows.append({
            "name": str(name).strip(), "maker": r.get("업체명", ""), "stage": r.get("규격단계", ""),
            "slot": str(r.get(slot_col, "")).strip(), "grams": _num(r.get(g_col)) if g_col else None,
            "cook": (str(cook).strip() if cook is not None and pd.notna(cook) and str(cook).strip() else None),
            "per100": {k: _num(r.get(c)) for k, c in nut_col.items()},
        })
    return rows


def load_products(path: str = PRODUCT_XLSX) -> dict:
    """{대체 칸: [제품 dict(1회 배식량 기준)]}"""
    global _PRODUCTS
    if _PRODUCTS is not None:
        return _PRODUCTS
    if not os.path.exists(path):
        print(f"  [대체찬] ⚠ {path} 없음 → 대체 생략")
        _PRODUCTS = {}
        return _PRODUCTS
    out, skipped, other = {}, [], []
    for r in _read_product_table(path):
        slot = r["slot"]
        if slot not in ("국", "주찬", "부찬"):
            other.append(f"{r['name']}({slot})")
            continue
        per100 = r["per100"]
        miss = [k for k in REQUIRED_NUTS if per100.get(k) is None]
        if not r["grams"] or r["grams"] <= 0:
            miss = miss + ["1인분(g)"]
        if miss or per100["sodium"] > 2000 or per100["protein"] > 40:
            skipped.append(f"{r['name']}" + (f"(결측: {','.join(miss)})" if miss else "(값 의심)"))
            continue
        g = r["grams"]                       # 1인분 중량(g) — 영양·배식량 모두 이 값 기준
        item = {k: (v * g / 100 if v is not None else None) for k, v in per100.items()}
        item.update({
            "menu_name": r["name"], "weight": g, "cost": 0, "is_product": True,
            "maker": r["maker"], "stage": r["stage"], "cook": r["cook"],
            "texture": "적합", "one_dish": False, "slot": slot,
            "brain": any(k in r["name"] for k in BRAIN_PRODUCT_KW),
        })
        out.setdefault(slot, []).append(item)
    _PRODUCTS = out
    print(f"  [대체찬] {os.path.basename(path)} → 사용 { {k: len(v) for k, v in out.items()} }")
    if skipped:
        print(f"  [대체찬] 영양값 부족 제외 {len(skipped)}개: {', '.join(skipped)}")
    if other:
        print(f"  [대체찬] 대체 칸 아님(밥·죽 등) {len(other)}개: {', '.join(other)}")
    return out


def _v(x):
    return x or 0.0


_RECIPE_MAP = None


def _brain_tag(m: dict) -> bool:
    """메뉴(또는 제품)가 뇌건강 식재료를 포함하는지 (레시피 원재료 기준, 제품은 이름 기준)"""
    global _RECIPE_MAP
    if "brain" in m:
        return bool(m["brain"])
    if _RECIPE_MAP is None:
        try:
            from .inventory import recipe_ingredients
            _RECIPE_MAP = recipe_ingredients()
        except Exception:
            _RECIPE_MAP = {}
    ings = m.get("ingredients") or _RECIPE_MAP.get(m.get("menu_name"), {})
    tag = any(n.startswith(k) for n in ings for k in BRAIN_OMEGA3 + BRAIN_B)
    m["brain"] = tag
    return tag


_PROD_SCORES = None


def _pref(prefs: dict, m: dict) -> float:
    """선호 점수: 일반식 메뉴 = pool preference_score(시설 점수), 제품 = 시설 속성 모델 예측
    (USE_PERSONAL_PREF=True면 개인 점수가 있을 때 우선)"""
    global _PROD_SCORES
    name = m.get("menu_name")
    if prefs and name in prefs:
        return prefs[name]
    if m.get("is_product"):
        if _PROD_SCORES is None:
            from .facility_preference import load_product_scores
            _PROD_SCORES = load_product_scores()
        return _PROD_SCORES.get(name, PRODUCT_PREF)
    return m.get("preference_score", 0.7)


def is_target(p) -> bool:
    """대체 대상: 당뇨·고혈압·치매"""
    return any(d in TARGET_DISEASES for d in p.diseases) or getattr(p, "dementia", False)


def _ings(m: dict) -> dict:
    """메뉴 → {원재료: g} (제품은 빈 dict → 이름으로 판단)"""
    global _RECIPE_MAP
    if m.get("is_product"):
        return {}
    if _RECIPE_MAP is None:
        try:
            from .inventory import recipe_ingredients
            _RECIPE_MAP = recipe_ingredients()
        except Exception:
            _RECIPE_MAP = {}
    return m.get("ingredients") or _RECIPE_MAP.get(m.get("menu_name"), {})


def safety_hits(m: dict, p) -> list:
    """이 메뉴(또는 제품)에 들어 있는, 어르신이 피해야 할 식재료 사유 목록"""
    av = getattr(p, "avoid", None)
    if not av:
        return []
    from .agents import matches_avoid
    return matches_avoid(_ings(m), m.get("menu_name") or "", av)


def safe_alternatives(m: dict, cat: str, p, pool_index: dict, k: int = 3) -> list:
    """안전 문제로 못 바꾼 칸 → 같은 분류의 일반식 메뉴 중 피할 식재료가 없고 영양이 가장 비슷한 것 k개 (영양사 참고용)"""
    if cat not in ("국", "주찬", "부찬", "김치", "밥"):
        return []
    cands = []
    for (c, nm), x in pool_index.items():
        if c != cat or nm == m.get("menu_name") or safety_hits(x, p):
            continue
        d = (abs(_v(x.get("energy")) - _v(m.get("energy"))) / 100 + abs(_v(x.get("sodium")) - _v(m.get("sodium"))) / 300
             + abs(_v(x.get("protein")) - _v(m.get("protein"))) / 10)
        cands.append((d, nm))
    return [nm for _, nm in sorted(cands)[:k]]


def _violation(items: list, p, base, ratio: float = 1.0, prefs: dict = None, safety_only: bool = False) -> tuple:
    """끼니(밥~김치 6칸) → (위반 점수, 사유 목록)
    · 초과: 기본 일반식(base)보다 엄격한 개인 상한만, TOLERANCE 이상 넘을 때
    · 부족: 개인 목표 열량, 단백질·식이섬유(개인·기본 중 높은 하한), 칼륨(개인 하한)
    · 치매: 뇌건강 식재료 없는 끼니 / 선호도: 기피 반찬"""
    c = p.constraint
    # 개인 배식 비율(목표 열량 ÷ 시설 평균)을 적용한 양으로 비교 — 개인 기준도 목표 열량 비례이므로
    tot = {k: sum(_v(m.get(k)) for m in items) * ratio for k in NUT_KEYS}
    v, why = 0.0, []
    # ── [다중 에이전트] 안전: 약물·알레르기로 피할 식재료가 든 반찬 (국·주찬·부찬) ──
    if TRIGGERS.get("safety") and getattr(p, "avoid", None):
        for m in items[1:5]:
            hits = safety_hits(m, p)
            if hits:
                v += SAFETY_W
                why.append(f"안전({'·'.join(sorted(set(hits)))}): {m.get('menu_name')}")
    if safety_only:
        return v, why
    for key in ("sodium", "sugar", "sat_fat", "fat", "protein"):
        if not TRIGGERS.get(key):
            continue
        lim = getattr(c, f"{key}_max", None)
        if not lim:
            continue
        base_lim = getattr(base, f"{key}_max", None) if base else None
        if base_lim and lim >= base_lim * 0.98:      # 기본 기준과 같거나 느슨 → 대체 사유 아님
            continue
        if tot[key] > lim * (1 + TOLERANCE):
            v += (tot[key] - lim) / lim
            why.append(f"{key} {tot[key]:.0f}>{lim:.0f}")

    # ── [2026-10-19] 부족 ──
    lows = {
        "energy":    max(c.energy_min or 0, min(getattr(p, "target_energy", 0) or 0, c.energy_max or 9999)),
        "protein":   max(c.protein_min or 0, getattr(base, "protein_min", 0) or 0) if not c.protein_max else 0,
        "fiber":     max(c.fiber_min or 0, getattr(base, "fiber_min", 0) or 0),
        "potassium": c.potassium_min or 0,
    }
    for key, lo in lows.items():
        if not TRIGGERS.get(f"{key}_low") or not lo:
            continue
        if tot[key] < lo * (1 - TOLERANCE):
            v += (lo - tot[key]) / lo
            why.append(f"{key}_low {tot[key]:.0f}<{lo:.0f}")

    # ── [2026-10-19] 치매: 뇌건강 식재료 ──
    if TRIGGERS.get("dementia") and getattr(p, "dementia", False):
        if not any(_brain_tag(m) for m in items[1:5]):
            v += DEMENTIA_W
            why.append("치매 뇌건강식재료 없음")

    # ── [2026-10-19] 선호도: 기피 반찬 ──
    if TRIGGERS.get("dislike") and prefs:
        bad = [m["menu_name"] for m in items[1:5] if not m.get("is_product") and _pref(prefs, m) < PERSONAL_DISLIKE]
        if bad:
            v += DISLIKE_W * len(bad)
            why.append("기피 메뉴: " + ",".join(bad))

    sensitive = p.meal_texture_side in TEXTURE_SENSITIVE or p.meal_texture_rice == "죽"
    if TRIGGERS.get("texture") and sensitive:
        bad = [m["menu_name"] for m in items[1:5] if m.get("texture") == "부적합"]
        if bad:
            v += len(bad)
            why.append("식사형태 부적합: " + ",".join(bad))
    return v, why


def _guard(items: list, p, ratio: float = 1.0) -> float:
    """대체로 다른 기준이 나빠지지 않게: 개인 상한 전체(기본과 같은 항목 포함) 초과분 합"""
    c = p.constraint
    tot = {k: sum(_v(m.get(k)) for m in items) * ratio for k in NUT_KEYS}
    g = 0.0
    for key in ("sodium", "sugar", "sat_fat", "fat", "protein"):
        lim = getattr(c, f"{key}_max", None)
        if lim and tot[key] > lim:
            g += (tot[key] - lim) / lim
    return g


_LABEL = {"sodium": "나트륨 초과", "sugar": "당류 초과", "sat_fat": "포화지방 초과", "fat": "지방 초과",
          "protein": "단백질 초과", "energy_low": "열량 부족", "protein_low": "단백질 부족",
          "fiber_low": "식이섬유 부족", "potassium_low": "칼륨 부족"}


def _reason_label(why: list) -> str:
    out = []
    for w in why:
        if w.startswith(("식사형태", "기피 메뉴", "치매", "안전")):
            out.append(w)
        else:
            out.append(_LABEL.get(w.split(" ")[0], w))
    return " / ".join(out)


def _day_no(day_label: str) -> int:
    m = re.search(r"\d+", str(day_label))
    return int(m.group()) if m else 0


def substitute_agent(state: MealPlanState) -> dict:
    print("\n[SubstituteAgent] 질환 맞춤 대체찬 산출 시작...")
    products   = load_products()
    df_records = state.get("df_menu_records") or []
    pool       = state.get("pool") or {}
    patients   = registry.get(state["patients_key"]) if state.get("patients_key") else []
    if not products or not df_records:
        return {"personal_menus": {}, "substitutions": [],
                "messages": ["[SubstituteAgent] 제품 또는 식단 없음 — 건너뜀"]}

    pool_index = {(cat, m["menu_name"]): m for cat, ms in pool.items() for m in ms}
    base = registry.get(state["constraint_key"]) if state.get("constraint_key") and registry.has(state["constraint_key"]) else None
    no_rice = {"menu_name": ONE_DISH_RICE_LABEL, **{k: 0 for k in NUT_KEYS}, "texture": "적합"}
    cat_of = {"밥": "밥", "국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "김치": "김치"}
    rows = sorted(df_records, key=lambda r: (_day_no(r["일차"]), {"아침": 0, "점심": 1, "저녁": 2}.get(r["끼니"], 9)))
    mf_over  = state.get("meal_form_overrides") or {}     # [2026-10-19] 죽식·백김치 (meal_form.py)
    mf_items = state.get("meal_form_items") or {}
    weights  = state.get("preference_weights") or {}

    from .serving_agent import _calc_ratio
    energies = [p.target_energy for p in patients if getattr(p, "target_energy", None)]
    fac_avg  = sum(energies) / len(energies) if energies else 700

    personal_menus, subs, safety_flags = {}, [], []
    for p in patients:
        target = is_target(p)
        if not target and not getattr(p, "avoid", None):
            continue
        so = not target                                   # 질환 대상이 아니면 안전 사유로만 대체
        ratio = _calc_ratio(p, fac_avg)
        prefs = weights.get(p.name, {}) if USE_PERSONAL_PREF else {}
        last_used = {}   # 제품명 → 마지막 사용 일차
        for r in rows:
            day = _day_no(r["일차"])
            key = f"{p.name}||{r['일차']}||{r['끼니']}"
            over = mf_over.get(key, {})
            items = []
            for s in SLOTS:
                name = r.get(s, "")
                if s in over and over[s] in mf_items:
                    items.append(mf_items[over[s]])
                elif s == "밥" and str(name).startswith("-("):
                    items.append(no_rice)
                else:
                    items.append(pool_index.get((cat_of[s], name), {"menu_name": name, **{k: 0 for k in NUT_KEYS}}))
            base_v, base_why = _violation(items, p, base, ratio, prefs, so)
            if base_v <= 0:
                if getattr(p, "avoid", None):
                    for s_, m_ in zip(SLOTS, items):
                        h_ = safety_hits(m_, p)
                        if h_:
                            safety_flags.append({"elderly_id": p.name, "day": r["일차"], "meal": r["끼니"], "slot": s_,
                                                 "menu": m_.get("menu_name"), "reason": "·".join(sorted(set(h_))),
                                                 "alternatives": safe_alternatives(m_, cat_of[s_], p, pool_index)})
                continue

            changes, cur_v, cur_why = {}, base_v, base_why
            cur_g = _guard(items, p, ratio)
            while len(changes) < MAX_SUBS_PER_MEAL and cur_v > 0:
                best = None
                used_now = {m["menu_name"] for m in items}
                for slot, pslot in REPLACEABLE.items():
                    if slot in changes or items[SLOTS.index(slot)].get("one_dish"):
                        continue   # 한 그릇 음식은 일반 반찬 제품으로 바꾸지 않음
                    i = SLOTS.index(slot)
                    unsafe = bool(safety_hits(items[i], p))       # 이 칸이 안전 문제로 바꿔야 하는 칸인가
                    gap = SAFETY_NO_REPEAT if unsafe else NO_REPEAT_DAYS
                    for prod in products.get(pslot, []):
                        nm = prod["menu_name"]
                        if nm in used_now or (nm in last_used and day - last_used[nm] < gap):
                            continue
                        if safety_hits(prod, p):                 # 안전 게이트: 피할 식재료 제품은 후보에서 제외
                            continue
                        if SODIUM_UP_MAX is not None and _v(prod.get("sodium")) - _v(items[i].get("sodium")) > SODIUM_UP_MAX:
                            continue
                        trial = items[:i] + [prod] + items[i + 1:]
                        tv, _ = _violation(trial, p, base, ratio, prefs, so)
                        gain = cur_v - tv
                        tg = _guard(trial, p, ratio)
                        if tg > cur_g + GUARD_SLACK and not unsafe:   # 대체로 다른 기준(예: 나트륨)이 나빠지면 제외 (안전 교체는 예외)
                            continue
                        if gain < MIN_GAIN:
                            continue
                        # 위반 감소 + 선호도 차이 가산, 동률이면 단백질 많은 제품 우선
                        score = gain + PREF_W * (_pref(prefs, prod) - _pref(prefs, items[i]))
                        k = (round(score, 6), _v(prod.get("protein")))
                        if best is None or k > best[0]:
                            best = (k, slot, i, prod, tv)
                if best is None:
                    break
                _, slot, i, prod, tv = best
                orig = items[i]["menu_name"]
                items[i] = prod
                changes[slot] = prod["menu_name"]
                last_used[prod["menu_name"]] = day
                cur_v, cur_why = _violation(items, p, base, ratio, prefs, so)
                cur_g = _guard(items, p, ratio)
                subs.append({
                    "name": p.name, "type": p.disease_type_label + ("·치매" if getattr(p, "dementia", False) else ""),
                    "texture": f"{p.meal_texture_rice}/{p.meal_texture_side}",
                    "day": r["일차"], "meal": r["끼니"], "slot": slot, "orig": orig,
                    "product": prod["menu_name"], "maker": prod["maker"], "stage": prod["stage"],
                    "cook": prod["cook"] or COOK_BY_TEXTURE.get(p.meal_texture_side, "그대로"), "grams": prod["weight"],
                    "reason": _reason_label(base_why),
                    "v_before": round(base_v, 3), "v_after": round(cur_v, 3),
                })
            if changes:
                personal_menus[key] = changes
            # 바꾸고도 남은 안전 문제 (밥·김치 칸, 대체 2칸 초과, 맞는 제품 없음) → 영양사 확인 목록
            if getattr(p, "avoid", None):
                for s_, m_ in zip(SLOTS, items):
                    h_ = safety_hits(m_, p)
                    if h_:
                        safety_flags.append({"elderly_id": p.name, "day": r["일차"], "meal": r["끼니"], "slot": s_,
                                             "menu": m_.get("menu_name"), "reason": "·".join(sorted(set(h_))),
                                             "alternatives": safe_alternatives(m_, cat_of[s_], p, pool_index)})

    n_people = len({s["name"] for s in subs})
    print(f"[SubstituteAgent] 완료 — 대체 {len(subs)}건 / {len(personal_menus)}끼 / {n_people}명")
    sub_products = {pr["menu_name"]: pr for lst in products.values() for pr in lst}
    return {
        "personal_menus": personal_menus,
        "substitutions":  subs,
        "sub_products":   sub_products,
        "safety_flags":   safety_flags,
        "messages": [f"[SubstituteAgent] 대체찬 {len(subs)}건 ({n_people}명)"],
    }
