"""
moo_metrics.py  ─  다목적 최적화 성능 지표
============================================
  · 정규화(normalize)  : 목적함수별 고정 범위로 0~1 스케일링 → 실행 간 비교 가능
  · Hypervolume (HV)   : 정규화 공간, 기준점 1.1  (클수록 좋음)  ─ 수렴성+다양성
  · IGD+               : 기준 해 집합까지의 거리 (작을수록 좋음)  ─ 수렴성+다양성
  · Spacing (Schott)   : 이웃 해 간격의 표준편차 (작을수록 고르게 분포)
  · 비지배해 추출, 기준 해 집합(reference front) 저장/로드

목적함수 (모두 최소화):
  f1 영양 위반   f2 예산 초과   f3 -(다양성·선호)   f4 패턴 위반
"""

import json
import os
import numpy as np

# ── 목적함수별 고정 정규화 범위 [이상점, 최악점] ──────────────────
#   f1: 랜덤 식단 수준(~3)을 최악으로 가정
#   f3: -(diversity*0.7 + pref*100*0.3) → 이론 범위 -100 ~ 0
OBJ_NAMES  = ["f1_영양위반", "f2_예산초과+재고미활용", "f3_다양성선호", "f4_패턴위반"]
OBJ_BOUNDS = np.array([
    [0.0,    3.0],   # f1
    [0.0,    1.0],   # f2  (2026-10-19: 예산 초과 + 재고 미활용률, 보통 0~1)
    [-100.0, 0.0],   # f3
    [0.0,    1.0],   # f4
])
REF_POINT = 1.1       # 정규화 공간 HV 기준점 (모든 축 동일)
REFERENCE_FRONT_PATH = "reference_front.json"


# ══════════════════════════════════════════════════════════════
# 기본 연산
# ══════════════════════════════════════════════════════════════
def normalize(F: np.ndarray, bounds: np.ndarray = OBJ_BOUNDS) -> np.ndarray:
    """고정 범위로 0~1 정규화 (범위 밖은 0~REF_POINT로 clip)"""
    F = np.asarray(F, dtype=float)
    lo, hi = bounds[:, 0], bounds[:, 1]
    return np.clip((F - lo) / (hi - lo), 0.0, REF_POINT)


def nondominated(F: np.ndarray) -> np.ndarray:
    """비지배해만 반환 (최소화 기준, 중복 제거)"""
    F = np.unique(np.asarray(F, dtype=float), axis=0)
    keep = np.ones(len(F), dtype=bool)
    for i in range(len(F)):
        if not keep[i]:
            continue
        dominated_by = np.all(F <= F[i], axis=1) & np.any(F < F[i], axis=1)
        if dominated_by.any():
            keep[i] = False
    return F[keep]


# ══════════════════════════════════════════════════════════════
# 지표
# ══════════════════════════════════════════════════════════════
def hypervolume(F_norm: np.ndarray, ref: float = REF_POINT,
                mc_samples: int = 200_000, seed: int = 0) -> float:
    """
    정규화된 F의 HV. pymoo(HV) 정확 계산을 우선 사용하고,
    불가능한 환경이면 Monte Carlo 근사로 대체합니다.
    """
    F_norm = np.asarray(F_norm, dtype=float)
    ref_pt = np.full(F_norm.shape[1], ref)
    F_in   = F_norm[np.all(F_norm < ref_pt, axis=1)]
    if len(F_in) == 0:
        return 0.0
    try:
        from pymoo.indicators.hv import HV
        return float(HV(ref_point=ref_pt)(F_in))
    except Exception:
        rng = np.random.default_rng(seed)
        S   = rng.random((mc_samples, F_in.shape[1])) * ref
        dom = np.zeros(mc_samples, dtype=bool)
        for f in F_in:
            dom |= np.all(S >= f, axis=1)
        return float(dom.mean() * ref ** F_in.shape[1])


def igd_plus(F_norm: np.ndarray, ref_front_norm: np.ndarray) -> float:
    """IGD+ (Ishibuchi et al., 2015) ─ 정규화 공간, 작을수록 좋음"""
    A = np.asarray(F_norm, dtype=float)
    Z = np.asarray(ref_front_norm, dtype=float)
    diff = np.maximum(A[None, :, :] - Z[:, None, :], 0.0)   # (|Z|, |A|, m)
    d = np.sqrt((diff ** 2).sum(axis=2)).min(axis=1)
    return float(d.mean())


def spacing(F_norm: np.ndarray) -> float:
    """Spacing (Schott, 1995) ─ L1 최근접 거리의 표준편차, 작을수록 고르게 분포"""
    A = np.unique(np.asarray(F_norm, dtype=float), axis=0)
    if len(A) < 2:
        return 0.0
    D = np.abs(A[:, None, :] - A[None, :, :]).sum(axis=2)
    np.fill_diagonal(D, np.inf)
    d = D.min(axis=1)
    return float(np.sqrt(((d - d.mean()) ** 2).sum() / (len(d) - 1)))


# ══════════════════════════════════════════════════════════════
# 기준 해 집합 (reference front)
# ══════════════════════════════════════════════════════════════
def save_reference_front(F_raw: np.ndarray, path: str = REFERENCE_FRONT_PATH, meta: dict = None):
    """여러 실행 결과(원 스케일 F)를 합친 비지배해를 저장"""
    front = nondominated(F_raw)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"objectives": OBJ_NAMES, "bounds": OBJ_BOUNDS.tolist(),
                   "meta": meta or {}, "front": front.tolist()},
                  f, ensure_ascii=False, indent=1)
    return front


def load_reference_front(path: str = REFERENCE_FRONT_PATH):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return np.array(json.load(f)["front"], dtype=float)


# ══════════════════════════════════════════════════════════════
# 한 번에 계산
# ══════════════════════════════════════════════════════════════
def evaluate_front(F_raw: np.ndarray, ref_front_raw: np.ndarray = None) -> dict:
    """원 스케일 F → 지표 dict. ref_front_raw가 없으면 IGD+는 None"""
    F_nd   = nondominated(F_raw)
    F_norm = normalize(F_nd)
    out = {
        "hv_norm":      round(hypervolume(F_norm), 6),
        "spacing":      round(spacing(F_norm), 6),
        "igd_plus":     None,
        "n_nondom":     int(len(F_nd)),
    }
    if ref_front_raw is not None and len(ref_front_raw):
        out["igd_plus"] = round(igd_plus(F_norm, normalize(ref_front_raw)), 6)
    return out


# ══════════════════════════════════════════════════════════════
# [2026-10-18] 균형 해 선택 (MOPI-HFRS의 '고정 가중치 없음' 원칙)
# ══════════════════════════════════════════════════════════════
BALANCE_PASS_F1 = 0.3   # 건강(f1) 기준 통과 해 중에서만 선택 (없으면 전체에서)


def select_balanced(F, pass_f1: float = BALANCE_PASS_F1):
    """
    파레토 해 집합에서 '가장 균형 잡힌 해'의 인덱스를 반환합니다.
      ① f1(영양 위반) ≤ pass_f1 인 해만 후보 (없으면 f1 하위 10%)
      ② 후보 집합 안에서 목적별 최소~최대로 0~1 정규화
      ③ 이상점(모든 목적 0)까지 유클리드 거리가 가장 짧은 해
    """
    F = np.asarray(F, dtype=float)
    cand = np.where(F[:, 0] <= pass_f1)[0]
    rule = f"f1 ≤ {pass_f1} 통과 해 {len(cand)}개 중 균형점"
    if len(cand) == 0:
        k = max(1, int(len(F) * 0.1))
        cand = np.argsort(F[:, 0])[:k]
        rule = f"f1 통과 해 없음 → f1 하위 {k}개 중 균형점"
    sub = F[cand]
    lo, hi = sub.min(axis=0), sub.max(axis=0)
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    dist = np.sqrt((((sub - lo) / span) ** 2).sum(axis=1))
    best = int(cand[int(np.argmin(dist))])
    return best, rule
