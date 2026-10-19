"""
meal_form.py  ─  식사형태 규칙 (2026-10-19)
==========================================
일반식(시설 공통) → 어르신 식사형태에 맞게 칸을 바꿉니다. (대체찬 2개 한도와 별개)

  ① 죽식 어르신  : 아침 = 흰죽 / 점심·저녁 = 영양죽
                   영양죽은 '일반식에서 쓰고 남은 재고'의 핵심재료를 가장 많이 쓰는 죽을 고름
                   (유통기한 가까운 재고 우선, 최근 4끼에 나온 죽은 피함, 재고 없으면 순환)
  ② 매운 음식 불가: 김치 칸 → 백김치  (고령자.xlsx '매운음식' 열 = X)

[출력]
  overrides : {"이름||일차||끼니": {"밥": "흰죽", "김치": "백김치"}}
  items     : {"흰죽": 메뉴dict, ...}  (serving_agent가 sub_products로 조회)
  porridge  : [{"일차","끼니","죽","사용 재고"}]  (주방용 죽 계획)
"""
import numpy as np
from .extra_recipes import load_extra_recipes, WHITE_PORRIDGE, WHITE_KIMCHI
from .inventory import _match, PLAN_DAYS

PORRIDGE_NO_REPEAT = 4   # 최근 4끼(이틀) 안에 나온 영양죽은 다시 고르지 않음

SLOT_CATS = [("밥", "밥"), ("국", "국"), ("주찬", "주찬"), ("부찬1", "부찬"), ("부찬2", "부찬"), ("김치", "김치")]


def _day_no(label) -> int:
    d = "".join(ch for ch in str(label) if ch.isdigit())
    return int(d) if d else 1


def plan_porridge(records: list, n_juk: int, inv_model=None) -> dict:
    """{(일차, 끼니): (죽 이름, 사용 재고 목록)} — 점심·저녁 영양죽 계획 (시설 단위, 같은 끼니는 같은 죽)"""
    extra = load_extra_recipes()
    options = [m for m in extra["죽"] if m["menu_name"] != WHITE_PORRIDGE]
    plan = {}
    if not options:
        return plan

    remain = exp_idx = w = None
    if inv_model is not None:
        U = inv_model.daily_usage_records(records, SLOT_CATS)
        cum = np.cumsum(U, axis=0)                       # 일반식 누적 사용량
        remain_by_day = inv_model.stock[None, :] - cum   # d일 저녁까지 쓰고 남은 양
        remain = np.maximum(remain_by_day, 0)
        exp_idx, w = inv_model.exp_idx, inv_model.w
        used_juk = np.zeros(len(inv_model.names))

    recent, rot = [], 0
    for r in sorted(records, key=lambda x: (_day_no(x["일차"]), {"아침": 0, "점심": 1, "저녁": 2}.get(x["끼니"], 9))):
        if r["끼니"] == "아침":
            continue
        d = _day_no(r["일차"]) - 1
        best, best_score, best_use = None, 0.0, {}
        if remain is not None and 0 <= d < PLAN_DAYS:
            for m in options:
                if m["menu_name"] in recent:
                    continue
                score, use = 0.0, {}
                for k, inv in enumerate(inv_model.names):
                    if d >= exp_idx[k]:
                        continue                                   # 유통기한 지남
                    need = sum(g for nm, g in m["ingredients"].items()
                               if nm in m["key_ingredients"] and _match(inv, nm)) * n_juk
                    left = remain[d, k] - used_juk[k]
                    if need > 0 and left >= need:
                        score += w[k] * need
                        use[inv] = need
                if score > best_score:
                    best, best_score, best_use = m, score, use
        if best is None:                                           # 남는 재고 없음 → 순환
            cand = [m for m in options if m["menu_name"] not in recent] or options
            best = cand[rot % len(cand)]; rot += 1; best_use = {}
        else:
            for inv, g in best_use.items():
                used_juk[inv_model.names.index(inv)] += g
        plan[(r["일차"], r["끼니"])] = (best["menu_name"], best_use)
        recent = (recent + [best["menu_name"]])[-PORRIDGE_NO_REPEAT:]
    return plan


def build_meal_form(records: list, patients: list, inv_model=None) -> dict:
    extra = load_extra_recipes()
    items = {m["menu_name"]: m for ms in extra.values() for m in ms}
    juk = [p for p in patients if p.meal_texture_rice == "죽"]
    plan = plan_porridge(records, len(juk), inv_model) if juk else {}
    overrides = {}
    for p in patients:
        for r in records:
            ch = {}
            if p.meal_texture_rice == "죽" and WHITE_PORRIDGE in items:
                ch["밥"] = WHITE_PORRIDGE if r["끼니"] == "아침" else plan.get((r["일차"], r["끼니"]), (WHITE_PORRIDGE, {}))[0]
            if getattr(p, "no_spicy", False) and WHITE_KIMCHI in items and str(r.get("김치", "")).strip():
                ch["김치"] = WHITE_KIMCHI
            if ch:
                overrides[f"{p.name}||{r['일차']}||{r['끼니']}"] = ch
    porridge = [{"일차": d, "끼니": m, "죽": name, "사용 재고": ", ".join(f"{k} {v/1000:.1f}kg" for k, v in use.items()) or "-"}
                for (d, m), (name, use) in plan.items()]
    print(f"  [식사형태] 죽식 {len(juk)}명 · 백김치 {sum(getattr(p, 'no_spicy', False) for p in patients)}명 "
          f"· 영양죽 계획 {len(plan)}끼")
    return {"overrides": overrides, "items": items, "porridge": porridge}
