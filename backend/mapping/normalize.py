# -*- coding: utf-8 -*-
"""② 이름 정리: 상품명 → 핵심 이름 + 속성,  식재료 → 이름 형태(검색어 사전) + 허용 상태·부위."""
import re
import unicodedata
from dataclasses import dataclass, field

from . import lexicon as L

_STATE_INDEX = sorted(((w, c) for c, ws in L.STATE_WORDS.items() for w in ws), key=lambda x: -len(x[0]))
_ANIMAL_INDEX = sorted(((w, a) for a, ws in L.ANIMALS.items() for w in ws), key=lambda x: -len(x[0]))
_PART_INDEX = {a: sorted(((w, p) for p, ws in parts.items() for w in ws), key=lambda x: -len(x[0]))
               for a, parts in L.PARTS.items()}
_SYN = [(k, v) for k, v in sorted(L.SYNONYMS.items(), key=lambda x: -len(x[0])) if k != v]
_NOISE = sorted(L.PREFIX_NOISE + L.BRANDS, key=len, reverse=True)
LEARNED = {"makers": set(), "brands": set()}          # mapping/vocab.py 가 월별 이력으로 배운 어휘


def set_learned(makers, brands):
    LEARNED["makers"] = set(makers or [])
    LEARNED["brands"] = set(brands or [])


def _load_learned():
    try:
        from .vocab import load
        v = load()
        set_learned(v.get("makers"), v.get("brand_prefixes"))
    except Exception:                                    # noqa: BLE001
        pass


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def canon(s: str) -> str:
    """공백 제거 + 같은 말 통일. 양쪽(상품·식재료)에 똑같이 쓴다."""
    s = re.sub(r"\s+", "", nfkc(s))
    for a, b in _SYN:
        if a in s and (b not in s or b in a):       # '숙주나물' → '숙주',  '새송이' → '새송이버섯'(이미 있으면 그대로)
            s = s.replace(a, b)
    return s


_ONE_CHAR_EXCLUDE = ("건강", "건더기", "건빵", "생강", "생선", "생크림", "생수", "채소", "통조림", "찐빵", "피자", "피클",
                     "피망", "알로에", "알룰로스", "편육", "링귀니")


def states_in(text: str) -> set:
    """글 속 상태 클래스. 한 글자 상태어(건·생·채·피·통…)는 단어 첫머리일 때만 센다."""
    found, t = set(), text
    for w, c in _STATE_INDEX:                    # 여러 글자 상태어 먼저 (긴 것부터)
        if len(w) > 1 and w in t:
            found.add(c)
            t = t.replace(w, " ")
    for w in _ONE_CHAR_EXCLUDE:
        t = t.replace(w, " ")
    for w, c in _STATE_INDEX:
        if len(w) == 1 and re.search(r"(^|[\s(,/\[])" + re.escape(w) + r"(?=[가-힣)]|$)", t):
            found.add(c)
    if re.search(r"캔(?![가-힣])", t):           # '참치캔', '꽁치캔(…)'
        found.add("CANNED")
    return found


def strip_states(text: str, known: set | None = None) -> tuple[str, set]:
    """앞뒤에 붙은 상태어를 떼어 낸다: '다진마늘' → ('마늘', {CUT}),  '건미역' → ('미역', {DRIED}).
    한 글자 상태어는 남는 말이 known(알려진 식재료 이름)에 있을 때만 뗀다 ('생강' → '강' 방지)."""
    st, changed = set(), True
    while changed and len(text) > 1:
        changed = False
        for w, c in _STATE_INDEX:
            if len(text) - len(w) < 1:
                continue
            for rest in ((text[len(w):] if text.startswith(w) else None), (text[:-len(w)] if text.endswith(w) else None)):
                if rest is None:
                    continue
                if len(w) == 1 and (known is None or rest not in known):
                    continue
                if len(rest) < 1:
                    continue
                text, changed = rest, True
                st.add(c)
                break
            if changed:
                break
    return text, st


# ═════════════════════════════ 상품 ═════════════════════════════
@dataclass
class Product:
    supplier: str
    item_cd: str
    item_nm: str
    core: str                       # 핵심 이름 (브랜드·규격·괄호 제거, 같은 말 통일)
    attrs: str                      # 괄호 안·뒤 설명 (상태·용도·원산지)
    states: set = field(default_factory=set)
    animal: str | None = None
    part: str | None = None
    soft: bool = False              # 고령친화
    lcls: str = ""
    mcls: str = ""
    dcls: str = ""
    category_auto: bool = False     # 사조: 품목명으로 추정한 분류


def product_core(item_nm: str) -> tuple[str, str]:
    """'(C)깐단호박(상품,냉동,샐러드용,중국)' → ('깐단호박', '상품,냉동,샐러드용,중국')
       '전처리청양고추(국내산)어슷/A타입'      → ('청양고추', '국내산 어슷/A타입')
       '우유(매일) 매일유업'                  → ('우유', '매일 매일유업')"""
    s = nfkc(item_nm)
    while True:
        m = L.LEADING_PAREN.match(s)
        if not m:
            break
        s = s[m.end():]
    s = re.sub(r"^H(?=[가-힣])", "", s)                    # 'H돈육' (현대그린푸드 자체 표기)
    m = re.search(r"[(\[/_]", s)
    head, rest = (s[:m.start()], s[m.start():]) if m else (s, "")
    m2 = re.match(r"\(([^()]*)\)([가-힣]{2,})", rest)      # '치자(알밥)단무지(…)' → 머리말은 '치자단무지'
    if m2 and len(m2.group(2)) >= 3 and not re.search(r"산$|국내|국산|수입|한우|한돈|[/,]", m2.group(1)):
        head, rest = head + m2.group(2), "(" + m2.group(1) + ")" + rest[m2.end():]
    if " " in head.strip():                               # '백설 박력밀가루' → '박력밀가루',  '오징어 너겟' → '오징어너겟'
        toks = [t for t in head.split() if t]
        keep = [t for t in toks if t not in L.BRANDS and t not in LEARNED["makers"]
                and not re.search(r"(식품|유업|제당|제일제당|푸드|산업|상사|\(주\)|주식회사)$", t)]
        head = "".join(keep or toks)
    head = head.strip()
    if "-" in head:                                       # '충청미-현대서산간척지쌀' → '현대서산간척지쌀'
        head = head.split("-")[-1] or head
    for _ in range(3):                                    # 붙여 쓴 브랜드·인증 접두어
        for w in _NOISE:
            if head.startswith(w) and len(head) > len(w) + 1:
                head = head[len(w):]
                break
    head = re.sub(r"[A-Za-z0-9.%+\-]+$", "", head)        # '양조간장701' '진간장S'
    head = re.sub(r"^[0-9.]+(배|단|호|번|kg|g|ml|l)?(?=[가-힣])", "", head, flags=re.I)   # '2배사과식초' → '사과식초'
    attrs = re.sub(r"[()\[\]]", " ", rest).strip()
    return canon(head), attrs


def parse_product(r: dict) -> Product:
    core, attrs = product_core(r.get("item_nm"))
    full = canon(r.get("item_nm"))
    st = states_in(nfkc(r.get("item_nm")) + " " + nfkc(r.get("spec")))
    animal, part = meat_of(core, attrs + " " + nfkc(r.get("spec")), mcls=r.get("mcls_nm") or "")
    return Product(
        supplier=r.get("supplier"), item_cd=str(r.get("item_cd")), item_nm=nfkc(r.get("item_nm")),
        core=core, attrs=attrs, states=st, animal=animal, part=part,
        soft=any(t in full for t in L.SOFT_TAGS),
        lcls=nfkc(r.get("lcls_nm")), mcls=nfkc(r.get("mcls_nm")), dcls=canon(r.get("dcls_nm")),
        category_auto=nfkc(r.get("scls_nm")) == "자동분류",
    )


MEAT_MCLS = {"돈육": "pork", "우육": "beef", "계육": "chicken", "양육": "lamb"}


def meat_of(core: str, attrs: str, mcls: str = "") -> tuple[str | None, str | None]:
    """(동물, 부위). 상품: '돈목살' → (pork, 목심),  '닭(Skin-Off)(가슴살,…)' → (chicken, 가슴)."""
    animal = None
    attrs = re.sub(r"뼈(포함|없는부위|없는것|제거)", " ", attrs)
    for w, a in _ANIMAL_INDEX:
        if not core.startswith(w):
            continue
        rest = core[len(w):]
        # 한 글자 접두어(돈·우)는 뒤가 부위일 때만: '우양지' O, '우유'·'우동' X / '돈목살' O, '돈가스' X
        if len(w) == 1 and w != "닭" and not any(rest.startswith(pw) for pw, _ in _PART_INDEX.get(a, [])):
            continue
        animal = a
        break
    if animal is None and mcls in MEAT_MCLS:
        animal = MEAT_MCLS[mcls]
    if animal is None:
        return None, None
    text = re.sub(r"[가-힣]+제거", " ", core + " " + attrs)       # '날개끝제거' 의 '날개'는 부위가 아님
    for w, p in _PART_INDEX.get(animal, []):
        if w in text and not (p == "살코기" and w in ("닭",)):
            return animal, p
    if animal == "chicken" and re.fullmatch(r"(닭|영계)", core) and not re.search(r"닭발|근위|모래|똥집|껍질|간\b|목뼈|발", attrs):
        return animal, "살코기"
    return animal, None


# ═════════════════════════════ 식재료 ═════════════════════════════
@dataclass
class Ingredient:
    ingredient_id: str
    rep_name: str
    names: list
    food_code: str | None
    mfds_name: str | None
    food_group: str
    discard_pct: float
    usage_g: float
    rank: int
    forms_primary: set = field(default_factory=set)     # 대표 이름과 같은 바탕의 이름 형태
    forms_secondary: set = field(default_factory=set)   # 같은 코드의 다른 이름 (두반장 ⊂ 굴소스 코드 등)
    qualifiers: set = field(default_factory=set)        # 괄호 속 수식어 (박력분, 황색, 다진것 …)
    states: set = field(default_factory=set)            # 허용 상태 클래스
    required_state: set = field(default_factory=set)    # 식약처 식품명이 정한 상태 (말린것·삶은것 …)
    animal: str | None = None
    parts_primary: set = field(default_factory=set)
    parts_secondary: set = field(default_factory=set)
    not_product: bool = False
    code_raw: bool = False                                # 식약처 식품명이 '생것'
    minced: bool = False                                  # 육류 '다진것' — 다짐육·분쇄 상품이면 부위 무관


def _split_name(n: str) -> tuple[str, list]:
    """'마늘(다진것_양념장)' → ('마늘', ['다진것', '양념장'])"""
    n = nfkc(n)
    m = re.match(r"^([^()]+)\((.*)\)\s*$", n)
    if not m:
        return canon(n), []
    quals = [canon(q) for q in re.split(r"[_,/]", m.group(2)) if q.strip()]
    return canon(m.group(1)), quals


_USE_QUAL = re.compile(r"(용|재료|양념장?|소스|드레싱|육수|토핑|고명|곁들임|데코|장식|밑간|필링|반죽|속|부재료)$")


_STATE_PREFIX = {"말린것": ["건", "말린"], "말린": ["건", "말린"], "삶은것": ["삶은", "데친", "자숙"], "데친것": ["데친"],
                 "볶은것": ["볶은"], "구운것": ["구운"], "다진것": ["다진"], "냉동": ["냉동"], "깐것": ["깐"],
                 "훈제": ["훈제"], "절인것": ["절임", "절인"], "염절임": ["절임"]}


def _forms(base: str, quals: list) -> set:
    out = {base}
    for q in quals:
        for pre in _STATE_PREFIX.get(q, []):                 # 레시피 '(말린것)' ↔ 상품 '건…'
            out.add(pre + base)
        if q == "통조림":                                    # 레시피 '(통조림)' ↔ 상품 '…캔'
            out.add(base + "캔")
        if not q or _USE_QUAL.search(q) or len(q) > 8:
            continue
        q2 = re.sub(r"(것|분|색)$", "", q) or q
        for qq in {q, q2}:
            out.add(qq + base)
            out.add(base + qq)
    b2, st = strip_states(base)         # 여러 글자 상태어만 (다진마늘 → 마늘). 훈제·삶은 같은 상태는 떼지 않는다
    if len(b2) >= 2 and not (st & L.HARD_STATES):
        out.add(b2)
    return {f for f in out if len(f) >= 1}


def is_not_product(rep_name: str, food_code) -> bool:
    if food_code and str(food_code) not in ("", "nan", "None"):
        return False
    n = canon(rep_name)
    if any(e in n for e in L.NOT_PRODUCT_EXCEPT):
        return False
    return any(re.search(p, n) for p in L.NOT_PRODUCT_PATTERNS)


def parse_ingredient(row: dict) -> Ingredient:
    rep = nfkc(row.get("대표 원재료명"))
    names = [nfkc(x) for x in str(row.get("레시피 원재료명(같은 코드)") or rep).split("|")]
    names = [x for x in names if x and not re.fullmatch(r"[\d.]+", x)]          # '247.7' 같은 잘못된 값
    if rep not in names:
        names.insert(0, rep)
    mfds = nfkc(row.get("식약처 식품명")) if str(row.get("식약처 식품명") or "") not in ("", "nan", "None") else None
    rep_base, _ = _split_name(rep)
    rep_base_core, _ = strip_states(rep_base)

    ing = Ingredient(
        ingredient_id=str(row["식재료ID"]), rep_name=rep, names=names,
        food_code=(str(row.get("식품코드")) if str(row.get("식품코드") or "") not in ("", "nan", "None") else None),
        mfds_name=mfds, food_group=nfkc(row.get("식품대분류")) or "미분류",
        discard_pct=_f(row.get("폐기율(%)")), usage_g=_f(row.get("사용량_g(레시피 합)")), rank=int(row.get("순위") or 0),
    )
    for n in names:
        base, quals = _split_name(n)
        forms = _forms(base, quals)
        base_core, _ = strip_states(base)
        primary = base in (rep_base, rep_base_core) or base_core in (rep_base, rep_base_core) or n == rep
        # 같은 코드 이름이 대표 이름으로 끝나면 대표 이름 수준 (황금팽이버섯·양조식초·왕만두 — 뒤가 중심)
        if not primary and len(rep_base) >= 2 and base.endswith(rep_base) and not (states_in(base) & L.HARD_STATES):
            primary = True
        (ing.forms_primary if primary else ing.forms_secondary).update(forms)
        ing.qualifiers.update(q for q in quals if q)
        st = states_in(" ".join([base] + [q for q in quals if not _USE_QUAL.search(q)]))
        if primary:
            ing.states |= st or {"RAW"}
    # 식약처 식품명: '멥쌀_백미_생것', '국수_소면_말린것', '돼지고기_목심(목심살)_생것'
    if mfds:
        toks = [canon(t) for t in re.split(r"[_]", mfds) if t.strip()]
        toks = [re.sub(r"\(.*?\)", "", t) or t for t in toks]
        for t in toks:
            st = states_in(t)
            if st & L.HARD_STATES and t in ("말린것", "삶은것", "데친것", "찐것", "구운것", "통조림", "분말화한것",
                                              "기름담금통조림", "말린것을삶은것", "얼린것", "볶은것", "훈제"):
                ing.required_state |= st & L.HARD_STATES
        if toks:
            # '고추_청양고추' '호박_애호박' '파_대파' → 품종 이름만 (속 이름 '고추'는 여러 식재료가 공유하므로 빼기)
            # '멥쌀_백미' '마늘_구근' '양조간장' → 첫 단어
            t0 = toks[0]
            t1 = toks[1] if len(toks) > 1 and not states_in(toks[1]) else ""
            secondary_now = {f for f in ing.forms_secondary}
            if t1 and t0 in t1 and t1 not in secondary_now:
                ing.forms_primary.add(t1)
            elif len(t0) >= 2 and not re.search(r"류$", t0) and t0 not in secondary_now:
                ing.forms_primary.add(t0)               # 같은코드 이름에 이미 있으면(국간장의 '간장') 그대로 둔다
            if t1 and t0 not in t1 and 2 <= len(t1) <= 3 and not re.search(r"\d", t1):
                ing.forms_primary.add(t1 + t0)          # '전분_감자' → '감자전분', '고추_빨간색' 같은 조합은 무해
    # 대표 이름 괄호의 상태(통조림·말린것·삶은것)는 그 식재료의 필수 상태 (꽁치(통조림) ≠ 냉동 꽁치)
    rep_hard = set()
    for q in _split_name(rep)[1]:
        if not _USE_QUAL.search(q):
            rep_hard |= states_in(q) & L.HARD_STATES
    if rep_hard:
        ing.required_state = rep_hard               # 식약처 식품명과 다르면 대표 이름을 따른다
    # 식약처 식품명이 '생것'이면 그 코드는 생것: 같은 바탕 이름에 말린것·삶은것이 섞여 있어도 허용하지 않는다 (건미역 ≠ 생미역)
    if mfds and "생것" in mfds and not rep_hard:
        rep_hard = states_in(rep) & L.HARD_STATES
        ing.states = {s for s in ing.states if s not in L.HARD_STATES} | rep_hard
        ing.code_raw = True
    ing.forms_primary |= {canon(x) for x in L.EXTRA_FORMS.get(rep, [])}
    # 생선 이름 끝 '어'는 상품명에서 흔히 빠진다: 임연수어 → 임연수 (세 글자 이하는 그대로: 고등어·오징어·연어)
    if ing.food_group == "어패류 및 기타 수산물":
        ing.forms_primary |= {f[:-1] for f in ing.forms_primary if len(f) >= 4 and f.endswith("어")}
    ing.states |= ing.required_state
    ing.forms_secondary -= ing.forms_primary
    ing.forms_primary = {f for f in ing.forms_primary if f and not re.search(r"\d", f)}
    ing.forms_secondary = {f for f in ing.forms_secondary if f and not re.search(r"\d", f)}

    # 육류: 대표 이름이 동물 이름(괄호 앞)일 때만. 부위는 대표 이름 괄호 > 식약처 식품명 순.
    animal = L.ANIMAL_BASES.get(rep_base) or L.ANIMAL_BASES.get(rep_base_core)
    if animal:
        ing.animal = animal
        ing.required_state |= strip_states(rep_base)[1] & L.HARD_STATES      # 훈제오리 → 훈제(조리) 필요
        _, rep_quals = _split_name(rep)
        part = None
        for q in rep_quals:
            q = re.sub(r"뼈(포함|없는부위|없는것|제거)", "", q)
            if not q or _USE_QUAL.search(q):
                continue
            hit = next((pp for w, pp in _PART_INDEX.get(animal, []) if w in q), None)
            if hit:
                part = hit
                break
            st = states_in(q)
            if st & L.HARD_STATES:
                ing.required_state |= st & L.HARD_STATES
                continue
            if st:
                continue
            part = "?" + q                                  # 모르는 부위(곱창·잡뼈·족발 …) → 상품과 맞추지 않음
            break
        if part is None and mfds:
            inner = " ".join(re.findall(r"\(([^)]*)\)", mfds))          # '등심(살치살)' → 살치살 먼저
            _, part = meat_of(canon(mfds.split("_")[0]), inner)
            if part is None:
                _, part = meat_of(canon(mfds.split("_")[0]), mfds)
        if any(q in ("다진것", "간것", "갈은것", "다짐육") for q in rep_quals):
            ing.minced = True                               # 쇠고기(다진것) 코드가 '안심'이어도 다짐육이면 같은 재료
        ing.parts_primary = {part or "살코기"}
        for n in names:
            b, qs = _split_name(n)
            if L.ANIMAL_BASES.get(b) == animal:
                _, p3 = meat_of(b, " ".join(qs))
                if p3:
                    ing.parts_secondary.add(p3)
        ing.parts_secondary -= ing.parts_primary
        ing.states |= ing.required_state
    ing.not_product = is_not_product(rep, ing.food_code)
    return ing


def _f(v) -> float:
    try:
        x = float(v)
        return 0.0 if x != x else x
    except (TypeError, ValueError):
        return 0.0


_load_learned()
