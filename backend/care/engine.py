# -*- coding: utf-8 -*-
"""
유형 배정 엔진
  - Supabase 설문 행 → 통합 특징(파이프라인과 동일 채점)
  - 활성 유형 모델로 배정 + 경계 여부
  - 유형 전이 판정: '상태 변화'와 '모델 변경'을 구분
"""
from __future__ import annotations
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import bluefood_cluster as bc

MODEL_DIR = Path(os.getenv("CARE_MODEL_DIR", Path(__file__).resolve().parent.parent / "models"))
BORDERLINE_MAX = float(os.getenv("CARE_BORDERLINE_MAX", "0.15"))

# 파이프라인이 읽는 기초조사표 컬럼 (행에 없으면 결측으로 채움)
BASIC_COLS = (["elderly_id", "nursing_home_id", "created_at", "updated_at", "age", "gender", "care_grade",
               "education", "diseases", "medications", "height", "weight", "systolic_bp", "diastolic_bp",
               "vigorous_activity_days", "vigorous_activity_time", "moderate_activity_days",
               "moderate_activity_time", "walking_days", "walking_time", "sitting_time", "mna_bmi_category",
               "mna_appetite_change", "mna_weight_change", "mna_mobility", "mna_stress_illness",
               "mna_neuropsychological_problem", "chewing_difficulty", "swallowing_difficulty", "meal_type",
               "eating_independence"]
              + list(bc.KMBI_SCORES) + bc.MMSE_ITEMS + [f"gds_{i}" for i in range(1, 16)])
NUTRITION_COLS = ["elderly_id", "nursing_home_id", "updated_at", "meal_portions", "plate_waste"]
SAT_COLS = ["elderly_id", "nursing_home_id", "updated_at", "overall_satisfaction", "portion_adequacy",
            "food_quality", "preferred_food_groups", "improvement_suggestions"]

# 설명·솔루션·추이 비교에 쓰는 지표 (원값 저장)
KEY_FEATURES = bc.cluster_vars() + ["age", "female", "care_grade", "education_level", "n_diseases", "dx_dementia", "dx_diabetes",
                                    "dx_depression", "dx_stroke", "dx_parkinson", "dx_hypertension", "mna_risk",
                                    "intake_kimchi", "intake_snack", "intake_g_day", "pref_seafood", "pref_meat",
                                    "pref_fruit", "pref_vegetable", "cmt_seasoning", "cmt_portion", "cmt_variety",
                                    "cmt_diabetic", "cmt_fruit", "cmt_texture_fishy", "has_nutrition",
                                    "mmse_untested", "gds_untested", "weight_kg", "height_cm", "met_total", "sitting_min",
                                    "sbp", "dbp", "n_food_groups", "intake_breakfast", "intake_lunch", "intake_dinner",
                                    "n_days", "kmbi_mobility_wheelchair", "mna_risk"]
# 숫자가 아닌 부가 정보 (리포트용)
EXTRA_FEATURES = ["diseases", "medications", "improvement_text", "meal_form"]


def _frame(rows, cols):
    df = pd.DataFrame(rows or [])
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df


def build_features(basic_rows, nutrition_rows, satisfaction_rows):
    """Supabase 행(dict 리스트) 3종 → 대상자별 특징 DataFrame (index = 'NH|ID')."""
    b = _frame(basic_rows, BASIC_COLS)
    if b.empty:
        return pd.DataFrame()
    n = _frame(nutrition_rows, NUTRITION_COLS)
    s = _frame(satisfaction_rows, SAT_COLS)
    df = bc.build_dataset_frames(b, n, s)
    # 원값·부가 정보 (리포트용)
    bb = bc.dedupe_latest(b).set_index("key")
    df["weight_kg"] = pd.to_numeric(bb["weight"], errors="coerce").reindex(df.index)
    df["height_cm"] = pd.to_numeric(bb["height"], errors="coerce").reindex(df.index)
    df["diseases"] = bb["diseases"].apply(bc.parse_json_list).reindex(df.index)
    df["medications"] = bb["medications"].apply(bc.parse_json_list).reindex(df.index) if "medications" in bb.columns else None
    df["meal_form"] = bb["meal_type"].reindex(df.index) if "meal_type" in bb.columns else None
    df["survey_start"] = bb["created_at"].reindex(df.index) if "created_at" in bb.columns else None
    # 3개 조사표 중 가장 최근 저장 시각 (변경 없으면 재평가 생략 판단용)
    ts = []
    for t in (b, n, s):
        if len(t):
            tt = t.assign(key=bc.make_key(t), _ts=pd.to_datetime(t["updated_at"], errors="coerce", utc=True, format="mixed"))
            ts.append(tt.groupby("key")["_ts"].max())
    latest = pd.concat(ts, axis=1).max(axis=1) if ts else pd.Series(dtype="datetime64[ns, UTC]")
    df["survey_updated_at"] = latest.reindex(df.index)
    return df


# ─────────────────────────── 모델 로드 ───────────────────────────

class TypeModel:
    def __init__(self, version: str, bundle: dict, meta: dict):
        self.version = version
        self.pre = bundle["pre"]
        self.centroids = np.asarray(bundle["centroids"])
        self.k = int(bundle["k"])
        self.cluster_vars = list(bundle["cluster_vars"])
        self.names = bundle.get("names")
        rel = bundle.get("train_relative_margin")
        # 경계 기준: 1·2순위 유형 거리 차가 2순위 거리의 15% 미만 (단, 학습 데이터 하위 20% 를 넘지 않게)
        self.borderline_cut = min(BORDERLINE_MAX, float(np.percentile(rel, 20))) if rel else BORDERLINE_MAX
        self.meta = meta

    def code(self, idx: int) -> str:
        return f"C{idx + 1}"

    def type_info(self, code: str) -> dict:
        m = self.meta.get(code, {})
        idx = int(code[1:]) - 1
        name = m.get("name") or (self.names[idx] if self.names and idx < len(self.names) else code)
        return {"code": code, "name": name, "guardian_label": m.get("guardian_label", name),
                "risk_weight": float(m.get("risk_weight", 0)), "description": m.get("description", "")}

    def assign(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df.reindex(columns=self.cluster_vars).apply(pd.to_numeric, errors="coerce")
        Xw, Zi = self.pre.transform(X)
        d = np.linalg.norm(Xw.values[:, None, :] - self.centroids[None, :, :], axis=2)
        order = np.argsort(d, axis=1)
        d1 = d[np.arange(len(d)), order[:, 0]]
        d2 = d[np.arange(len(d)), order[:, 1]] if self.k > 1 else d1
        out = pd.DataFrame(index=df.index)
        out["type_code"] = [self.code(i) for i in order[:, 0]]
        out["second_code"] = [self.code(i) for i in order[:, 1]] if self.k > 1 else out["type_code"]
        out["centroid_margin"] = (d2 - d1).round(4)
        out["relative_margin"] = ((d2 - d1) / np.maximum(d2, 1e-9)).round(4)
        out["is_borderline"] = out["relative_margin"] < self.borderline_cut
        out["n_missing"] = X.isna().sum(axis=1).values
        out["imputed_vars"] = X.isna().apply(lambda r: [c for c in self.cluster_vars if r[c]], axis=1)
        # 설명용: 개인의 표준점수 중 전체 평균에서 가장 벗어난 지표
        out["deviations"] = [
            [{"var": v, "label": bc.VAR_LABELS.get(v, v), "z": round(float(z), 2)}
             for v, z in sorted(row.items(), key=lambda kv: -abs(kv[1]))[:5] if abs(z) >= 0.5]
            for _, row in Zi.iterrows()
        ]
        return out


def _install_pickle_shim():
    """파일럿(python bluefood_cluster.py fit)으로 저장된 모델은 __main__.Preprocessor 로 피클됨."""
    main = sys.modules.get("__main__")
    if main is not None and not hasattr(main, "Preprocessor"):
        setattr(main, "Preprocessor", bc.Preprocessor)


@lru_cache(maxsize=8)
def load_model(version: str) -> TypeModel:
    import joblib
    _install_pickle_shim()
    d = MODEL_DIR / version
    bundle = joblib.load(d / "model.joblib")
    meta_path = d / "type_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return TypeModel(version, bundle, meta)


def active_version(sb=None) -> str:
    v = os.getenv("CARE_ACTIVE_MODEL")
    if v:
        return v
    if sb is not None:
        try:
            r = sb.table("type_models").select("version").eq("is_active", True).execute()
            if r.data:
                return r.data[0]["version"]
        except Exception:
            pass
    # 폴더 중 최신
    if MODEL_DIR.exists():
        cands = sorted([p.name for p in MODEL_DIR.iterdir() if (p / "model.joblib").exists()])
        if cands:
            return cands[-1]
    raise RuntimeError("활성 유형 모델이 없습니다. python -m care.train 으로 모델을 등록하세요.")


# ─────────────────────────── 전이 판정 ───────────────────────────

def classify_transition(model: TypeModel, current_code: str, prev: dict | None) -> dict:
    """
    prev: 직전 care_assessments 행.
    - first        : 첫 평가
    - same         : 유형 동일
    - state_change : 어르신 상태가 바뀌어 유형이 달라짐 (알림 대상)
    - model_change : 모델 버전 교체로만 달라짐 (직전 지표를 현 모델로 다시 배정하면 현재와 같음 → 알림 제외)
    """
    if not prev:
        return {"kind": "first"}
    base = {"prev_type": prev["type_code"], "prev_model": prev["model_version"]}
    if prev["model_version"] == model.version:
        kind = "same" if prev["type_code"] == current_code else "state_change"
        return {**base, "kind": kind}
    # 모델이 바뀐 경우: 직전 지표를 현재 모델로 재배정
    feats = prev.get("features") or {}
    if isinstance(feats, str):
        feats = json.loads(feats)
    prev_df = pd.DataFrame([{v: feats.get(v) for v in model.cluster_vars}], index=["prev"])
    prev_now = model.assign(prev_df).iloc[0]["type_code"]
    base["prev_type_under_current_model"] = prev_now
    if prev_now == current_code:
        kind = "same" if prev["type_code"] == current_code else "model_change"
    else:
        kind = "state_change"
    return {**base, "kind": kind}


def features_record(row: pd.Series) -> dict:
    rec = {}
    for v in EXTRA_FEATURES + ["survey_start"]:
        x = row.get(v)
        if isinstance(x, list):
            rec[v] = [str(i) for i in x]
        elif x is None or (isinstance(x, float) and np.isnan(x)):
            rec[v] = None
        else:
            rec[v] = str(x)
    for v in KEY_FEATURES:
        x = row.get(v)
        if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
            rec[v] = None
        else:
            rec[v] = round(float(x), 3)
    rec["improvement_text"] = (row.get("improvement_text") or "") if isinstance(row.get("improvement_text"), str) else ""
    return rec
