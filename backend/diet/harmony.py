# -*- coding: utf-8 -*-
"""한 끼 조화 점수 — 실제 요양원 식단표의 국·주찬·부찬1·부찬2 조합을 '좋은 조합'으로 보고 학습

  1) 메뉴 → 속성 (이름이 아니라 속성으로 학습해야 처음 보는 메뉴에도 점수를 줄 수 있음)
       조리법   음식코드 앞자리 (B05 국 · B06 탕 · C09 찜 · C10 구이 · C11 전 · C12 볶음 · C13 조림 · C14 튀김 ·
                C15 무침 · C16 샐러드 · C19 장아찌 · A03 면·만두 …), 없으면 이름 끝말
       국 종류   음식코드 5자리 (된장국 · 미역국 · 어패류국 · 채소류국 · 육류국 · 탕 …)
       주재료    재료 중 가장 무거운 단백질·채소 재료의 묶음 (돼지·소·닭·생선·해물·두부콩·달걀·가공육 · 채소·버섯·해조·묵 …)
       양념     고추장·고춧가루(매운 양념) / 간장 / 된장 / 서양식(크림·치즈·케첩·마요) / 맑음
       온도     냉국·냉채·샐러드 = 찬 음식
  2) 실제 한 끼 vs 칸을 섞은 한 끼 를 구분하는 로지스틱 회귀 (harmony_train.py)
       특징 = 칸 쌍의 '겹침'(같은 조리법·주재료·양념, 둘 다 단백질) + 구성(단백질·튀김·매운 양념 수)
              + 끼니 적합도(아침/점심/저녁 × 칸별 조리법·주재료·국 종류)
  3) 조화 점수 = 모델이 본 '실제 한 끼일 확률' (0~1).  식단 설계 f3 에 반영.
"""
from __future__ import annotations

import json
import math
import os
import re
from itertools import combinations

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MODEL_JSON = os.path.join(DATA_DIR, "harmony", "harmony_model.json")

METHOD_BY_CODE3 = {"B05": "국", "B06": "탕", "B07": "찌개", "B08": "전골", "C09": "찜", "C10": "구이", "C11": "전",
                   "C12": "볶음", "C13": "조림", "C14": "튀김", "C15": "무침", "C16": "샐러드", "C17": "김치",
                   "C18": "젓갈", "C19": "장아찌", "A03": "면·만두", "A04": "덮밥·죽", "A02": "덮밥·죽", "A01": "밥"}
METHOD_BY_SUFFIX = [("찌개", "찌개"), ("전골", "전골"), ("탕", "탕"), ("국", "국"), ("스프", "국"), ("죽", "덮밥·죽"),
                    ("볶음", "볶음"), ("조림", "조림"), ("구이", "구이"), ("찜", "찜"), ("튀김", "튀김"), ("까스", "튀김"),
                    ("강정", "튀김"), ("전", "전"), ("부침", "전"), ("무침", "무침"), ("나물", "무침"), ("겉절이", "무침"),
                    ("샐러드", "샐러드"), ("냉채", "샐러드"), ("장아찌", "장아찌"), ("절임", "장아찌"), ("잡채", "볶음"),
                    ("만두", "면·만두"), ("국수", "면·만두")]
SOUP_BY_CODE5 = {"B0501": "된장국", "B0502": "김치국", "B0503": "미역국", "B0504": "냉국", "B0505": "어패류국",
                 "B0506": "육류국", "B0509": "채소류국", "B0510": "두류국", "B0511": "달걀국"}
MAIN_GROUPS = [
    ("가공육", ("햄", "소시지", "스팸", "베이컨", "어묵", "맛살", "크래미", "미트볼", "동그랑땡", "너비아니", "돈까스", "만두")),
    ("돼지", ("돼지", "돈육", "목살", "삼겹", "앞다리", "등갈비", "제육")),
    ("소", ("소고기", "쇠고기", "우육", "사태", "양지", "불고기용", "차돌", "사골", "우족")),
    ("닭·오리", ("닭", "오리", "계육")),
    ("생선", ("고등어", "삼치", "꽁치", "갈치", "조기", "동태", "명태", "코다리", "가자미", "임연수", "연어", "참치", "황태",
             "북어", "대구", "방어", "아귀", "생선", "멸치")),
    ("해물", ("오징어", "낙지", "주꾸미", "쭈꾸미", "문어", "새우", "꽃게", "게살", "조개", "바지락", "홍합", "굴", "전복",
             "꼬막", "해물", "관자")),
    ("두부·콩", ("두부", "순두부", "유부", "콩", "비지", "두유")),
    ("달걀", ("달걀", "계란", "메추리알")),
    ("묵·곤약", ("묵", "곤약", "청포")),
    ("버섯", ("버섯",)),
    ("해조", ("미역", "다시마", "김", "파래", "톳", "매생이", "꼬시래기", "곰피", "자반", "해초")),
    ("감자·고구마", ("감자", "고구마", "단호박", "토란", "옥수수")),
    ("곡류·면", ("떡", "누룽지", "국수", "당면", "면", "쌀", "밀가루", "수제비")),
    ("채소", ()),                                   # 나머지
]
PROTEIN = {"가공육", "돼지", "소", "닭·오리", "생선", "해물", "두부·콩", "달걀"}
SEASON_RULES = [("매운양념", ("고추장", "고춧가루", "고추가루", "청양", "고추기름", "김치")),
                ("된장", ("된장", "청국장", "쌈장")),
                ("서양식", ("크림", "치즈", "케첩", "케찹", "마요네즈", "버터", "우유", "카레", "토마토소스", "머스타드")),
                ("간장", ("간장", "굴소스", "데리야끼"))]
SKIP_ING = ("물", "소금", "설탕", "백설탕", "식용유", "참기름", "들기름", "깨", "참깨", "후추", "후춧가루", "마늘", "대파", "파",
            "양파", "생강", "물엿", "올리고당", "맛술", "청주", "육수", "다시마(말린것)", "멸치(국물용)", "멸치(육수용)")


# 단어가 겹쳐 잘못 잡히는 경우 (예: '콩나물'의 콩, '김치'의 김, '굴소스'의 굴)
NOT_GROUP = {"두부·콩": ("콩나물", "땅콩", "강낭콩깍지"), "해조": ("김치", "김칫", "김말이"), "해물": ("굴소스",),
             "곡류·면": ("면실유",), "생선": ("멸치액젓", "멸치(육수용)", "멸치(국물용)", "멸치육수", "멸치다시마육수")}


def _group(name: str) -> str:
    for g, kws in MAIN_GROUPS:
        if not kws:
            continue
        t = name
        for bad in NOT_GROUP.get(g, ()):
            t = t.replace(bad, " ")
        if any(k in t for k in kws):
            return g
    return "채소"


def menu_attrs(name: str, code: str | None = None, ingredients: dict | None = None) -> dict:
    """메뉴 → {method, soup, main, protein, season, cold}"""
    code = str(code or "")
    name = str(name or "")
    method = METHOD_BY_CODE3.get(code[:3])
    if not method:
        method = next((m for suf, m in METHOD_BY_SUFFIX if suf in name), "기타")
    soup = SOUP_BY_CODE5.get(code[:5]) if method == "국" else (method if method in ("탕", "찌개", "전골") else None)
    if method == "국" and not soup:
        soup = ("된장국" if "된장" in name else "미역국" if "미역" in name else "냉국" if "냉국" in name else "맑은국")
    ings = ingredients or {}
    main, main_ing = None, None
    # 단백질 재료가 일정량(10g) 이상이면 그 묶음, 아니면 가장 무거운 재료 묶음
    items = sorted(((float(v or 0), k) for k, v in ings.items() if not any(k == s or k.startswith(s + "(") for s in SKIP_ING)),
                   reverse=True)
    for g, k in items:
        grp = _group(k)
        if grp in PROTEIN and g >= 10:
            main, main_ing = grp, k
            break
    if main is None:
        main = _group(items[0][1]) if items else _group(name)
        main_ing = items[0][1] if items else None
    if main == "채소" and _group(name) != "채소":
        main = _group(name)
    text = name + " " + " ".join(ings.keys())
    season = next((s for s, kws in SEASON_RULES if any(k in text for k in kws)), "맑음")
    cold = any(k in name for k in ("냉국", "냉채", "샐러드", "사라다", "묵사발")) or method == "샐러드"
    return {"method": method, "soup": soup, "main": main, "main_ingredient": _ing_base(main_ing),
            "protein": main in PROTEIN, "season": season, "cold": bool(cold)}


HARMONY_SCHEMA = "2026-10-28c"      # 특징 정의가 바뀌면 올림 — 모델 파일과 다르면 조화 점수를 쓰지 않음

# 같은 원재료의 다른 표기 (이름 기준). 재료코드 기반 표준화(ingredient_canon)보다 먼저 적용
ING_SYNONYMS = {"돈육": "돼지고기", "돼지": "돼지고기", "소고기": "쇠고기", "우육": "쇠고기", "계란": "달걀", "계육": "닭고기",
                "닭": "닭고기", "닭다리살": "닭고기", "닭가슴살": "닭고기", "두부(부침용)": "두부", "연두부": "두부",
                "알배추": "배추", "알배기배추": "배추", "쪽파": "파", "실파": "파", "대파": "파"}
_CANON = {}                          # 원재료명 → 표준명 (학습 때 재료코드로 만들어 모델 파일에 저장)


def set_canon(m: dict):
    global _CANON
    _CANON = dict(m or {})


def _ing_base(name):
    """재료명 표준화: ① 괄호·밑줄 뒤 설명 제거 ('돼지고기(앞다리)' → '돼지고기', '시금치: 생것' → '시금치')
    ② 동의어 ('돈육' → '돼지고기') ③ 재료코드 기반 표준명 (같은 코드의 다른 표기 → 가장 흔한 이름)"""
    if not name:
        return None
    raw = str(name).strip()
    if raw in _CANON:
        return _CANON[raw]
    b = re.sub(r"\(.*?\)", "", raw)
    b = re.split(r"[:_,/]", b)[0].strip()
    b = ING_SYNONYMS.get(b, b)
    return _CANON.get(b, b) or None


def build_canon(pairs) -> dict:
    """[(원재료명, 식품코드)] → {원재료명: 표준명}
    · 원재료(R) 코드 앞 11자리(식품군+품목+세부)가 같으면 같은 원재료로 보고, 가장 많이 쓰인 기본 이름으로 통일
      (가공식품 P·D 코드는 같은 코드에 다른 제품이 섞여 있어 쓰지 않음)
    · 예: 설탕 → 백설탕 · 천일염 → 소금 · 파(실파) → 대파"""
    from collections import Counter, defaultdict
    by_code = defaultdict(Counter)
    for nm, code in pairs:
        c = str(code or "")
        if not nm or not c.startswith("R") or len(c) < 11:
            continue
        b = re.split(r"[:_,/]", re.sub(r"\(.*?\)", "", str(nm)))[0].strip()
        b = ING_SYNONYMS.get(b, b)
        if b:
            by_code[c[:11]][b] += 1
    total = Counter()
    for cnt in by_code.values():
        total.update(cnt)
    targets = defaultdict(set)                # 기본 이름 → 후보 표준명들
    for c, cnt in by_code.items():
        canon = max(cnt, key=lambda b: (cnt[b], total[b]))
        for b in cnt:
            targets[b].add(canon)
    canons = {next(iter(t)) for t in targets.values() if len(t) == 1}
    out = {}
    for b, t in targets.items():
        # 여러 코드에 걸쳐 표준명이 갈리면(예: 돼지고기 ↔ 돼지부산물) 바꾸지 않음 · 표준명 자신은 그대로 · 육수·국물은 제외
        if len(t) != 1 or b in canons or any(k in b for k in ("육수", "국물")):
            continue
        canon = next(iter(t))
        if canon != b and total[b] <= total[canon]:
            out[b] = canon
    return out


# ─────────────────────────── 특징 ───────────────────────────
#  [2026-10-28 실험] 칸 쌍 속성 교차(1,500여 개)는 검증 AUC 0.54 로 과적합 → 아래 '간결 특징 + 끼니 적합도' 채택 (AUC 0.59)
PAIR_KEYS = (("국", "주찬", 0, 1), ("국", "부찬", 0, 2), ("국", "부찬", 0, 3), ("주찬", "부찬", 1, 2), ("주찬", "부찬", 1, 3),
             ("부찬", "부찬", 2, 3))
ROLES = ("국", "주찬", "부찬", "부찬")
FRIED = ("튀김", "전")


PAIR_GROUPS = {"국-주찬": ((0, 1),), "국-부찬": ((0, 2), (0, 3)), "주찬-부찬": ((1, 2), (1, 3)), "부찬-부찬": ((2, 3),)}
PAIR_ATTRS = ("method", "main", "season", "main_ingredient")
FEATURE_SETS = {"A_조합": dict(use_pair=True, use_composition=False, use_meal=False),
                "B_구성": dict(use_pair=False, use_composition=True, use_meal=False),
                "C_끼니": dict(use_pair=False, use_composition=False, use_meal=True),
                "D_전체": dict(use_pair=True, use_composition=True, use_meal=True)}


def meal_features(soup: dict, main: dict, side1: dict, side2: dict, meal: str | None = None,
                  use_pair: bool = True, use_composition: bool = True, use_meal: bool = True) -> list:
    """한 끼 → 특징 이름 목록 (중복 없음)
    · 조합(use_pair): 칸 쌍(국-주찬 · 국-부찬 · 주찬-부찬 · 부찬-부찬)마다 같은 조리법·주재료 묶음·양념·실제 주재료,
                     둘 다 단백질 반찬. 국-부찬·주찬-부찬은 부찬1·부찬2 중 하나라도 해당하면 1번만
    · 구성(use_composition): 단백질 반찬 수, 튀김·전 수, 매운 양념 칸 수, 반찬 조리법 가짓수
    · 끼니 적합도(use_meal): (아침/점심/저녁) × 칸별 조리법·주재료, 국 종류"""
    xs = (soup, main, side1, side2)
    f = set()
    if use_pair:
        for key, pairs in PAIR_GROUPS.items():
            for i, j in pairs:
                a, b = xs[i], xs[j]
                for x in PAIR_ATTRS:
                    if a.get(x) is not None and a.get(x) == b.get(x):
                        f.add(f"{key}|same_{x}")
                if a["protein"] and b["protein"]:
                    f.add(f"{key}|both_protein")
    if use_composition:
        trio = xs[1:]
        f.add(f"n_protein={sum(x['protein'] for x in trio)}")
        f.add(f"n_fried={min(sum(x['method'] in FRIED for x in trio), 2)}")
        f.add(f"n_spicy={min(sum(x['season'] == '매운양념' for x in xs), 3)}")
        f.add(f"n_method={len({x['method'] for x in trio})}")
    if use_meal and meal:
        for role, x in zip(ROLES, xs):
            f.add(f"{meal}|{role}.m={x['method']}")
            f.add(f"{meal}|{role}.g={x['main']}")
        f.add(f"{meal}|국.t={soup.get('soup')}")
    return sorted(f)


# ─────────────────────────── 점수 (실행 시) ───────────────────────────
_MODEL = None


def load_model(path: str = MODEL_JSON):
    """서비스용 모델 (data/harmony/harmony_model.json). 특징 정의(HARMONY_SCHEMA)가 다르면 쓰지 않음 → 다시 학습 필요"""
    global _MODEL
    if _MODEL is None:
        try:
            m = json.load(open(path, encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            m = {}
        if m and m.get("schema") != HARMONY_SCHEMA:
            print(f"[조화] 모델 파일의 특징 정의({m.get('schema')})가 코드({HARMONY_SCHEMA})와 달라 조화 점수를 끕니다. "
                  f"python -m diet.harmony_train 으로 다시 학습하세요.")
            m = {"stale": True, "path": path}
        else:
            set_canon(m.get("ingredient_canon"))
        m["path"] = path
        _MODEL = m
    return _MODEL


def enabled() -> bool:
    return bool(load_model().get("weights"))


def meal_score(soup: dict, main: dict, side1: dict, side2: dict, meal: str | None = None) -> float:
    m = load_model()
    w = m.get("weights") or {}    
    features = set(
    meal_features(soup, main, side1, side2, meal)
    )

    z = m.get("bias", 0.0) + sum(
        w.get(k, 0.0) for k in features
    )
    return 1 / (1 + math.exp(-z))


class HarmonyTable:
    """후보 풀 메뉴 속성을 정수로 바꿔 두고, 식단 1개(84끼)의 조화 점수를 numpy 로 한 번에 계산 (meal_features 와 같은 값)"""
    MEALS = ("아침", "점심", "저녁")

    def __init__(self, pool: dict, recipe_map: dict | None = None):
        import numpy as np
        m = load_model()
        self.ok = bool(m.get("weights"))
        if not self.ok:
            return
        w, self.bias = m["weights"], float(m.get("bias", 0.0))
        if recipe_map is None:
            from .inventory import recipe_ingredients
            recipe_map = recipe_ingredients()
        codes = _code_map()
        self.attrs = {cat: [menu_attrs(x["menu_name"], codes.get(x["menu_name"]),
                                       x.get("ingredients") or recipe_map.get(x["menu_name"], {}))
                            for x in pool.get(cat, [])] for cat in ("국", "주찬", "부찬")}
        self._encode(w)

    def _encode(self, w):
        """self.attrs(칸별 메뉴 속성) → 정수 배열·가중치 표 (테스트에서 속성을 바꿔 다시 부를 수 있게 분리)"""
        import numpy as np
        voc = {k: sorted({str(a.get(k)) for lst in self.attrs.values() for a in lst})
               for k in ("method", "main", "season", "soup", "main_ingredient")}
        self.voc = voc
        enc = lambda cat, k: np.array([voc[k].index(str(a.get(k))) for a in self.attrs[cat]], dtype=np.int32)
        self.A = {cat: {k: enc(cat, k) for k in ("method", "main", "season", "soup", "main_ingredient")} for cat in self.attrs}
        # 속성값이 None 이면 '같음'으로 세지 않음 (meal_features 의 a.get(x) is not None 규칙과 동일)
        for cat in self.attrs:
            for x in PAIR_ATTRS:
                self.A[cat][f"has_{x}"] = np.array([a.get(x) is not None for a in self.attrs[cat]], dtype=bool)
        for cat in self.attrs:
            self.A[cat]["protein"] = np.array([a["protein"] for a in self.attrs[cat]], dtype=bool)
            self.A[cat]["fried"] = np.array([a["method"] in FRIED for a in self.attrs[cat]], dtype=bool)
            self.A[cat]["spicy"] = np.array([a["season"] == "매운양념" for a in self.attrs[cat]], dtype=bool)
        self.w_pair = {(key, x): w.get(f"{key}|same_{x}", 0.0) for key in PAIR_GROUPS for x in PAIR_ATTRS}
        self.w_bp = {key: w.get(f"{key}|both_protein", 0.0) for key in PAIR_GROUPS}
        self.w_np = np.array([w.get(f"n_protein={k}", 0.0) for k in range(4)])
        self.w_nf = np.array([w.get(f"n_fried={k}", 0.0) for k in range(3)])
        self.w_ns = np.array([w.get(f"n_spicy={k}", 0.0) for k in range(4)])
        self.w_nm = np.array([w.get(f"n_method={k}", 0.0) for k in range(4)])
        # 끼니 적합도 표: [끼니, 속성값]
        self.w_mt = {}
        for role in ("국", "주찬", "부찬"):
            for k, tag in (("method", "m"), ("main", "g")):
                self.w_mt[(role, k)] = np.array([[w.get(f"{ml}|{role}.{tag}={v}", 0.0) for v in voc[k]] for ml in self.MEALS])
        self.w_mt[("국", "soup")] = np.array([[w.get(f"{ml}|국.t={v}", 0.0) for v in voc["soup"]] for ml in self.MEALS])

    STYLE_KEYS = (("국", "soup"), ("주찬", "method"), ("주찬", "main"), ("부찬", "method"), ("부찬", "main"))
    STYLE_SCALE = 0.3          # JS 발산 0 → 1점, 0.3 이상 → 0점

    def _style_init(self):
        import numpy as np
        st = load_model().get("style") or {}
        self.style = {}
        for t, ml in enumerate(self.MEALS):
            for role, key in self.STYLE_KEYS:
                cnt = (st.get(ml) or {}).get(f"{role}.{key}") or {}
                v = np.array([cnt.get(x, 0) for x in self.voc[key]], dtype=float) + 0.5
                self.style[(t, role, key)] = v / v.sum()
        self.ref_real = float(load_model().get("ref_real_mean") or 0.55)

    def style_similarity(self, g, mi, s1, s2, t):
        """설계 식단의 끼니별 속성 분포가 시설 실제 분포와 얼마나 닮았는지 (0~1, Jensen-Shannon 기반)"""
        import numpy as np
        if not hasattr(self, "style"):
            self._style_init()
        src = {"국": (self.A["국"], [g]), "주찬": (self.A["주찬"], [mi]), "부찬": (self.A["부찬"], [s1, s2])}
        js = []
        for ti in range(3):
            sel = t == ti
            for role, key in self.STYLE_KEYS:
                A_, arrs = src[role]
                vals = np.concatenate([A_[key][a[sel]] for a in arrs])
                p = np.bincount(vals, minlength=len(self.voc[key])).astype(float) + 0.5
                p /= p.sum()
                q = self.style[(ti, role, key)]
                m_ = (p + q) / 2
                js.append(0.5 * (p * np.log(p / m_)).sum() + 0.5 * (q * np.log(q / m_)).sum())
        d = float(np.mean(js))
        return max(0.0, 1 - d / self.STYLE_SCALE), d

    def objective(self, g, mi, s1, s2, t):
        """f3 에 넣는 값 (0~1) = 0.5 × 조합 점수(시설 실제 평균까지만 인정) + 0.5 × 시설 스타일 유사도
        조합 점수를 상한 없이 쓰면 모델이 좋아하는 몇몇 속성으로 쏠림 → 실제 평균에서 자름"""
        import numpy as np
        if not hasattr(self, "style"):
            self._style_init()
        h = self.scores(g, mi, s1, s2, t)
        comb = float(np.minimum(h, self.ref_real).mean() / self.ref_real)
        sim, _ = self.style_similarity(g, mi, s1, s2, t)
        return 0.5 * comb + 0.5 * sim

    def scores(self, g, mi, s1, s2, t=None):
        """정수 인덱스 배열 (끼니 수,) → 끼니별 조화 점수. t = 끼니 번호 (0 아침 · 1 점심 · 2 저녁)"""
        import numpy as np
        G, M, S = self.A["국"], self.A["주찬"], self.A["부찬"]
        idx = (("국", G, g), ("주찬", M, mi), ("부찬", S, s1), ("부찬", S, s2))
        z = np.full(len(g), self.bias)
        # 칸 쌍 이름마다 '하나라도 해당하면 1' (meal_features 와 같은 규칙 — 부찬1·부찬2 중복 가산 없음)
        for key, pairs in PAIR_GROUPS.items():
            for x in PAIR_ATTRS:
                occ = np.zeros(len(g), dtype=bool)
                for i, j in pairs:
                    (_, Ai, ii), (_, Aj, jj) = idx[i], idx[j]
                    hit = (Ai[x][ii] == Aj[x][jj]) & Ai[f"has_{x}"][ii]
                    occ |= hit
                z += self.w_pair[(key, x)] * occ
            occ = np.zeros(len(g), dtype=bool)
            for i, j in pairs:
                (_, Ai, ii), (_, Aj, jj) = idx[i], idx[j]
                occ |= Ai["protein"][ii] & Aj["protein"][jj]
            z += self.w_bp[key] * occ
        z += self.w_np[M["protein"][mi].astype(int) + S["protein"][s1] + S["protein"][s2]]
        z += self.w_nf[np.minimum(M["fried"][mi].astype(int) + S["fried"][s1] + S["fried"][s2], 2)]
        z += self.w_ns[np.minimum(G["spicy"][g].astype(int) + M["spicy"][mi] + S["spicy"][s1] + S["spicy"][s2], 3)]
        nm = 1 + (M["method"][mi] != S["method"][s1]).astype(int) + \
            ((S["method"][s2] != M["method"][mi]) & (S["method"][s2] != S["method"][s1])).astype(int)
        z += self.w_nm[nm]
        if t is not None:
            for role, A_, ii in (("국", G, g), ("주찬", M, mi), ("부찬", S, s1)):
                z += self.w_mt[(role, "method")][t, A_["method"][ii]] + self.w_mt[(role, "main")][t, A_["main"][ii]]
            # 부찬2: 부찬1과 같은 값이면 특징 이름이 같아 한 번만 (meal_features 는 중복 없는 집합)
            for k in ("method", "main"):
                z += self.w_mt[("부찬", k)][t, S[k][s2]] * (S[k][s2] != S[k][s1])
            z += self.w_mt[("국", "soup")][t, G["soup"][g]]
        return 1 / (1 + np.exp(-z))


_CODES = None


def _code_map() -> dict:
    """레시피 DB 음식명 → 음식 코드"""
    global _CODES
    if _CODES is None:
        try:
            import pandas as pd
            r = pd.read_csv(os.path.join(DATA_DIR, "recipes.csv"), usecols=["음식명", "음식 코드"]).drop_duplicates("음식명")
            _CODES = dict(zip(r["음식명"], r["음식 코드"].astype(str)))
        except Exception:
            _CODES = {}
    return _CODES


def explain(soup: dict, main: dict, side1: dict, side2: dict, meal: str | None = None, k: int = 4) -> list:
    """점수에 가장 크게 기여한 특징 (화면 설명용)"""
    w = load_model().get("weights") or {}
    f = [(w.get(x, 0.0), x) for x in set(meal_features(soup, main, side1, side2, meal))]
    f = [t for t in f if abs(t[0]) > 0.05]
    return [x for _, x in sorted(f, key=lambda t: -abs(t[0]))[:k]]
