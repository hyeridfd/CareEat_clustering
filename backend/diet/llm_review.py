# -*- coding: utf-8 -*-
"""AI 식단 검토자 — 선택된 28일 식단을 LLM 이 영양사처럼 읽고 어색한 칸을 짚어 교체를 제안, 코드가 검증해 반영

  최적화·조화 모델이 수치로 잘 못 보는 것:
    한 끼 안에서 주재료·조리법·양념이 겹치는 조합, 같은 끼니 튀김·전 여러 개(조리 부담),
    계절에 안 맞는 메뉴, 색·식감이 단조로운 상차림, 다진찬 어르신이 많은데 질긴 반찬,
    이틀 연속 비슷한 주찬(같은 주재료·조리법)

  흐름
    1) 식단 읽기     meal_lines()  84끼를 한 줄씩 + 코드가 미리 계산한 표시(튀김 수, 겹치는 주재료, 조화 낮음, 다진찬 부적합)
    2) 후보 메뉴     menu_catalog()  국·주찬·부찬 후보 이름과 간단한 속성 (교체는 이 목록 안에서만)
    3) LLM 제안      문제 칸 + 바꿀 메뉴 + 이유 (최대 10개)
    4) 코드 검증     apply_suggestions()  하나씩:
                       후보 목록에 있는 메뉴인지 · 같은 분류인지 · 한 그릇 음식 여부가 같은지 ·
                       앞뒤 3일(9끼) 안에 같은 메뉴가 없는지 ·
                       f1 영양이 0.3 을 넘지 않고 f1·f3·f4 가 각각 TOL 이상 나빠지지 않는지
                     통과한 제안만 순서대로 반영 (반영할 때마다 다시 계산)
                     · 급원 보존: 칼슘 급원 반찬(1회 100mg 이상)이나 단백질 반찬(5g 이상)을 그렇지 않은 메뉴로 바꾸려 하면
                       코드가 같은 분류에서 '같은 급원 + (질감 문제면) 부드러운 메뉴' 중 f1·f3·f4 가 가장 덜 나빠지는 메뉴를 대신 고른다
                     · 검토 전체 누적으로도 f1·f3 이 CUM_TOL 넘게 나빠지면 그 뒤 제안은 거절
    5) 기록          반영·거절 목록과 사유, 반영 전후 f1~f4 → 화면에서 확인·되돌리기
  호출 실패·미설정이면 식단을 그대로 둔다 (검토 없음으로 기록).
"""
from __future__ import annotations

import json
import re
import time

import numpy as np

from . import llm_select as LS

PROMPT_VERSION = "2026-11-09-review3"
MAX_SUGGESTIONS = 10
TOL = {"f1": 0.01, "f3": 0.01, "f4": 0.01}      # 제안 1건이 나빠지게 해도 되는 최대치
CUM_TOL = {"f1": 0.01, "f3": 0.01}              # 검토 전체 누적으로 나빠지게 해도 되는 최대치
CA_SOURCE = 100.0        # 칼슘 급원 반찬 기준 (1회 제공량 mg) — 세 요양원 식단 DB 의 메뉴별 칼슘값
PROTEIN_SOURCE = 5.0     # 단백질 반찬 기준 (1회 g)
KEEP_RATIO = 0.6         # 바꾼 메뉴가 원래 급원량의 이 비율 이상이면 '같은 급원'으로 인정
SCORE_W = {"f1": 1.0, "f3": 1.0, "f4": 1.0}     # 대체 메뉴 고를 때 점수 변화 가중치
MAX_SAME_ING = 2         # 검토 한 번에 같은 주재료로 바꾸는 건 최대 2번 (예: 브로콜리 메뉴로 4번 바꾸는 쏠림 방지)
ING_WINDOW = 3           # 바꾼 메뉴와 같은 주재료가 앞뒤 3끼 안에 있으면 거절
F1_PASS = 0.3
WINDOW = 9                                       # 앞뒤 9끼(3일) 안 같은 메뉴 금지
SLOTS = {"국": (1, "국"), "주찬": (2, "주찬"), "부찬1": (3, "부찬"), "부찬2": (4, "부찬")}
MEALS = ("아침", "점심", "저녁")
FRIED = ("튀김", "전")

SYSTEM_PROMPT = """당신은 요양원 급식을 20년 넘게 담당한 임상 영양사입니다.
최적화 프로그램이 만든 28일 공통 식단(84끼)을 검토합니다. 영양 수치는 프로그램이 이미 맞췄으니,
숫자로는 잡기 어려운, 현장 영양사의 눈에 어색한 점을 찾아 고칩니다.

찾을 것:
1. 한 끼 조합이 어색함 — 주재료·조리법·양념이 겹침(예: 두부조림 + 두부부침, 볶음 3개), 국과 반찬 맛이 충돌
2. 조리 부담 — 같은 끼니에 튀김·전 2개 이상, 하루에 튀김·전이 너무 많음
3. 계절에 안 맞음 — 시작 월·계절을 보고 판단 (예: 한겨울 냉국·냉채, 한여름 뜨겁고 무거운 찜이 연달아)
4. 단조로움 — 한 끼 반찬 색·식감이 모두 비슷함 (모두 갈색 조림 등)
5. 수용성 — 다진찬 인원이 많은데 질기거나 딱딱한 반찬(다진찬부적합 표시), 매운 양념이 한 끼에 몰림
6. 연속 끼니·다음 날 비슷함 — 주찬이 이틀 연속 같은 주재료·조리법

규칙:
- 교체 메뉴는 반드시 '후보_메뉴' 의 같은 분류(국/주찬/부찬) 목록에 있는 이름을 그대로 씁니다. 새 메뉴를 만들지 않습니다.
- 밥·김치는 바꾸지 않습니다. '한그릇' 표시가 있는 메뉴(덮밥·비빔밥·면 등)는 '한그릇' 메뉴로만 바꿉니다.
- 같은 끼니 앞뒤 3일 안에 이미 나오는 메뉴로 바꾸지 않습니다.
- 칼슘·단백질 급원 반찬(후보 목록의 '칼슘 Nmg', '단백질 Ng' 표시, 예: 멸치·건새우·두부·생선·달걀)을 바꿀 때는
  같은 급원이면서 부드러운 메뉴로 바꿉니다. 채소 나물로 바꾸면 칼슘·단백질이 빠집니다.
- 대체 메뉴의 주재료를 다양하게 고릅니다. 같은 재료(예: 브로콜리)로 여러 번 바꾸지 않습니다 (같은 주재료는 최대 2번).
- 확실히 나아지는 경우만 제안합니다. 사소한 취향 차이는 제안하지 않습니다. 최대 10개, 중요한 것부터.
- 영양 수치를 언급하거나 계산하지 않습니다 (영양은 프로그램이 다시 검사합니다).
- 반드시 아래 JSON 한 개만 출력합니다.

{"overall": "식단 전체에 대한 2~3문장 평가",
 "suggestions": [
   {"day": 3, "meal": "점심", "slot": "부찬2", "current": "지금 메뉴 이름", "replace_with": "후보 메뉴 이름",
    "type": "조합|조리부담|계절|단조로움|수용성|연속", "problem": "무엇이 문제인지 1문장", "why": "바꾸면 왜 나은지 1문장"}
 ]}"""


# ─────────────────────────── 1) 식단 읽기 ───────────────────────────
def _attr(problem, cat, i):
    h = problem.harmony
    if h is None:
        return {}
    try:
        return h.attrs[cat][i]
    except (AttributeError, KeyError, IndexError):
        return {}


def meal_lines(problem, chrom) -> list[str]:
    """84끼 → '3일 점심 | 국 … | 주찬 … | 부찬1 … | 부찬2 … | 표시: …' (표시는 코드가 계산한 사실만)"""
    from .problem import N_DAYS, N_SLOTS
    pool = problem.pool
    hs = problem.meal_harmony(chrom)
    out = []
    for d in range(N_DAYS):
        for mi, ml in enumerate(MEALS):
            idx = {s: int(chrom[d * N_SLOTS + mi * 6 + k]) % len(pool[cat]) for s, (k, cat) in SLOTS.items()}
            menus = {s: pool[SLOTS[s][1]][i] for s, i in idx.items()}
            attrs = {s: _attr(problem, SLOTS[s][1], i) for s, i in idx.items()}
            flags = []
            fried = [menus[s]["menu_name"] for s in ("주찬", "부찬1", "부찬2") if attrs[s].get("method") in FRIED]
            if len(fried) >= 2:
                flags.append(f"튀김·전 {len(fried)}개")
            ing = {}
            for s, a in attrs.items():
                if a.get("main_ingredient"):
                    ing.setdefault(a["main_ingredient"], []).append(s)
            flags += [f"주재료 겹침({k}: {'·'.join(v)})" for k, v in ing.items() if len(v) >= 2]
            meth = [attrs[s].get("method") for s in ("주찬", "부찬1", "부찬2")]
            if meth[0] and len(set(meth)) == 1:
                flags.append(f"조리법 모두 {meth[0]}")
            spicy = sum(1 for a in attrs.values() if a.get("season") == "매운양념")
            if spicy >= 3:
                flags.append(f"매운 양념 {spicy}칸")
            tex = [menus[s]["menu_name"] for s in ("주찬", "부찬1", "부찬2") if menus[s].get("texture") == "부적합"]
            if tex:
                flags.append("다진찬 부적합: " + "·".join(tex))
            if hs is not None and hs[d * 3 + mi] < 0.4:
                flags.append(f"조화 낮음 {hs[d * 3 + mi]:.2f}")
            one = [s for s in SLOTS if menus[s].get("one_dish")]
            names = " | ".join(f"{s} {menus[s]['menu_name']}{'(한그릇)' if s in one else ''}" for s in SLOTS)
            out.append(f"{d + 1}일 {ml} | {names}" + (f" | 표시: {', '.join(flags)}" if flags else ""))
    return out


# 메뉴별 칼슘(mg) — 후보 풀은 세 요양원 식단 DB(정성노인·포천·은화케어) 메뉴로 만들어져 이름이 그대로 맞는다
_CA = None


CA_KEYWORDS = ("멸치", "건새우", "뱅어")   # DB 칼슘값이 비정상적으로 낮게 들어간 메뉴가 있어(예: 멸치볶음 3.7mg) 이름으로 보완


def ca_value(m: dict) -> float:
    """급원 판단용 칼슘값: DB 값, 단 멸치·건새우·뱅어 반찬은 최소 CA_SOURCE 로 본다"""
    v = calcium(m["menu_name"]) or 0.0
    if any(k in m["menu_name"] for k in CA_KEYWORDS):
        v = max(v, CA_SOURCE)
    return v


def calcium(name: str):
    global _CA
    if _CA is None:
        import glob, os
        from .harmony import MODEL_JSON
        acc = {}
        for f in glob.glob(os.path.join(os.path.dirname(MODEL_JSON), "*_menus.json")):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for k, v in (d.get("menus") or {}).items():
                if (v or {}).get("ca") is not None:
                    acc.setdefault(k, []).append(float(v["ca"]))
        _CA = {k: sum(v) / len(v) for k, v in acc.items()}
    return _CA.get(name)


# ─────────────────────────── 2) 후보 메뉴 ───────────────────────────
def menu_catalog(problem) -> dict:
    """{분류: ["메뉴(조리법·주재료[·한그릇][·다진찬부적합])", …]} — 교체는 이 안에서만"""
    out = {}
    for cat in ("국", "주찬", "부찬"):
        rows = []
        for i, m in enumerate(problem.pool[cat]):
            a = _attr(problem, cat, i)
            tags = [x for x in (a.get("method"), a.get("main_ingredient") or a.get("main")) if x]
            if m.get("one_dish"):
                tags.append("한그릇")
            if m.get("texture") == "부적합":
                tags.append("다진찬부적합")
            ca = calcium(m["menu_name"])
            if ca_value(m) >= CA_SOURCE:
                tags.append(f"칼슘 {round(ca)}mg" if ca and ca >= CA_SOURCE else "칼슘 급원")
            if cat == "부찬" and (m.get("protein") or 0) >= PROTEIN_SOURCE:
                tags.append(f"단백질 {round(m['protein'], 1)}g")
            rows.append(f"{m['menu_name']}({'·'.join(tags)})" if tags else m["menu_name"])
        out[cat] = rows
    return out


def build_payload(problem, chrom, context: dict) -> dict:
    ctx = {k: context.get(k) for k in ("어르신_수", "질환_인원", "식사형태_인원", "다진찬_인원_합계", "죽_인원_합계",
                                       "매운음식_제한_인원", "시작_월", "계절") if k in context}
    return {"시설_상황": ctx, "식단": meal_lines(problem, chrom), "후보_메뉴": menu_catalog(problem),
            "참고": "표시는 프로그램이 계산한 사실입니다. 표시가 없어도 어색하면 제안할 수 있습니다."}


# ─────────────────────────── 4) 코드 검증 ───────────────────────────
def _name_index(problem):
    return {cat: {m["menu_name"]: i for i, m in enumerate(problem.pool[cat])} for cat in ("국", "주찬", "부찬")}


def _strip_tag(name: str) -> str:
    return re.sub(r"\(.*?\)$", "", str(name or "")).strip()


def _f(problem, chrom) -> dict:
    v = problem._eval_one(chrom)
    return {"f1": float(v[0]), "f2": float(v[1]), "f3": float(v[2]), "f4": float(v[3])}


def _need(old: dict, new: dict | None) -> dict | None:
    """원래 메뉴가 칼슘·단백질 급원인데 바꿀 메뉴가 그만큼 못 채우면 → 지켜야 할 급원 {"ca": 최소, "protein": 최소}"""
    need = {}
    oca = ca_value(old)
    if oca >= CA_SOURCE:
        nca = ca_value(new) if new else 0.0
        if nca < oca * KEEP_RATIO:
            need["ca"] = oca
    opr = old.get("protein") or 0.0
    if opr >= PROTEIN_SOURCE:
        npr = (new.get("protein") or 0.0) if new else 0.0
        if npr < opr * KEEP_RATIO:
            need["protein"] = opr
    return need or None


def _meets(m: dict, need: dict, floor: float) -> bool:
    """floor = 원래 급원량의 몇 % 이상이어야 하는지 (단계적으로 낮춤)"""
    if "ca" in need and ca_value(m) < max(CA_SOURCE, need["ca"] * floor):
        return False
    if "protein" in need and (m.get("protein") or 0.0) < max(PROTEIN_SOURCE * 0.6, need["protein"] * floor):
        return False
    return True


def _ing(problem, cat, j):
    a = _attr(problem, cat, j)
    return a.get("main_ingredient") or None


def best_alternative(problem, chrom, gi, cat, old, need, near, cur_f, soft: bool, ing_ok=None):
    """같은 분류에서 급원(need)을 지키고, (soft 면) 다진찬 적합이며, 반복·한그릇 조건을 통과하는 메뉴 중
    f1·f3·f4 가중 합이 가장 덜 나빠지는(가장 좋아지는) 메뉴 → (번호, 새 점수) 또는 None"""
    pool = problem.pool[cat]
    for floor in (KEEP_RATIO, 0.35, 0.0):                  # 원래 급원량 60% → 35% → 기준값만
        best = None
        for j, m in enumerate(pool):
            if m["menu_name"] == old["menu_name"] or m["menu_name"] in near:
                continue
            if bool(m.get("one_dish")) != bool(old.get("one_dish")):
                continue
            if soft and m.get("texture") != "적합":
                continue
            if not _meets(m, need, floor):
                continue
            if ing_ok and not ing_ok(j):
                continue
            trial = np.array(chrom, dtype=int).copy()
            trial[gi] = j
            f = _f(problem, trial)
            if any(f[x] - cur_f[x] > TOL[x] for x in TOL):
                continue
            score = sum(SCORE_W[x] * (f[x] - cur_f[x]) for x in SCORE_W)
            if best is None or score < best[0]:
                best = (score, j, f)
        if best:
            return best[1], best[2]
    return None


def apply_suggestions(problem, chrom, suggestions: list) -> tuple[np.ndarray, list, list]:
    """→ (반영한 염색체, 반영 목록, 거절 목록). 제안을 순서대로 하나씩 검사·반영"""
    from .problem import N_DAYS, N_SLOTS
    chrom = np.array(chrom, dtype=int).copy()
    pool, names = problem.pool, _name_index(problem)
    accepted, rejected = [], []
    cur_f = _f(problem, chrom)
    start_f = dict(cur_f)

    used_ing = {}                                        # 이번 검토에서 바꾼 메뉴의 주재료 → 횟수

    def ing_at(t, k):
        d, mi = divmod(t, 3)
        cat_ = SLOTS[[s for s, (kk, _) in SLOTS.items() if kk == k][0]][1]
        return _ing(problem, cat_, int(chrom[d * N_SLOTS + mi * 6 + k]) % len(pool[cat_]))

    def ing_problem(t, k, cat_, j) -> str | None:
        """주재료 쏠림 검사 → 거절 사유 또는 None"""
        ing = _ing(problem, cat_, j)
        if not ing:
            return None
        if used_ing.get(ing, 0) >= MAX_SAME_ING:
            return f"같은 주재료({ing})로 이미 {MAX_SAME_ING}번 바꿈"
        for u in range(max(0, t - ING_WINDOW), min(N_DAYS * 3, t + ING_WINDOW + 1)):
            for kk in (1, 2, 3, 4):
                if (u, kk) != (t, k) and ing_at(u, kk) == ing:
                    return f"앞뒤 {ING_WINDOW}끼 안에 같은 주재료({ing})가 있음"
        return None

    def name_at(t, k):
        d, mi = divmod(t, 3)
        cat = SLOTS[[s for s, (kk, _) in SLOTS.items() if kk == k][0]][1]
        return pool[cat][int(chrom[d * N_SLOTS + mi * 6 + k]) % len(pool[cat])]["menu_name"]

    for sg in suggestions[:MAX_SUGGESTIONS]:
        rec = {k: sg.get(k) for k in ("day", "meal", "slot", "current", "replace_with", "type", "problem", "why")}
        try:
            day, meal, slot = int(sg.get("day")), str(sg.get("meal")).strip(), str(sg.get("slot")).strip()
        except (TypeError, ValueError):
            rejected.append({**rec, "reason": "끼니 정보 형식 오류"}); continue
        if not (1 <= day <= N_DAYS) or meal not in MEALS or slot not in SLOTS:
            rejected.append({**rec, "reason": "없는 끼니·칸 (밥·김치는 바꾸지 않음)"}); continue
        k, cat = SLOTS[slot]
        t = (day - 1) * 3 + MEALS.index(meal)
        gi = (day - 1) * N_SLOTS + MEALS.index(meal) * 6 + k
        old = pool[cat][int(chrom[gi]) % len(pool[cat])]
        new_name = _strip_tag(sg.get("replace_with"))
        rec.update(day=day, meal=meal, slot=slot, current=old["menu_name"], replace_with=new_name)
        j = names[cat].get(new_name)
        if j is None:
            rejected.append({**rec, "reason": f"{cat} 후보 목록에 없는 메뉴"}); continue
        if new_name == old["menu_name"]:
            rejected.append({**rec, "reason": "지금과 같은 메뉴"}); continue
        if bool(pool[cat][j].get("one_dish")) != bool(old.get("one_dish")):
            rejected.append({**rec, "reason": "한 그릇 음식 여부가 다름"}); continue
        near = {name_at(u, kk) for u in range(max(0, t - WINDOW), min(N_DAYS * 3, t + WINDOW + 1))
                for kk in (1, 2, 3, 4) if not (u == t and kk == k)}
        need = _need(old, pool[cat][j])
        if need:
            # 칼슘·단백질 급원이 빠지는 교체 → 코드가 같은 급원의 부드러운 메뉴 중 점수가 가장 좋은 것으로 바꿈
            soft = sg.get("type") == "수용성" or old.get("texture") in ("부적합", "주의")
            ok = lambda jj: ing_problem(t, k, cat, jj) is None
            alt = best_alternative(problem, chrom, gi, cat, old, need, near, cur_f, soft, ok)
            if alt is None and soft:
                alt = best_alternative(problem, chrom, gi, cat, old, need, near, cur_f, False, ok)
            if alt is None:
                rejected.append({**rec, "reason": "칼슘·단백질 급원을 지킬 대체 메뉴가 없음"}); continue
            j = alt[0]
            src = "·".join({"ca": "칼슘", "protein": "단백질"}[x] for x in need)
            rec.update(llm_pick=new_name, replace_with=pool[cat][j]["menu_name"],
                       code_note=f"{src} 급원 보존: AI 제안 '{new_name}' 대신 같은 급원 중 점수가 가장 좋은 메뉴로 바꿈")
            new_name = rec["replace_with"]
        if new_name in near:
            rejected.append({**rec, "reason": "앞뒤 3일 안에 같은 메뉴가 있음"}); continue
        why_ing = ing_problem(t, k, cat, j)
        if why_ing:
            rejected.append({**rec, "reason": why_ing}); continue
        trial = chrom.copy()
        trial[gi] = j
        new_f = _f(problem, trial)
        bad = [x for x in ("f1", "f3", "f4") if new_f[x] - cur_f[x] > TOL[x]]
        if cur_f["f1"] <= F1_PASS < new_f["f1"]:
            bad.append("f1 기준(0.3) 초과")
        bad += [f"검토 누적 {x} +{new_f[x] - start_f[x]:.3f} (한도 {CUM_TOL[x]})" for x in CUM_TOL
                if new_f[x] - start_f[x] > CUM_TOL[x]]
        if bad:
            rejected.append({**rec, "reason": "점수가 나빠짐: " + ", ".join(
                f"{x} {cur_f[x]:.3f}→{new_f[x]:.3f}" if x in new_f else x for x in bad)}); continue
        oca, nca = calcium(old["menu_name"]), calcium(new_name)
        ing = _ing(problem, cat, j)
        if ing:
            used_ing[ing] = used_ing.get(ing, 0) + 1
        accepted.append({**rec, "ingredient": ing, "delta": {x: round(new_f[x] - cur_f[x], 4) for x in ("f1", "f3", "f4")},
                         "calcium": [round(oca) if oca is not None else None, round(nca) if nca is not None else None],
                         "protein": [round(old.get("protein") or 0, 1), round(pool[cat][j].get("protein") or 0, 1)]})
        chrom, cur_f = trial, new_f
    return chrom, accepted, rejected


# ─────────────────────────── 전체 ───────────────────────────
def review_menu(problem, chrom, context: dict, caller=None, progress=None) -> tuple[np.ndarray, dict]:
    """→ (검토 반영 염색체, 기록). caller 는 테스트용 (payload → (raw, model))"""
    say = progress or (lambda *_: None)
    say("AI 식단 검토: 28일 식단 읽는 중")
    payload = build_payload(problem, chrom, context)
    before = _f(problem, chrom)
    rec = {"mode": "llm", "prompt_version": PROMPT_VERSION, "f_before": {k: round(v, 4) for k, v in before.items()}}
    t0 = time.time()
    try:
        call = caller or (lambda p: LS.call_llm(p, system=SYSTEM_PROMPT, max_tokens=3000))
        raw, model = call(payload)
        sugg = raw.get("suggestions") or []
        if not isinstance(sugg, list):
            raise ValueError("suggestions 형식 오류")
    except Exception as e:
        msg = str(e)[:160]
        rec.update(mode="off", note=(f"{msg} → 검토 없이 진행" if msg.startswith("AI 영양사 미설정")
                                     else f"AI 검토 실패 → 검토 없이 진행 ({msg})"),
                   latency_sec=round(time.time() - t0, 1))
        return chrom, rec
    say(f"AI 식단 검토: 제안 {len(sugg)}건 검증 중")
    new, acc, rej = apply_suggestions(problem, chrom, sugg)
    after = _f(problem, new)
    rec.update(model=model, overall=LS._clean(raw.get("overall"), 400),
               accepted=[{**a, "problem": LS._clean(a.get("problem"), 160), "why": LS._clean(a.get("why"), 160)} for a in acc],
               rejected=[{**r, "problem": LS._clean(r.get("problem"), 160), "why": LS._clean(r.get("why"), 160)} for r in rej],
               n_suggested=len(sugg), f_after={k: round(v, 4) for k, v in after.items()},
               latency_sec=round(time.time() - t0, 1))
    return new, rec


if __name__ == "__main__":
    # 실제 LLM 확인:  venv-win\Scripts\python -m diet.llm_review tests\llm_review_sample.json
    #   (합성 데이터로 만든 28일 식단 — 개인정보 없음). 검증까지 실제 후보 풀로 돌린다
    import sys
    from .base_standard import BaseStandard
    from .pipeline import BUDGET_PER_MEAL, harmony_table, load_pool, records_to_chrom
    from .problem import MealPlanProblem
    src = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "tests/llm_review_sample.json", encoding="utf-8"))
    pool = load_pool()
    prob = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, harmony=harmony_table(pool))
    ch = records_to_chrom(prob, src["menu"])
    print("설정:", LS.status())
    new, rec = review_menu(prob, ch, src["context"], progress=print)
    print(f"\n모델 {rec.get('model')} · {rec.get('latency_sec')}초 · 제안 {rec.get('n_suggested')}건 → 반영 {len(rec.get('accepted', []))} · 거절 {len(rec.get('rejected', []))}")
    print("전체 평가:", rec.get("overall") or rec.get("note"))
    for a in rec.get("accepted", []):
        print(f"  ✔ {a['day']}일 {a['meal']} {a['slot']}: {a['current']} → {a['replace_with']}  [{a.get('type')}] {a.get('problem')}"
              f"  Δ{a['delta']} 칼슘 {a['calcium'][0]}→{a['calcium'][1]}mg 단백질 {a['protein'][0]}→{a['protein'][1]}g")
        if a.get("code_note"):
            print(f"      ↳ {a['code_note']}")
    for r in rec.get("rejected", []):
        print(f"  ✘ {r.get('day')}일 {r.get('meal')} {r.get('slot')}: {r.get('current')} → {r.get('replace_with')}  거절: {r['reason']}")
    print("f 전후:", rec.get("f_before"), "→", rec.get("f_after"))
