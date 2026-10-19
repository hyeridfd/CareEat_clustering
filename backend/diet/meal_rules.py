"""
meal_rules.py  ─  현장 식단 작성 규칙 (한 그릇 음식 · 식사형태)
=================================================================
[데이터]  data/메뉴_식사형태_분류.xlsx  (영양사 검토 파일)
  · 한 그릇 음식 : '한 그릇 확인'(Y/N)이 있으면 그 값, 없으면 '한 그릇 음식' 열이 Y인 경우
  · 다진찬 적합도: '최종 적합도'(영양사 판정 우선, 없으면 규칙 분류)

[규칙]  최적화 f4(패턴 위반)에 반영
  ① 한 그릇 음식이 있는 끼니는 밥을 내지 않음 (밥 칸 → ONE_DISH_RICE_LABEL, 영양·비용 0)
  ② 한 끼에 한 그릇 음식은 1개까지
  ③ 한 그릇 끼니는 7일 단위로 ONE_DISH_MAX_PER_WEEK 회까지
  ④ 다진찬 '부적합' 메뉴는 한 끼에 0개, '주의' 메뉴는 한 끼에 TEXTURE_CAUTION_MAX 개까지
"""
import os
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

TEXTURE_XLSX = os.path.join(DATA_DIR, "meal_policy.json")   # [서버] 영양사 검토 엑셀 → JSON 변환본

ONE_DISH_RICE_LABEL   = "-(일품식)"   # 한 그릇 끼니의 밥 칸 표시
ONE_DISH_MAX_PER_WEEK = 2             # 7일 단위 한 그릇 끼니 상한
TEXTURE_CAUTION_MAX   = 2             # 한 끼 '주의' 메뉴 허용 개수
UNKNOWN_TEXTURE       = "주의"        # 엑셀에 없는 새 메뉴의 기본값 (안전 쪽)

# f4 구성 가중치 (합으로 나눠 평균) ─ 0으로 두면 해당 규칙 끔
F4_WEIGHTS = {
    "side_dup":   1.0,   # 같은 끼니 부찬1=부찬2
    "carry_over": 1.0,   # 14일 내 반복
    "one_dish":   1.0,   # ②③ 한 그릇 음식 규칙
    "texture":    1.0,   # ④ 다진찬 적합도
}

_POLICY = None


def load_policy(path: str = TEXTURE_XLSX) -> dict:
    """{(카테고리, 메뉴명): {"one_dish": bool, "texture": str}}"""
    global _POLICY
    if _POLICY is not None:
        return _POLICY
    if not os.path.exists(path):
        print(f"  [식단 규칙] ⚠ {path} 없음 → 한 그릇·식사형태 규칙 미적용")
        _POLICY = {}
        return _POLICY

    if path.endswith(".json"):                     # [서버] {"카테고리|메뉴명": {...}}
        import json
        raw = json.load(open(path, encoding="utf-8"))
        _POLICY = {tuple(k.split("|", 1)): v for k, v in raw.items()}
        return _POLICY
    from openpyxl import load_workbook
    ws  = load_workbook(path, data_only=True)["메뉴분류"]
    hdr = [c.value for c in ws[5]]
    col = {h.split("\n")[0] if h else h: i for i, h in enumerate(hdr)}
    pol = {}
    for r in ws.iter_rows(min_row=6, values_only=True):
        name, cat = r[col["메뉴명"]], r[col["카테고리"]]
        if not name:
            continue
        confirm = (r[col["한 그릇 확인"]] or "").strip().upper()
        one = (confirm == "Y") if confirm in ("Y", "N") else (str(r[col["한 그릇 음식"]]).strip() == "Y")
        tex = (r[col["영양사 판정"]] or r[col["최종 적합도"]] or r[col["다진찬 적합도"]] or UNKNOWN_TEXTURE)
        prev = pol.get((cat, name))
        if prev:   # 같은 이름이 여러 줄이면 엄격한 쪽
            order = {"적합": 0, "주의": 1, "부적합": 2}
            tex = max(tex, prev["texture"], key=lambda t: order.get(t, 1))
            one = one or prev["one_dish"]
        pol[(cat, name)] = {"one_dish": one, "texture": tex}
    _POLICY = pol
    return pol


def apply_meal_rules(pool: dict, verbose: bool = True) -> dict:
    """pool 메뉴에 one_dish / texture 속성을 붙입니다."""
    pol = load_policy()
    unknown, n_one = 0, 0
    for cat, menus in pool.items():
        for m in menus:
            p = pol.get((cat, m["menu_name"]))
            if p is None:
                unknown += 1
                p = {"one_dish": False, "texture": UNKNOWN_TEXTURE}
            m["one_dish"] = bool(p["one_dish"]) and cat != "밥"
            m["texture"]  = p["texture"]
            n_one += m["one_dish"]
    if verbose:
        tex = {}
        for ms in pool.values():
            for m in ms:
                tex[m["texture"]] = tex.get(m["texture"], 0) + 1
        print(f"  [식단 규칙] 한 그릇 음식 {n_one}개 | 다진찬 적합도 {tex}"
              + (f" | ⚠ 분류 없는 메뉴 {unknown}개 → '{UNKNOWN_TEXTURE}'" if unknown else ""))
    return pool


NO_RICE = {"menu_name": ONE_DISH_RICE_LABEL, "energy": 0, "protein": 0, "fat": 0, "sugar": 0,
           "fiber": 0, "sodium": 0, "carb": 0, "sat_fat": 0, "potassium": 0, "vit_d": 0,
           "cost": 0, "weight": 0, "one_dish": False, "texture": "적합", "preference_score": 0.7}


def effective_meal(menus6: list) -> list:
    """한 끼(밥,국,주찬,부찬1,부찬2,김치) → 한 그릇 음식이 있으면 밥을 NO_RICE로 대체"""
    if any(m.get("one_dish") for m in menus6[1:]):
        return [NO_RICE] + list(menus6[1:])
    return menus6
