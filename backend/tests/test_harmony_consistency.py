# -*- coding: utf-8 -*-
"""조화 점수 일치 검사 — meal_score() (특징 이름 → 가중치 합, 기준 구현) 와
HarmonyTable.scores() (최적화에서 쓰는 numpy 벡터 계산) 가 같은 끼니에 같은 점수를 내는지 확인

  실행:  cd backend
         venv-win\\Scripts\\python -m tests.test_harmony_consistency      (결과 요약 출력)
         venv-win\\Scripts\\python -m pytest tests/test_harmony_consistency.py -q

  검사 1  실제 후보 풀(pool.json) 메뉴로 무작위 조합 N개 × (아침·점심·저녁·끼니 없음)
  검사 2  경계 사례: 부찬1 = 부찬2(같은 메뉴), 부찬끼리 조리법·주재료가 같은 조합, 주재료 없음(None) 메뉴
  검사 3  속성값 None: 일부 메뉴 속성을 None 으로 바꾼 복사본 (None == None 은 '같음' 아님)
  검사 4  최적화 경로 그대로: 무작위 염색체 → MealPlanProblem.meal_harmony() (84끼)
          vs 염색체를 메뉴 이름으로 풀고 속성을 새로 계산해 meal_score() — 인덱스·끼니 번호 매핑까지 확인
  비교는 확률이 아닌 로짓(z)으로 해서 작은 차이도 놓치지 않음 (허용 오차 1e-9)
"""
from __future__ import annotations

import copy
import random
import sys

import numpy as np

from diet import harmony as H

TOL = 1e-9
N_RANDOM = 50_000
SEED = 11
MEALS = ("아침", "점심", "저녁")


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-15, 1 - 1e-15)
    return np.log(p / (1 - p))


def _setup():
    from diet.pipeline import load_pool
    m = H.load_model()
    assert m.get("weights"), f"조화 모델이 꺼져 있음 ({m.get('path')}) — schema 불일치면 python -m diet.harmony_train 으로 재학습"
    pool = load_pool()
    table = H.HarmonyTable(pool)
    assert table.ok
    return pool, table


def _ref_logits(table, g, mi, s1, s2, t):
    """기준값: 같은 메뉴 속성으로 meal_score() 를 한 끼씩 계산"""
    A = table.attrs
    out = []
    for a, b, c, d, ti in zip(g, mi, s1, s2, t):
        meal = None if ti < 0 else MEALS[ti]
        out.append(H.meal_score(A["국"][a], A["주찬"][b], A["부찬"][c], A["부찬"][d], meal))
    return _logit(out)


def _fast_logits(table, g, mi, s1, s2, t):
    t = np.asarray(t)
    z = np.empty(len(g))
    on = t >= 0
    if on.any():
        z[on] = _logit(table.scores(g[on], mi[on], s1[on], s2[on], t[on]))
    if (~on).any():
        z[~on] = _logit(table.scores(g[~on], mi[~on], s1[~on], s2[~on], None))
    return z


def _diff_report(table, g, mi, s1, s2, t, zr, zf, k=5):
    """불일치 끼니: 메뉴 이름 · 특징 목록 · 차이"""
    pool_names = {cat: [a.get("_name") for a in table.attrs[cat]] for cat in table.attrs}
    bad = np.where(np.abs(zr - zf) > TOL)[0]
    lines = []
    for i in bad[:k]:
        A = table.attrs
        meal = None if t[i] < 0 else MEALS[t[i]]
        xs = (A["국"][g[i]], A["주찬"][mi[i]], A["부찬"][s1[i]], A["부찬"][s2[i]])
        lines.append(f"  끼니={meal} 차이={zr[i] - zf[i]:+.6f} 메뉴={[x.get('_name') for x in xs]}\n"
                     f"    속성={[{k_: x.get(k_) for k_ in ('method', 'main', 'main_ingredient', 'season', 'protein')} for x in xs]}\n"
                     f"    특징={H.meal_features(*xs, meal)}")
    return bad, "\n".join(lines)


def _name_attrs(pool, table):
    for cat in table.attrs:
        for x, a in zip(pool[cat], table.attrs[cat]):
            a["_name"] = x["menu_name"]


def check_random(pool, table, n=N_RANDOM, seed=SEED):
    rng = np.random.default_rng(seed)
    ng, nm, ns = (len(table.attrs[c]) for c in ("국", "주찬", "부찬"))
    g, mi, s1, s2 = rng.integers(0, ng, n), rng.integers(0, nm, n), rng.integers(0, ns, n), rng.integers(0, ns, n)
    t = rng.integers(-1, 3, n)                         # -1 = 끼니 정보 없음
    zr, zf = _ref_logits(table, g, mi, s1, s2, t), _fast_logits(table, g, mi, s1, s2, t)
    return (g, mi, s1, s2, t), zr, zf


def check_edges(pool, table, seed=SEED):
    rng = random.Random(seed)
    S = table.attrs["부찬"]
    ng, nm, ns = (len(table.attrs[c]) for c in ("국", "주찬", "부찬"))
    rows = []
    # 부찬1 = 부찬2 (같은 메뉴)
    for c in range(ns):
        rows.append((rng.randrange(ng), rng.randrange(nm), c, c))
    # 부찬끼리 조리법 / 주재료 묶음 / 실제 주재료가 같은 쌍 (부찬1 ≠ 부찬2)
    for key in ("method", "main", "main_ingredient"):
        by = {}
        for i, a in enumerate(S):
            by.setdefault(a.get(key), []).append(i)
        for v, ids in by.items():
            if len(ids) >= 2:
                for _ in range(min(30, len(ids))):
                    a, b = rng.sample(ids, 2)
                    rows.append((rng.randrange(ng), rng.randrange(nm), a, b))
    # 주재료 없음(None) 메뉴끼리 — None == None 을 '같은 주재료'로 세면 안 됨
    for cat_ids in ([i for i, a in enumerate(S) if a.get("main_ingredient") is None],):
        for _ in range(min(200, len(cat_ids) ** 2)):
            if len(cat_ids) >= 2:
                a, b = rng.sample(cat_ids, 2)
                rows.append((rng.randrange(ng), rng.randrange(nm), a, b))
    # 주찬과 부찬이 같은 주재료
    M = table.attrs["주찬"]
    sm = {}
    for i, a in enumerate(S):
        sm.setdefault(a.get("main_ingredient"), []).append(i)
    for j, a in enumerate(M):
        ids = sm.get(a.get("main_ingredient")) if a.get("main_ingredient") else None
        if ids:
            rows.append((rng.randrange(ng), j, rng.choice(ids), rng.randrange(ns)))
            rows.append((rng.randrange(ng), j, rng.randrange(ns), rng.choice(ids)))
    arr = np.array(rows)
    reps = len(arr)
    arr = np.repeat(arr, 4, axis=0)
    t = np.tile(np.array([-1, 0, 1, 2]), reps)
    g, mi, s1, s2 = arr.T
    zr, zf = _ref_logits(table, g, mi, s1, s2, t), _fast_logits(table, g, mi, s1, s2, t)
    return (g, mi, s1, s2, t), zr, zf


def check_problem_path(pool, table, n_chrom=30, seed=SEED):
    """최적화와 같은 경로: 염색체 → problem.meal_harmony() vs 이름으로 다시 푼 메뉴의 meal_score()"""
    from diet.base_standard import BaseStandard
    from diet.inventory import recipe_ingredients
    from diet.pipeline import BUDGET_PER_MEAL
    from diet.problem import MealPlanProblem, N_DAYS
    prob = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, harmony=table)
    assert prob.harmony is table
    rmap, codes = recipe_ingredients(), H._code_map()
    attr = lambda x: H.menu_attrs(x["menu_name"], codes.get(x["menu_name"]), x.get("ingredients") or rmap.get(x["menu_name"], {}))
    rng = np.random.default_rng(seed)
    n = [len(pool[c]) for c in ("국", "주찬", "부찬")]
    zr_all, zf_all = [], []
    for _ in range(n_chrom):
        c = rng.integers(0, 10_000, size=(N_DAYS * 3, 6))   # 최적화처럼 큰 정수 → % 풀 크기
        fast = prob.meal_harmony(c.reshape(-1))
        ref = []
        for k, row in enumerate(c):
            xs = (attr(pool["국"][row[1] % n[0]]), attr(pool["주찬"][row[2] % n[1]]),
                  attr(pool["부찬"][row[3] % n[2]]), attr(pool["부찬"][row[4] % n[2]]))
            ref.append(H.meal_score(*xs, MEALS[k % 3]))
        zr_all.append(_logit(ref))
        zf_all.append(_logit(fast))
    return np.concatenate(zr_all), np.concatenate(zf_all)


def check_missing_attrs(pool, table, seed=SEED):
    """현재 풀에는 속성값 None 이 거의 없으므로, 일부 메뉴의 조리법·주재료 묶음·양념·주재료를 None 으로 바꾼
    복사본으로 다시 검사 — None == None 을 '같음'으로 세지 않는 규칙이 두 함수에서 같은지 확인"""
    rng = random.Random(seed)
    tb = copy.deepcopy(table)
    for cat in tb.attrs:
        for a in tb.attrs[cat]:
            for k in H.PAIR_ATTRS:
                if rng.random() < 0.3:
                    a[k] = None
    tb._encode(H.load_model()["weights"])
    if hasattr(tb, "style"):
        del tb.style
    return check_edges(pool, tb, seed) + (tb,), check_random(pool, tb, 20_000, seed) + (tb,)


# ─────────────── pytest ───────────────
_CACHE = {}


def _ctx():
    if not _CACHE:
        pool, table = _setup()
        _name_attrs(pool, table)
        _CACHE.update(pool=pool, table=table)
    return _CACHE["pool"], _CACHE["table"]


def test_random_combos():
    pool, table = _ctx()
    idx, zr, zf = check_random(pool, table)
    bad, rep = _diff_report(table, *idx, zr, zf)
    assert len(bad) == 0, f"{len(bad)}끼 불일치\n{rep}"


def test_edge_cases():
    pool, table = _ctx()
    idx, zr, zf = check_edges(pool, table)
    bad, rep = _diff_report(table, *idx, zr, zf)
    assert len(bad) == 0, f"{len(bad)}끼 불일치\n{rep}"


def test_missing_attrs():
    pool, table = _ctx()
    for idx, zr, zf, tb in check_missing_attrs(pool, table):
        bad, rep = _diff_report(tb, *idx, zr, zf)
        assert len(bad) == 0, f"{len(bad)}끼 불일치\n{rep}"


def test_problem_path():
    pool, table = _ctx()
    zr, zf = check_problem_path(pool, table)
    assert np.abs(zr - zf).max() <= TOL


# ─────────────── 직접 실행 ───────────────
def main():
    pool, table = _ctx()
    m = H.load_model()
    print(f"모델: {m.get('path')}  (schema {m.get('schema')}, 학습 {m.get('trained_at')}, 특징 {len(m['weights'])}개)")
    print(f"후보 풀: 국 {len(pool['국'])} · 주찬 {len(pool['주찬'])} · 부찬 {len(pool['부찬'])}")
    ok = True
    for name, fn in (("① 무작위 조합", check_random), ("② 경계 사례", check_edges)):
        idx, zr, zf = fn(pool, table)
        d = np.abs(zr - zf)
        bad, rep = _diff_report(table, *idx, zr, zf)
        print(f"{name}: {len(d):,}끼 · 최대 차이(로짓) {d.max():.2e} · 불일치 {len(bad)}끼")
        if len(bad):
            ok = False
            print(rep)
    for name, (idx, zr, zf, tb) in zip(("③ 속성 없음(None) 경계", "③ 속성 없음(None) 무작위"), check_missing_attrs(pool, table)):
        d = np.abs(zr - zf)
        bad, rep = _diff_report(tb, *idx, zr, zf)
        print(f"{name}: {len(d):,}끼 · 최대 차이(로짓) {d.max():.2e} · 불일치 {len(bad)}끼")
        if len(bad):
            ok = False
            print(rep)
    zr, zf = check_problem_path(pool, table)
    d = np.abs(zr - zf)
    print(f"④ 최적화 경로(염색체 30개 × 84끼): {len(d):,}끼 · 최대 차이(로짓) {d.max():.2e} · 불일치 {(d > TOL).sum()}끼")
    ok &= bool(d.max() <= TOL)
    print("결과:", "일치 ✅" if ok else "불일치 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
