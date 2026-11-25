# -*- coding: utf-8 -*-
"""Care-Eat 공통 식단 최적화 — 다목적 알고리즘 비교·조정용 핵심 모듈 (pymoo 표준 구현)

노트북(moea_benchmark.ipynb)과 같은 폴더에 둔다. 노트북과 병렬 작업자(joblib)가 이 모듈을 불러와 실행한다.
  · 문제: diet/problem.py 의 MealPlanProblem (28일 일반식, 목적함수 f1 영양·f2 비용·f3 다양성·f4 조화)
  · 사례: A 기본 · B 시설 개선안 6건 반영 · C 예산 제약(끼니당 950원)
  · 알고리즘: pymoo NSGA2 · NSGA3 · SPEA2 · MOEAD — 모두 같은 표집·교차·변이 연산자
"""
import json
import os
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

BACKEND = os.environ.get("CAREEAT_BACKEND")
if BACKEND and BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from pymoo.algorithms.moo.moead import MOEAD
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.algorithms.moo.nsga3 import NSGA3
from pymoo.algorithms.moo.spea2 import SPEA2
from pymoo.core.mutation import Mutation
from pymoo.core.problem import Problem
from pymoo.decomposition.tchebicheff import Tchebicheff
from pymoo.operators.crossover.ux import UniformCrossover
from pymoo.operators.sampling.rnd import IntegerRandomSampling
from pymoo.optimize import minimize
from pymoo.util.ref_dirs import get_reference_directions

# ── 사례 ──────────────────────────────────────────────────────────
PLAN_IDS = ["F_NUT_SODIUM", "F_MALNUT", "F_NUT_CALCIUM", "F_NUT_FIBER", "F_TEXTURE_NEED", "F_LOW_INTAKE"]
INSTANCES = {
    # 기본 예산(끼니당 10,000원)에서는 f2(예산 초과)가 늘 0 → 작동하는 목적만 최적화
    "A": dict(name="A 기본", budget=10000, plan=False, obj=[0, 2, 3]),
    "B": dict(name="B 시설 개선안 반영", budget=10000, plan=True, obj=[0, 2, 3]),
    "C": dict(name="C 예산 제약", budget=950, plan=False, obj=[0, 1, 2, 3]),
}
OBJ_NAME = {0: "f1 영양", 1: "f2 비용", 2: "f3 다양성", 3: "f4 조화"}

# 기준점 분할 수 (NSGA-III·MOEA/D) — 수준 → das-dennis 분할 수
#   3목적: −2 → 45개 · −1 → 66개 · 0 → 91개 · 1 → 153개 · 2 → 231개
#   4목적: −2 → 56개 · −1 → 84개 · 0 → 120개 · 1 → 165개 · 2 → 220개
REF_PARTITIONS = {3: {-2: 8, -1: 10, 0: 12, 1: 16, 2: 20}, 4: {-2: 5, -1: 6, 0: 7, 1: 8, 2: 9}}


@lru_cache(maxsize=None)
def build_instance(key):
    """사례 → (식단 문제, 목적 번호, 척도 하한, 척도 폭). 작업자마다 한 번만 만든다."""
    from diet.base_standard import BaseStandard
    from diet.pipeline import MealPlanProblem, harmony_table, load_pool
    cfg = INSTANCES[key]
    pool = load_pool(None)
    plan = None
    if cfg["plan"]:
        from diet import facility_plan as FPL
        plan = FPL.from_priorities([{"id": i, "title": i, "severity": 2} for i in PLAN_IDS], {"menus": {"worst": []}})
        pool, _ = FPL.apply_pool(pool, plan)
    p = MealPlanProblem(pool, BaseStandard(), cfg["budget"], harmony=harmony_table(pool))
    if plan:
        FPL.configure(p, plan)
    obj = cfg["obj"]
    # 목적마다 크기가 달라 고정 척도로 맞춘다 (무작위 해 2,000개의 1–99 백분위, 모든 알고리즘 공통)
    rng = np.random.default_rng(0)
    ub = np.asarray(p.xu, dtype=int) + 1
    S = np.array([[p._eval_one(x)[i] for i in obj] for x in rng.integers(0, ub, size=(2000, len(ub)))])
    lo, hi = np.percentile(S, 1, axis=0), np.percentile(S, 99, axis=0)
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    return p, tuple(obj), lo, span


class MealProblem(Problem):
    """pymoo 문제 — 정수 염색체(28일 × 18칸 메뉴 번호) → 척도를 맞춘 목적값"""

    def __init__(self, key):
        self.key = key
        self.meal, self.obj, self.lo, self.span = build_instance(key)
        super().__init__(n_var=len(self.meal.xu), n_obj=len(self.obj), xl=0,
                         xu=np.asarray(self.meal.xu, dtype=int), vtype=int)

    def _evaluate(self, X, out, *args, **kwargs):
        X = np.round(X).astype(int)
        F = np.array([[self.meal._eval_one(x)[i] for i in self.obj] for x in X])
        out["F"] = (F - self.lo) / self.span


class RandomResetMutation(Mutation):
    """무작위 재설정 변이 — 유전자마다 확률 mut_genes / n_var 로 새 메뉴 번호 (염색체당 평균 mut_genes 개)"""

    def __init__(self, mut_genes=4.0):
        super().__init__(prob=1.0)
        self.mut_genes = float(mut_genes)

    def _do(self, problem, X, random_state=None, **kwargs):
        # pymoo 가 시드로 만든 난수 생성기(random_state)를 써야 같은 시드 → 같은 결과 (재현성)
        rs = random_state if random_state is not None else np.random.default_rng()
        X = np.array(X, dtype=float).round().astype(int)
        mask = rs.random(X.shape) < self.mut_genes / problem.n_var
        rnd = rs.integers(0, np.asarray(problem.xu, dtype=int) + 1, size=X.shape)
        return np.where(mask, rnd, X)


def ref_dirs(n_obj, level):
    return get_reference_directions("das-dennis", n_obj, n_partitions=REF_PARTITIONS[n_obj][int(level)])


def make_algorithm(alg, prm, n_obj):
    ops = dict(sampling=IntegerRandomSampling(), crossover=UniformCrossover(prob=float(prm["cx"])),
               mutation=RandomResetMutation(prm["mut"]))
    if alg == "NSGA2":
        return NSGA2(pop_size=int(prm["pop_size"]), eliminate_duplicates=True, **ops)
    if alg == "SPEA2":
        return SPEA2(pop_size=int(prm["pop_size"]), eliminate_duplicates=True, **ops)
    R = ref_dirs(n_obj, prm["ref_level"])
    if alg == "NSGA3":
        return NSGA3(ref_dirs=R, pop_size=int(np.ceil(len(R) / 4) * 4), eliminate_duplicates=True, **ops)
    if alg == "MOEAD":
        return MOEAD(ref_dirs=R, n_neighbors=int(prm["n_neighbors"]), prob_neighbor_mating=float(prm.get("delta", 0.9)),
                     decomposition=Tchebicheff(), **ops)
    raise ValueError(alg)


# 코드 버전 — 결과를 바꾸는 수정이 있으면 올림. 버전별 하위 폴더에 저장되므로 예전 결과와 섞이지 않음
#   v1: 변이 연산자가 전역 난수(np.random) 사용 → 변이가 시드로 고정되지 않음
#   v2: 변이도 pymoo random_state 사용 → 모든 실행이 시드로 완전히 재현됨
CODE_VERSION = "v2"


def job_path(job):
    return Path(job["out_dir"]) / CODE_VERSION / job["stage"] / f"{job['tag']}.json"


def run_one(job):
    """한 번 실행 → 최종 비지배해(원래 척도 목적값)를 JSON 으로 저장. 이미 있으면 건너뜀."""
    path = job_path(job)
    if path.exists():
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prob = MealProblem(job["instance"])
    algo = make_algorithm(job["alg"], job["params"], prob.n_obj)
    t = time.time()
    res = minimize(prob, algo, ("n_eval", int(job["budget"])), seed=int(job["seed"]), verbose=False)
    sec = time.time() - t
    F = np.atleast_2d(res.F) * prob.span + prob.lo
    rec = {**{k: job[k] for k in ("stage", "alg", "instance", "seed", "params", "setting", "tag", "budget")},
           "obj": list(prob.obj), "code_version": CODE_VERSION, "sec": round(sec, 2), "n_eval": int(res.algorithm.evaluator.n_eval),
           "F": np.round(F, 6).tolist()}
    tmp = path.with_suffix(".tmp")
    json.dump(rec, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, path)
    return str(path)
