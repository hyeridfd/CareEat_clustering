# -*- coding: utf-8 -*-
"""
MFA-HCPC 유형 모델 (v2 이후)

  학습:  python scripts/train_mfa_hcpc.py ...   (models/<version>/model.joblib 생성)
  배정:  engine.TypeModel 이 bundle["pre"].transform(X) → (좌표, 표준점수) 를 받아
         학습 군집 중심과의 거리로 배정한다. v1(가중 표준점수 공간)과 인터페이스가 같다.

방법 (Nutrients 2026, 18, 2560 과 동일)
  1) 변수별 표준화(학습 평균·SD 고정) → 결측은 학습 표준점수 기준 KNN(k=5, 거리가중) 대치
  2) 그룹(영역)마다 1/√(그룹 첫 고유값) 가중 → 영역 간 비중을 맞춤 (MFA)
  3) 학습 자료의 주축 5개에 투영 → 이 좌표에서 Ward + k-means 정제로 만든 군집 중심과 비교

sklearn 객체를 피클하지 않는다(numpy·pandas만) → 서버의 sklearn 버전과 무관하게 불러온다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KNN_NEIGHBORS = 5


class MFAPreprocessor:
    """학습 자료로 표준화 기준·그룹 가중·주축을 고정하고 새 대상자를 같은 좌표로 옮긴다."""

    def fit(self, X: pd.DataFrame, groups: dict, ncp: int = 5):
        self.groups = {g: list(vs) for g, vs in groups.items()}
        self.cols = [v for vs in self.groups.values() for v in vs]
        X = X[self.cols].astype(float)
        self.mean_ = X.mean()
        self.sd_ = X.std(ddof=0).replace(0, 1.0)
        Z = (X - self.mean_) / self.sd_
        self.ref_ = Z.dropna().values                    # KNN 참조셋 (완전 응답 학습자)
        Z = self._impute(Z)
        w = {}
        for g, vs in self.groups.items():
            Zg = Z[vs].values
            lam1 = (np.linalg.svd(Zg, compute_uv=False)[0] ** 2 / len(Zg)) if len(vs) > 1 else 1.0
            lam1 = lam1 if lam1 > 1e-8 else 1.0
            for v in vs:
                w[v] = 1.0 / np.sqrt(lam1)
        self.w_ = pd.Series(w)[self.cols]
        W = (Z * self.w_).values
        self.center_ = W.mean(0)
        U, S, Vt = np.linalg.svd(W - self.center_, full_matrices=False)
        eig = S ** 2 / len(W)
        self.ncp = int(min(ncp, (eig > 1e-10).sum()))
        self.V_ = Vt[: self.ncp].T                       # p × ncp
        self.eig_ = eig
        self.dims_ = [f"Dim{i + 1}" for i in range(self.ncp)]
        return self

    def _impute(self, Z: pd.DataFrame) -> pd.DataFrame:
        Z = Z.copy()
        miss = Z.isna()
        if not miss.values.any():
            return Z
        R = self.ref_
        for i in np.where(miss.any(axis=1).values)[0]:
            z = Z.iloc[i].values.astype(float)
            obs = ~np.isnan(z)
            if not obs.any():                            # 전부 결측 → 학습 평균(0)
                Z.iloc[i] = np.where(np.isnan(z), 0.0, z)
                continue
            d = np.sqrt(((R[:, obs] - z[obs]) ** 2).mean(axis=1))
            nn = np.argsort(d)[:KNN_NEIGHBORS]
            wt = 1.0 / np.maximum(d[nn], 1e-6)
            fill = (R[nn] * wt[:, None]).sum(0) / wt.sum()
            z[~obs] = fill[~obs]
            Z.iloc[i] = z
        return Z

    def transform(self, X: pd.DataFrame):
        """→ (MFA 좌표 DataFrame, 대치된 표준점수 DataFrame)"""
        X = X.reindex(columns=self.cols).apply(pd.to_numeric, errors="coerce")
        Z = (X - self.mean_) / self.sd_
        Zi = self._impute(Z)
        coords = ((Zi * self.w_).values - self.center_) @ self.V_
        return pd.DataFrame(coords, index=X.index, columns=self.dims_), Zi

    def explained(self):
        return (100 * self.eig_ / self.eig_.sum())[: self.ncp]


def ward_kmeans(coords: np.ndarray, k: int, seed: int = 42):
    """HCPC: Ward 계층적 군집 → 그 중심에서 시작하는 k-means 정제. 군집 번호는 크기 순(C1 = 가장 큰 군집)."""
    from scipy.cluster.hierarchy import linkage, fcluster, cut_tree
    from sklearn.cluster import KMeans
    Z = linkage(coords, "ward")
    lab = fcluster(Z, k, "maxclust") - 1
    if len(np.unique(lab)) < k:
        lab = cut_tree(Z, n_clusters=k).ravel()
    cent = np.vstack([coords[lab == c].mean(0) for c in range(k)])
    lab2 = KMeans(k, init=cent, n_init=1, random_state=seed).fit(coords).labels_
    order = pd.Series(lab2).value_counts().index.tolist()
    return np.array([order.index(l) for l in lab2])
