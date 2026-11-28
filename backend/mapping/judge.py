# -*- coding: utf-8 -*-
"""④-2 판정 · ⑤ 승인 정책.

처음에는 규칙 점수(rule)로 판정한다. 사람 검수(approved/rejected)가 MIN_LABELS_FOR_MODEL 건 이상 쌓이면
train() 이 로지스틱 회귀를 학습하고, 자동 승인 정밀도가 TARGET_PRECISION 이상이 되는 기준을 함께 저장한다.
모델이 있으면 확률은 모델 값, 확정 불일치(가공품·다른 식재료 소유·부위·동물·분류) 규칙은 그대로 둔다.
"""
import json
import os
from dataclasses import dataclass

import numpy as np

from . import config as C

# ─────────────────────────── 규칙 점수 ───────────────────────────
BASE = {
    ("exact", "P"): 0.95, ("exact", "S"): 0.70,
    ("suffix", "P"): 0.92, ("suffix", "S"): 0.65,
    ("prefix", "P"): 0.90, ("prefix", "S"): 0.62,
}


def rule_score(f: dict) -> float:
    rel = f.get("rel")
    if rel == "meat":
        if not f.get("animal_match"):
            return 0.0
        s = {"primary": 0.93, "secondary": 0.62, "unknown": 0.50, "conflict": 0.05}[f.get("part_match", "unknown")]
    elif rel in ("exact", "suffix", "prefix"):
        s = BASE[(rel, f.get("tier") or "S")]
        if rel == "suffix" and f.get("leftover"):            # 앞에 모르는 말 = 품종일 수 있음 (꽈리고추, 적양파)
            if f.get("dcls_match") and f.get("form") == f.get("dcls") and not f.get("variety") and f.get("dcls_brand_ok"):
                s -= 0.02                                    # 공급사 세분류가 같은 이름 → 앞말은 브랜드·상품명
            else:
                s -= 0.32 if len(f.get("form") or "") >= 2 else 0.55
        if rel == "prefix" and f.get("leftover"):            # 뒤에 모르는 말 = 대개 가공품
            s = min(s, 0.30)
        if f.get("form_shared"):
            s -= 0.12
    elif rel == "dcls":                                      # 세분류만 맞음 → 검수 (안남미 같은 품종 차이)
        s = 0.80 - (0.12 if f.get("form_shared") else 0)
    else:                                                    # 이름 관계 없이 글자만 비슷
        s = 0.10 + 0.45 * f.get("sim", 0.0)
    if f.get("processed"):
        s = min(s, 0.05)
    if f.get("outranked"):
        s = min(s, 0.10)
    if not f.get("state_ok", True):
        s -= 0.30
    cat = f.get("category")
    if cat == "conflict":
        s -= 0.40
    elif cat == "ok":
        s += 0.02
    if f.get("dcls_match"):
        s += 0.03
    if f.get("price_range") == "out":
        s -= 0.10
    return float(min(max(s, 0.0), 1.0))


def hard_reject(f: dict) -> str | None:
    """확률과 상관없이 같은 식재료가 아닌 경우 (이유 문자열)."""
    if f.get("rel") == "meat":
        if not f.get("animal_match"):
            return "동물이 다름"
        if f.get("part_match") == "conflict":
            return "부위가 다름"
    if f.get("processed"):
        return f"가공품 ({f['processed']})"
    if f.get("outranked"):
        return "상품 이름이 다른 식재료와 더 길게 일치"
    if f.get("owned_elsewhere"):
        return f"'{f.get('form')}'은 다른 식재료의 대표 이름"
    if f.get("category") == "conflict" and f.get("rel") not in ("exact",):
        return "분류가 맞지 않음"
    return None


def gates(f: dict) -> list[str]:
    """자동 승인 조건 중 못 맞춘 것 (빈 목록이면 통과)."""
    miss = []
    if f.get("category") == "conflict":
        miss.append("분류")
    if not f.get("state_ok", True):
        miss.append("상태")
    if f.get("processed"):
        miss.append("가공품")
    if f.get("form_shared"):
        miss.append("여러 식재료가 같은 이름")
    if f.get("tier") == "S":
        miss.append("대표 이름이 아닌 같은 코드 이름으로 일치")
    if f.get("ready_meal"):
        miss.append("간편식 표시")
    if f.get("variety"):
        miss.append(f"품종 표시 '{f['variety']}'")
    # g당 가격은 동일성 판정 조건이 아니다 (명세서 권고). 규격 오류·튀는 값은 오늘 가격 계산에서 이상값으로 뺀다.
    if f.get("rel") == "meat" and f.get("part_match") != "primary":
        miss.append("부위")
    return miss


# ─────────────────────────── 학습 모델 ───────────────────────────
FEATURE_ORDER = [
    "sim", "rel_dcls", "rel_exact", "rel_suffix", "rel_prefix", "rel_meat", "rel_fuzzy", "tier_P", "form_shared", "leftover_len",
    "processed", "outranked", "state_ok", "cat_ok", "cat_conflict", "dcls_match", "price_ok", "price_out",
    "part_primary", "part_secondary", "part_unknown", "embed", "rule",
]


def vectorize(f: dict) -> list[float]:
    rel = f.get("rel")
    return [
        f.get("sim", 0.0), rel == "dcls", rel == "exact", rel == "suffix", rel == "prefix", rel == "meat",
        rel not in ("exact", "suffix", "prefix", "meat", "dcls"), f.get("tier") == "P", bool(f.get("form_shared")),
        min(len(f.get("leftover") or ""), 6) / 6, bool(f.get("processed")), bool(f.get("outranked")),
        bool(f.get("state_ok", True)), f.get("category") == "ok", f.get("category") == "conflict",
        bool(f.get("dcls_match")), f.get("price_range") == "ok", f.get("price_range") == "out",
        f.get("part_match") == "primary", f.get("part_match") == "secondary", f.get("part_match") == "unknown",
        f.get("embed", 0.0), rule_score(f),
    ]


@dataclass
class Model:
    version: str
    coef: list
    intercept: float
    approve_at: float
    reject_below: float

    def prob(self, f: dict) -> float:
        z = float(np.dot(self.coef, np.asarray(vectorize(f), float)) + self.intercept)
        return 1 / (1 + np.exp(-z))


def load_model(path: str | None = None) -> Model | None:
    path = path or os.path.join(C.MODEL_DIR, "judge_latest.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path, encoding="utf-8"))
    return Model(**d)


def train(labeled: list[tuple[dict, int]], version: str, out_dir: str = C.MODEL_DIR) -> dict:
    """labeled = [(features, 1=같음/0=다름)]. 교차검증 확률로 정밀도 98% 기준을 찾는다."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict

    X = np.array([vectorize(f) for f, _ in labeled], float)
    y = np.array([y for _, y in labeled], int)
    if len(y) < C.MIN_LABELS_FOR_MODEL or y.min() == y.max():
        return {"trained": False, "reason": f"라벨 {len(y)}건 (최소 {C.MIN_LABELS_FOR_MODEL}, 양쪽 모두 필요)"}
    clf = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
    p = cross_val_predict(clf, X, y, cv=5, method="predict_proba")[:, 1]
    approve_at, best_cov = 0.99, 0.0
    for t in np.arange(0.50, 0.995, 0.005):
        sel = p >= t
        if sel.sum() < 20:
            continue
        prec = y[sel].mean()
        if prec >= C.TARGET_PRECISION and sel.mean() > best_cov:
            approve_at, best_cov = float(t), float(sel.mean())
    reject_below = 0.10
    for t in np.arange(0.05, 0.5, 0.01):
        sel = p < t
        if sel.sum() and (1 - y[sel].mean()) >= 0.98:     # 자동 거절도 98% 이상 맞아야
            reject_below = float(t)
    clf.fit(X, y)
    m = {"version": version, "coef": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0]),
         "approve_at": approve_at, "reject_below": reject_below}
    os.makedirs(out_dir, exist_ok=True)
    for name in (f"judge_{version}.json", "judge_latest.json"):
        json.dump(m, open(os.path.join(out_dir, name), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"trained": True, "n": int(len(y)), "auto_approve_share_cv": best_cov, **m}


# ─────────────────────────── 결정 ───────────────────────────
def decide(f: dict, model: Model | None = None) -> tuple[str, float, str, str]:
    """→ (status, score, method, reason)   status ∈ auto_approved | pending | auto_rejected"""
    rs = rule_score(f)
    score, method = rs, "rule"
    approve_at, reject_below = C.AUTO_APPROVE, C.AUTO_REJECT
    if model is not None:
        score, method = model.prob(f), "model"
        approve_at, reject_below = model.approve_at, model.reject_below
    hr = hard_reject(f)
    if hr:
        return "auto_rejected", min(score, 0.05), method, hr
    miss = gates(f)
    if score >= approve_at and not miss:
        return "auto_approved", score, method, "이름·분류·상태·가공·가격 모두 맞음"
    if score < reject_below:
        return "auto_rejected", score, method, "확률 낮음"
    return "pending", score, method, ("자동 승인 못 함: " + ", ".join(miss)) if miss else "확률이 자동 승인 기준 미만"
