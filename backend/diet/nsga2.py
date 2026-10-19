"""
nsga2.py  ─  NSGA-II (numpy만 사용, 서버판)
==========================================
에이전트는 pymoo NSGA-II를 쓰지만, 서버는 설치·메모리 부담을 줄이려고 같은 알고리즘을 직접 구현했다.
  · 정수 염색체 (칸마다 후보 메뉴 번호)
  · 선택: 이진 토너먼트 (비지배 순위 → 혼잡 거리)
  · 교차: 균등 교차 (확률 CX_PROB)
  · 변이: 칸마다 MUT_RATE 확률로 무작위 메뉴로 교체
  · 생존: 부모+자식 2N에서 비지배 정렬 + 혼잡 거리로 N개
"""
import numpy as np

CX_PROB = 0.9


def nondominated_sort(F: np.ndarray) -> list:
    n = len(F)
    le = (F[:, None, :] <= F[None, :, :]).all(axis=2)
    lt = (F[:, None, :] < F[None, :, :]).any(axis=2)
    dom = le & lt                       # dom[i, j]: i가 j를 지배
    n_dom = dom.sum(axis=0)             # 나를 지배하는 해의 수
    fronts, cur = [], np.where(n_dom == 0)[0]
    assigned = np.zeros(n, dtype=bool)
    while len(cur):
        fronts.append(cur)
        assigned[cur] = True
        n_dom = n_dom - dom[cur].sum(axis=0)
        cur = np.where((n_dom == 0) & ~assigned)[0]
    return fronts


def crowding(F: np.ndarray) -> np.ndarray:
    n, m = F.shape
    d = np.zeros(n)
    if n <= 2:
        return np.full(n, np.inf)
    for k in range(m):
        o = np.argsort(F[:, k])
        span = F[o[-1], k] - F[o[0], k]
        d[o[0]] = d[o[-1]] = np.inf
        if span > 0:
            d[o[1:-1]] += (F[o[2:], k] - F[o[:-2], k]) / span
    return d


def _rank_crowd(F):
    rank = np.empty(len(F), dtype=int)
    cd = np.empty(len(F))
    for r, fr in enumerate(nondominated_sort(F)):
        rank[fr] = r
        cd[fr] = crowding(F[fr])
    return rank, cd


def minimize(problem, pop_size=150, n_gen=150, seed=42, mut_genes=4.0, progress=None):
    """→ (X 비지배해, F 비지배해, X 전체, F 전체)"""
    rng = np.random.default_rng(seed)
    ub = np.asarray(problem.xu, dtype=int) + 1
    n_var = len(ub)
    mut_rate = mut_genes / n_var
    X = rng.integers(0, ub, size=(pop_size, n_var))
    F = np.array([problem._eval_one(x) for x in X])
    for g in range(n_gen):
        rank, cd = _rank_crowd(F)
        # 이진 토너먼트
        a, b = rng.integers(0, pop_size, (2, pop_size))
        better = (rank[a] < rank[b]) | ((rank[a] == rank[b]) & (cd[a] > cd[b]))
        parents = np.where(better, a, b)
        P1, P2 = X[parents[0::2]], X[parents[1::2]]
        mask = rng.random(P1.shape) < 0.5
        do_cx = rng.random(len(P1)) < CX_PROB
        mask &= do_cx[:, None]
        C1 = np.where(mask, P2, P1); C2 = np.where(mask, P1, P2)
        C = np.vstack([C1, C2])[:pop_size]
        mut = rng.random(C.shape) < mut_rate
        C = np.where(mut, rng.integers(0, ub, size=C.shape), C)
        FC = np.array([problem._eval_one(x) for x in C])
        XA, FA = np.vstack([X, C]), np.vstack([F, FC])
        _, uniq = np.unique(XA, axis=0, return_index=True)          # 중복 해 제거
        uniq = np.sort(uniq)
        XA, FA = XA[uniq], FA[uniq]
        keep = []
        for fr in nondominated_sort(FA):
            if len(keep) + len(fr) <= pop_size:
                keep.extend(fr.tolist())
            else:
                cdf = crowding(FA[fr])
                keep.extend(fr[np.argsort(-cdf)][:pop_size - len(keep)].tolist())
                break
        if len(keep) < pop_size:                                     # 중복 제거로 모자라면 무작위 보충
            extra = rng.integers(0, ub, size=(pop_size - len(keep), n_var))
            XA = np.vstack([XA, extra]); FA = np.vstack([FA, [problem._eval_one(x) for x in extra]])
            keep.extend(range(len(XA) - len(extra), len(XA)))
        X, F = XA[keep], FA[keep]
        if progress and (g % 10 == 0 or g == n_gen - 1):
            progress(g + 1, n_gen, float(F[:, 0].min()))
    front = nondominated_sort(F)[0]
    return X[front], F[front], X, F
