# -*- coding: utf-8 -*-
"""④-1 특징 계산: 후보 쌍(식재료, 상품)마다 판정 근거를 만든다. 결과는 features JSON 으로 그대로 저장된다."""
import re

from . import lexicon as L
from .normalize import Ingredient, Product

_NOISE = sorted(set(L.PREFIX_NOISE + L.BRANDS), key=len, reverse=True)
_PROC = sorted(L.PROCESSED_TOKENS, key=len, reverse=True)
REL_RANK = {"exact": 3, "suffix": 2, "prefix": 1}


def _qual_words(ing: Ingredient) -> set:
    out = set()
    for q in ing.qualifiers:
        if re.search(r"(용|재료|양념|소스|드레싱|육수|토핑|고명|곁들임|데코|장식|밑간|필링|반죽)$", q):
            continue
        out.add(q)
        q2 = re.sub(r"(것|분|색)$", "", q)
        if q2:
            out.add(q2)
    return out


def explain(extra: str, ing: Ingredient, side: str) -> dict:
    """상품 이름에서 식재료 이름을 뺀 나머지(extra)를 풀이한다.
    side='front': 앞에 붙은 말(품종·상태·브랜드),  side='back': 뒤에 붙은 말(상태 또는 가공품)."""
    from .normalize import LEARNED
    quals = _qual_words(ing)
    words = quals | set(_NOISE) | (LEARNED["brands"] if side == "front" else set())
    vocab = [(w, None) for w in words] + [(w, c) for c, ws in L.STATE_WORDS.items() for w in ws]
    vocab.sort(key=lambda x: -len(x[0]))
    left, states, used = extra, set(), []
    for _ in range(10):                                  # 바깥쪽(식재료 이름에서 먼 쪽)부터 아는 말을 뗀다
        if not left:
            break
        hit = None
        for w, c in vocab:
            if (side == "front" and left.startswith(w)) or (side == "back" and left.endswith(w)):
                hit = (w, c)
                break
        if hit is None:
            # 앞에 붙은 말은 식재료 이름 쪽(끝)에서도 상태어를 뗀다: '전처리|채|' 같은 경우
            for w, c in vocab:
                if (side == "front" and left.endswith(w)) or (side == "back" and left.startswith(w)):
                    hit = (w, c)
                    break
            if hit is None:
                break
            w, c = hit
            left = left[:-len(w)] if side == "front" else left[len(w):]
        else:
            w, c = hit
            left = left[len(w):] if side == "front" else left[:-len(w)]
        used.append(w)
        if c:
            states.add(c)
    processed = None
    if left:
        for t in _PROC:
            if t in left:
                processed = t
                break
        if processed is None and side == "back" and (left in L.PROCESSED_SUFFIX_1 or left[-1:] in L.PROCESSED_SUFFIX_1 and len(left) <= 2):
            processed = left
    return {"leftover": left, "states": states, "used": used, "processed": processed}


def _state_check(p: Product, ing: Ingredient, extra_states: set) -> tuple[bool, str]:
    pst = (p.states | extra_states) & L.HARD_STATES
    allowed = ing.states & L.HARD_STATES
    bad = pst - allowed
    if bad:
        return False, f"상품 상태 {sorted(bad)} ∉ 식재료 허용 {sorted(allowed) or ['생']}"
    need = ing.required_state - {"DRIED", "POWDER"}          # 조리·통조림·절임은 상품에도 있어야 (말린 것은 표기 생략이 많음)
    if need and not (pst & need):
        return False, f"식재료는 {sorted(need)}인데 상품에 그 표시 없음"
    if "POWDER" in ing.required_state and "POWDER" not in pst and not re.search(r"가루|분말|믹스|파우더|분$", p.core):
        return False, "식재료는 가루인데 상품은 가루가 아님"
    if "DRIED" in ing.required_state and "생" in p.item_nm and "DRIED" not in pst:
        return False, "식재료는 말린 것인데 상품은 생것"
    return True, ""


def _meat(p: Product, ing: Ingredient) -> dict:
    f = {"rel": "meat", "animal_match": p.animal == ing.animal}
    if not f["animal_match"]:
        f.update(part_match="animal_conflict")
        return f
    minced_prod = any(w in p.item_nm for w in ("다짐육", "분쇄", "다짐", "민찌"))
    if ing.minced and minced_prod and p.part not in ("지방", "등뼈", "뼈"):
        f["part_match"] = "primary"
        f["minced"] = True
    elif p.part is None:
        f["part_match"] = "unknown"
    elif p.part in ing.parts_primary:
        f["part_match"] = "primary"
    elif p.part in ing.parts_secondary:
        f["part_match"] = "secondary"
    else:
        f["part_match"] = "conflict"
    # 핵심 이름에 육류 외 가공 표지 (돼지고기김치찌개, 닭가슴살소시지 …)
    rest = p.core
    for w in sorted(sum(L.ANIMALS.values(), []), key=len, reverse=True):
        if rest.startswith(w):
            rest = rest[len(w):]
            break
    for ws in L.PARTS.get(p.animal, {}).values():
        for w in sorted(ws, key=len, reverse=True):
            rest = rest.replace(w, "")
    proc = next((t for t in _PROC if t in rest), None)
    if proc:
        f["processed"] = proc
    return f


def pair_features(p: Product, ing: Ingredient, cand: dict, fidx, ki: int, owner_len: int) -> dict:
    """cand = candidates.candidate_pairs 의 값 {'sim', 'hits'}.  owner_len = 이 상품에서 가장 긴 끝맺음 형태 길이(모든 식재료 중)."""
    f = {"sim": round(cand.get("sim", 0.0), 3)}
    if p.animal and ing.animal:
        f.update(_meat(p, ing))
        ok, why = _state_check(p, ing, set())
        f["state_ok"], f["state_why"] = ok, why
        f["processed_ok"] = not f.get("processed")
        return f
    if p.animal and not ing.animal and ing.food_group == "육류":
        f["rel"] = "meat_unparsed"

    hits = cand.get("hits") or []
    if hits:
        rel, form, tier = max(hits, key=lambda h: (REL_RANK[h[0]], h[2] == "P", len(h[1])))
        others_p = fidx.p_owners.get(form, set()) - {ki} - (fidx.co.get(form, set()) if ki in fidx.co.get(form, set()) else set())
        f.update(rel=rel, form=form, tier=tier, form_shared=(tier == "P" and bool(others_p)))
        f["owned_elsewhere"] = tier == "S" and bool(others_p)     # 다른 식재료의 대표 이름 (홍고추 코드의 '청양고추')
        f["outranked"] = (rel == "suffix" and owner_len > len(form)) or (rel == "prefix" and owner_len >= 2)
        if rel == "suffix":
            ex = explain(p.core[:-len(form)], ing, "front")
        elif rel == "prefix":
            ex = explain(p.core[len(form):], ing, "back")
        else:
            ex = {"leftover": "", "states": set(), "used": [], "processed": None}
        f["extra"] = p.core.replace(form, "", 1) if rel != "exact" else ""
        f["leftover"] = ex["leftover"]
        f["extra_used"] = ex["used"]
        if rel == "prefix" and ex["leftover"]:
            f["processed"] = ex["processed"] or f"뒤에 '{ex['leftover']}'"
        elif rel == "suffix" and ex["processed"]:
            f["processed"] = ex["processed"]
        extra_states = ex["states"]
    elif p.dcls and p.dcls in ing.forms_primary and not any(t in p.core for t in _PROC):
        # 이름은 안 맞지만 공급사 세분류가 식재료 이름과 같다 ('충청미-…쌀' 세분류=쌀)
        others_p = fidx.p_owners.get(p.dcls, set()) - {ki}
        f.update(rel="dcls", form=p.dcls, tier="P", form_shared=bool(others_p), owned_elsewhere=False,
                 outranked=owner_len > 0, extra="", leftover=p.core, extra_used=[])
        extra_states = set()
    else:
        f.update(rel=f.get("rel") or "fuzzy", form=None, tier=None, form_shared=False, owned_elsewhere=False,
                 outranked=False, extra="", leftover="", extra_used=[])
        extra_states = set()
        if owner_len > 0:
            f["outranked"] = True                          # 다른 식재료가 이 상품 이름과 맞는다
    ap = next((t for t in L.ATTR_PROCESSED if t in p.item_nm and t not in ing.rep_name
               and not any(t in n for n in ing.names[:20])
               and not (t in ("초밥용", "조미유부") and "조미된" in ing.rep_name)), None)
    if ap:
        f["processed"] = f.get("processed") or ap
    if ing.food_group in L.RAW_FOOD_GROUPS and p.mcls in L.FLAVOR_MCLS and not ing.not_product \
            and (not p.category_auto or f.get("rel") != "exact"):    # 사조 자동분류는 틀릴 수 있어 이름이 정확히 같으면 봐줌
        f["processed"] = f.get("processed") or f"{p.mcls} 상품(맛)"
    mix_text = re.sub(r"품종\s*:\s*[^,)]*", "", p.item_nm)          # '(품종:혼합)' 은 쌀 품종 블렌드 — 섞은 상품 아님
    if any(m in mix_text for m in L.MIXED_MARKERS) and not any(m in ing.rep_name for m in L.MIXED_MARKERS):
        f["processed"] = f.get("processed") or "혼합 상품"
    if "간편식" in p.item_nm and "시판" not in ing.rep_name and ing.food_group != "미분류":
        f["ready_meal"] = True                              # (간편식) 표시: 조리·조미된 완제품일 가능성 → 검수
    front = f.get("extra") if f.get("rel") == "suffix" else (f.get("leftover") or "")
    raw = front or ""
    for w in sorted(set(_NOISE) | {x for ws in L.STATE_WORDS.values() for x in ws if len(x) > 1}, key=len, reverse=True):
        raw = raw.replace(w, "")
    animal_marks = {"돼지", "닭", "오리", "한우"}            # 동물 표시는 앞머리일 때만 ('회오리감자'의 '오리' 제외)
    f["variety"] = next((m for m in L.VARIETY_MARKERS + L.FLAVOR_MARKERS
                         if (raw.startswith(m) if m in animal_marks else m in raw)
                         and m not in ing.rep_name and not any(m in q for q in ing.qualifiers)), None)
    ok, why = _state_check(p, ing, extra_states)
    f["state_ok"], f["state_why"] = ok, why
    f["processed_ok"] = not f.get("processed")
    f["dcls"] = p.dcls or None
    f["dcls_match"] = bool(p.dcls) and (p.dcls in ing.forms_primary)
    return f
