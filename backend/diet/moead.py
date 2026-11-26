"""
moead.py  ─  MOEA/D (numpy만 사용, 서버판)
==========================================
[2026-11-26] 일반식 최적화 기본 알고리즘 — NSGA-II(nsga2.py)를 대체.
  다목적 알고리즘 비교(scripts/moea_benchmark_v2.ipynb, 결과 moea_results/v2_pool*)에서
  NSGA-II·NSGA-III·SPEA2·MOEA/D 4종 중 MOEA/D 가 모든 사례·지표에서 1위였고,
  격자 탐색으로 고른 설정(기준 방향 91개(4목적 120개)·이웃 T 30·변이 1개·교차 0.9)이
  새 시드 검증에서 기본 설정과 현재 NSGA-II 보다 모두 유의하게 좋았다 → 그 설정을 기본값으로 쓴다.

구현은 pymoo MOEAD(0.6.x)와 같은 방식이다.
  · 분해: 체비쇼프  g(x | w, z*) = max_i w_i · |f_i(x) − z*_i|   (z* = 지금까지의 이상점)
  · 기준 방향: Das–Dennis 균등 격자 (목적 3개 → 분할 12 = 91개, 4개 → 분할 7 = 120개)
  · 부모 선택: 확률 δ(0.9) 로 이웃 T개 안에서, 아니면 집단 전체에서 2개
  · 교차: 균등 교차(확률 CX_PROB) → 자식 2개 중 1개 · 변이: 유전자마다 mut_genes/n 확률로 무작위 메뉴
  · 교체: 자식이 더 나은 이웃 해를 모두 교체
  · 목적함수 크기가 서로 달라 무작위 해(N_SCALE개)의 1–99 백분위로 척도를 맞춘 뒤 분해한다
    (pymoo MOEA/D 는 스스로 정규화하지 않아 벤치마크에서도 같은 고정 척도를 썼다)
  · f2 비용이 무작위 해에서 늘 같은 값이면(예산이 넉넉하고 재고 정보가 없어 늘 0) 분해에서 빼고 f1·f3·f4 로 푼다
    (벤치마크 사례 A·B 는 f1·f3·f4, 예산 제약 사례 C 는 f1~f4 와 같은 규칙).
    f1·f3·f4 는 무작위 해에서 변화가 없어도 뺄 수 없다 — 예: 후보가 많으면 무작위 식단은 반복이 없어 f3 가 0 이지만
    최적화가 진행되며 반복이 생길 수 있다 (이때 척도 폭은 1 로 둔다)

minimize() 의 입출력은 nsga2.minimize() 와 같다 → (X 비지배해, F 비지배해, X 전체, F 전체), F 는 원래 척도 4개 목적.
"""
import numpy as np

CX_PROB = 0.9
DELTA = 0.9                       # 이웃 안에서 부모를 고를 확률
N_NEIGHBORS = 30                  # 이웃 수 T (격자 탐색 최적값)
MUT_GENES = 1.0                   # 염색체당 평균 변이 유전자 수 (격자 탐색 최적값)
REF_PARTITIONS = {1: 1, 2: 90, 3: 12, 4: 7, 5: 5}   # 목적 수 → Das–Dennis 분할 수 (2목적 91개 · 3목적 91개 · 4목적 120개)
N_SCALE = 500                     # 척도 추정용 무작위 해 수
ACTIVE_EPS = 1e-9                 # 이보다 변동이 작은 목적은 상수로 본다
DROPPABLE = (1,)                  # 상수일 때 분해에서 뺄 수 있는 목적 — f2 비용만


def das_dennis(m: int, h: int) -> np.ndarray:
    """합이 1인 m차원 균등 격자 (분할 h)"""
    out = []

    def rec(prefix, left, depth):
        if depth == m - 1:
            out.append(prefix + [left])
            return
        for i in range(left + 1):
            rec(prefix + [i], left - i, depth + 1)

    rec([], h, 0)
    return np.array(out, dtype=float) / h


def budget_of(pop_size: int, n_gen: int) -> int:
    """NSGA-II 실행 강도(개체 수 × 세대 수)와 같은 평가 횟수 — 초기 집단 포함"""
    return int(pop_size) * (int(n_gen) + 1)


def minimize(problem, budget=22650, seed=42, n_neighbors=N_NEIGHBORS, mut_genes=MUT_GENES,
             cx_prob=CX_PROB, delta=DELTA, progress=None, **_):
    """→ (X 비지배해, F 비지배해, X 전체, F 전체)   budget: 평가 횟수(척도 추정용 N_SCALE 회 제외)"""
    rng = np.random.default_rng(seed)
    ub = np.asarray(problem.xu, dtype=int) + 1
    n_var = len(ub)
    mut_rate = float(mut_genes) / n_var
    ev = lambda x: np.asarray(problem._eval_one(x), dtype=float)

    # ① 척도 — 무작위 해의 1–99 백분위, 변하지 않는 목적은 분해에서 제외
    S = np.array([ev(x) for x in rng.integers(0, ub, size=(N_SCALE, n_var))])
    lo, hi = np.percentile(S, 1, axis=0), np.percentile(S, 99, axis=0)
    const = (S.max(0) - S.min(0)) <= ACTIVE_EPS
    active = np.array([j for j in range(S.shape[1]) if not (j in DROPPABLE and const[j])])
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    scale = lambda F: ((np.atleast_2d(F) - lo) / span)[:, active]

    # ② 기준 방향 · 이웃
    m = len(active)
    W = das_dennis(m, REF_PARTITIONS.get(m, 4)) if m > 1 else np.ones((1, 1))
    N = len(W)
    T = int(min(max(2, n_neighbors), N))
    D = ((W[:, None, :] - W[None, :, :]) ** 2).sum(-1)
    B = np.argsort(D, axis=1, kind="quicksort")[:, :T]          # 자기 자신 포함
    Wd = np.maximum(W, 1e-6)                                     # 가중치 0 → 아주 작은 값 (체비쇼프 퇴화 방지)

    # ③ 초기 집단
    X = rng.integers(0, ub, size=(N, n_var))
    F = np.array([ev(x) for x in X])
    Z = scale(F)
    ideal = Z.min(0)
    n_gen = max(1, (int(budget) - N) // N)

    for g in range(n_gen):
        for k in rng.permutation(N):
            pool_idx = B[k] if rng.random() < delta else np.arange(N)
            a, b = rng.choice(pool_idx, 2, replace=len(pool_idx) < 2)
            # 균등 교차 → 자식 하나
            if rng.random() < cx_prob:
                mask = rng.random(n_var) < 0.5
                c1, c2 = np.where(mask, X[b], X[a]), np.where(mask, X[a], X[b])
                child = c1 if rng.random() < 0.5 else c2
            else:
                child = (X[a] if rng.random() < 0.5 else X[b]).copy()
            mut = rng.random(n_var) < mut_rate
            if mut.any():
                child = np.where(mut, rng.integers(0, ub), child)
            fc = ev(child)
            zc = scale(fc)[0]
            ideal = np.minimum(ideal, zc)
            # 체비쇼프 분해로 이웃 비교 → 더 나은 이웃을 모두 교체
            nb = B[k]
            g_old = (np.abs(Z[nb] - ideal) * Wd[nb]).max(1)
            g_new = (np.abs(zc - ideal) * Wd[nb]).max(1)
            better = nb[g_new < g_old]
            if len(better):
                X[better] = child
                F[better] = fc
                Z[better] = zc
        if progress and (g % 10 == 0 or g == n_gen - 1):
            progress(g + 1, n_gen, float(F[:, 0].min()))

    # ④ 최종 집단의 비지배해 (중복 제거)
    _, uniq = np.unique(X, axis=0, return_index=True)
    uniq = np.sort(uniq)
    Xu, Fu = X[uniq], F[uniq]
    le = (Fu[:, None, :] <= Fu[None, :, :]).all(-1)
    lt = (Fu[:, None, :] < Fu[None, :, :]).any(-1)
    front = np.where(~(le & lt).any(0))[0]
    return Xu[front], Fu[front], X, F
