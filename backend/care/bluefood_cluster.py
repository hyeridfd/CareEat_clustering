# -*- coding: utf-8 -*-
"""
블루푸드 요양원 고령자 유형분류(클러스터링) 파이프라인
=========================================================
(프로젝트 claude/pipeline/bluefood_cluster.py 와 동일 — 백엔드 모듈로 포함)

웹 설문 앱에서 내려받은 CSV 3종(기초/영양/만족도)을 그대로 넣으면
  1) 척도 점수 재계산 (MNA-SF, K-MBI, K-MMSE-2, GDS-SF, IPAQ-SF)
  2) 5일 섭취율(잔반 기반) 산출
  3) 결측 대치 → 표준화 → 도메인 가중
  4) k 탐색 (실루엣·CH·DB·부트스트랩 안정성·방법 간 일치도)
  5) Ward → K-means 정제로 최종 군집
  6) 군집 프로파일 표·그림·엑셀·모델 저장
"""
import argparse
import json
import os
import re
import warnings
from collections import Counter

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# =====================================================================
# 0. 설정
# =====================================================================

CLUSTER_BLOCKS = {
    "영양·신체기능": ["bmi", "mna_sf", "kmbi_pct"],
    "인지·정서": ["mmse", "gds"],
    "구강·섭식기능": ["chewing_difficulty", "swallowing_difficulty", "texture_level", "eating_dependence"],
    "식사 섭취": ["intake_total", "intake_rice", "intake_main", "intake_side", "intake_soup"],
    "급식 만족": ["sat_overall", "sat_portion", "sat_quality"],
}

PROFILE_ONLY = [
    "age", "female", "care_grade", "education_level", "n_diseases",
    "dx_dementia", "dx_diabetes", "dx_depression", "dx_stroke", "dx_parkinson", "dx_hypertension",
    "met_total", "sitting_min", "sbp", "dbp", "mna_risk", "kmbi_mobility_wheelchair",
    "intake_kimchi", "intake_snack", "intake_breakfast", "intake_lunch", "intake_dinner",
    "served_g_day", "intake_g_day", "intake_day_sd",
    "n_food_groups", "pref_seafood", "pref_meat", "pref_fruit", "pref_vegetable",
    "cmt_seasoning", "cmt_portion", "cmt_variety", "cmt_diabetic", "cmt_fruit", "cmt_texture_fishy",
    "has_nutrition", "mmse_untested", "gds_untested",
]

VAR_LABELS = {
    "bmi": "BMI (kg/m²)", "mna_sf": "MNA-SF (0–14)", "kmbi_pct": "K-MBI (%)",
    "mmse": "K-MMSE-2 (0–30)", "gds": "GDS-SF (0–15)",
    "chewing_difficulty": "저작곤란", "swallowing_difficulty": "연하곤란",
    "texture_level": "식사형태 (0일반~3유동)", "eating_dependence": "식사 의존도 (0–2)",
    "intake_total": "전체 섭취율 (%)", "intake_rice": "밥/죽 섭취율 (%)", "intake_main": "주찬 섭취율 (%)",
    "intake_side": "부찬 섭취율 (%)", "intake_soup": "국/탕 섭취율 (%)", "intake_kimchi": "김치 섭취율 (%)",
    "intake_snack": "간식 섭취율 (%)", "intake_breakfast": "아침 섭취율 (%)", "intake_lunch": "점심 섭취율 (%)",
    "intake_dinner": "저녁 섭취율 (%)", "served_g_day": "배식량 (g/일)", "intake_g_day": "섭취량 (g/일)",
    "intake_day_sd": "일간 섭취율 변동 (SD)",
    "sat_overall": "급식 전반 만족", "sat_portion": "양 적절성", "sat_quality": "맛·품질 만족",
    "age": "연령", "female": "여성", "care_grade": "장기요양등급", "education_level": "학력 (0무학~4대졸)",
    "n_diseases": "보유 질환 수", "dx_dementia": "치매", "dx_diabetes": "당뇨병", "dx_depression": "우울증",
    "dx_stroke": "뇌혈관질환", "dx_parkinson": "파킨슨병", "dx_hypertension": "고혈압",
    "met_total": "신체활동 (MET-분/주)", "sitting_min": "좌식시간 (분/일)", "sbp": "수축기혈압", "dbp": "이완기혈압",
    "mna_risk": "MNA 영양불량/위험 (<12)", "kmbi_mobility_wheelchair": "휠체어 이동",
    "n_food_groups": "선호 식품군 수", "pref_seafood": "생선·해산물 선호", "pref_meat": "고기류 선호",
    "pref_fruit": "과일 선호", "pref_vegetable": "채소·나물 선호",
    "cmt_seasoning": "의견: 간/싱거움", "cmt_portion": "의견: 양 부족", "cmt_variety": "의견: 다양성",
    "cmt_diabetic": "의견: 당뇨식", "cmt_fruit": "의견: 과일", "cmt_texture_fishy": "의견: 물렁/비린내/가시",
    "has_nutrition": "영양조사 완료", "mmse_untested": "MMSE 미시행", "gds_untested": "GDS 미시행",
}

K_RANGE = range(2, 7)
N_BOOT = 200
RANDOM_STATE = 42
KNN_NEIGHBORS = 5
MIN_CLUSTER_FRAC = 0.08
MIN_JACCARD = 0.60

# =====================================================================
# 1. 로딩 유틸
# =====================================================================

def read_csv_any(path):
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc)
            if any("id" == c.strip().lower().lstrip("﻿") for c in df.columns):
                df.columns = [c.lstrip("﻿") for c in df.columns]
                return df
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError(f"CSV 인코딩을 판별할 수 없습니다: {path}")


def make_key(df):
    return df["nursing_home_id"].astype(str).str.strip() + "|" + df["elderly_id"].astype(str).str.strip()


def dedupe_latest(df):
    df = df.copy()
    df["key"] = make_key(df)
    if "updated_at" in df.columns:
        df["_ts"] = pd.to_datetime(df["updated_at"], errors="coerce", utc=True, format="mixed")
        df = df.sort_values("_ts").drop(columns="_ts")
    return df.drop_duplicates("key", keep="last")


def parse_json_list(x):
    if isinstance(x, list):
        return x
    if not isinstance(x, str) or not x.strip():
        return []
    try:
        v = json.loads(x)
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def parse_json_obj(x):
    if isinstance(x, dict):
        return x
    if not isinstance(x, str) or not x.strip():
        return {}
    try:
        v = json.loads(x)
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def to_bool(x):
    if isinstance(x, (bool, np.bool_)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().upper()
        if s in ("TRUE", "예", "1", "Y"):
            return 1.0
        if s in ("FALSE", "아니오", "0", "N"):
            return 0.0
    if isinstance(x, (int, float)) and not pd.isna(x):
        return float(bool(x))
    return np.nan

# =====================================================================
# 2. 기초 조사표 → 건강 변수
# =====================================================================

KMBI_SCORES = {
    "kmbi_1": [0, 1, 3, 4, 5], "kmbi_2": [0, 1, 3, 4, 5],
    "kmbi_3": [0, 2, 5, 8, 10], "kmbi_4": [0, 2, 5, 8, 10], "kmbi_5": [0, 2, 5, 8, 10],
    "kmbi_6": [0, 2, 5, 8, 10], "kmbi_7": [0, 2, 5, 8, 10], "kmbi_8": [0, 2, 5, 8, 10],
    "kmbi_9": [0, 0, 3, 8, 12, 15],
    "kmbi_10": [0, 0, 1, 3, 4, 5],
    "kmbi_11": [0, 3, 8, 12, 15],
}
MMSE_ITEMS = [
    "mmse_reg_airplane", "mmse_reg_pencil", "mmse_reg_pine",
    "mmse_time_year", "mmse_time_month", "mmse_time_day", "mmse_time_weekday", "mmse_time_season",
    "mmse_place_country", "mmse_place_city", "mmse_place_type", "mmse_place_name", "mmse_place_floor",
    "mmse_recall_airplane", "mmse_recall_pencil", "mmse_recall_pine",
    "mmse_calc_1", "mmse_calc_2", "mmse_calc_3", "mmse_calc_4", "mmse_calc_5",
    "mmse_naming", "mmse_repetition", "mmse_comprehension", "mmse_reading", "mmse_writing", "mmse_drawing",
]
GDS_REVERSE = {1, 5, 7, 11, 13}
TEXTURE = {"일반식": 0, "다진식": 1, "갈은식(믹서식)": 2, "유동식": 3}
EATING = {"스스로 식사할 수 있음": 0, "요양보호사 등의 부분적인 도움 필요": 1, "요양보호사 등의 전적인 도움 필요": 2}
CARE = {"1등급": 1, "2등급": 2, "3등급": 3, "4등급 이상": 4}
EDU = {"무학": 0, "초등학교 졸업": 1, "중학교 졸업": 2, "고등학교 졸업": 3, "대학교(전문대 포함) 졸업 이상": 4}


def kmbi_row(r):
    def sc(item):
        v = r.get(item)
        if pd.isna(v) or v == "":
            return None
        idx = int(float(v))
        s = KMBI_SCORES[item]
        return s[idx] if 0 <= idx < len(s) else None

    base_items = [i for i in KMBI_SCORES if i not in ("kmbi_9", "kmbi_10")]
    base_vals = [sc(i) for i in base_items]
    if all(v is None for v in base_vals):
        return np.nan, np.nan
    base = sum(v or 0 for v in base_vals)
    walk_idx = r.get("kmbi_9")
    wheel_idx = r.get("kmbi_10")
    walk_applicable = not pd.isna(walk_idx) and int(float(walk_idx)) >= 1
    wheel_applicable = not pd.isna(wheel_idx) and int(float(wheel_idx)) >= 1
    if walk_applicable and (sc("kmbi_9") or 0) > 0:
        return (base + sc("kmbi_9")) / 100 * 100, 0.0
    if wheel_applicable:
        return (base + (sc("kmbi_10") or 0)) / 90 * 100, 1.0
    if walk_applicable:
        return base / 100 * 100, 0.0
    return base / 100 * 100, np.nan


def to_num(s):
    """'165', '165cm', '165 cm', ' 165.0 ' 등 문자 섞인 값도 숫자로 변환 (빈 값은 NaN)."""
    x = pd.Series(s).astype(str).str.replace(r"[^0-9.\-]", "", regex=True).str.strip()
    x = x.replace({"": np.nan, ".": np.nan, "-": np.nan})
    return pd.to_numeric(x, errors="coerce")


def build_health(b):
    out = pd.DataFrame({"key": b["key"].values, "elderly_id": b["elderly_id"].values,
                        "nursing_home_id": b["nursing_home_id"].values})
    year = pd.to_datetime(b["created_at"], errors="coerce", utc=True, format="mixed").dt.year.fillna(2026)
    out["age"] = (year - pd.to_numeric(b["age"], errors="coerce")).values
    out["female"] = (b["gender"] == "여자").astype(float).values
    out["care_grade"] = b["care_grade"].map(CARE).values
    out["education_level"] = b["education"].astype(str).str.strip().map(EDU).values

    dis = b["diseases"].apply(parse_json_list)
    out["n_diseases"] = dis.apply(lambda L: len([d for d in L if d not in ("기타", "없음")])).values
    for col, kw in [("dx_dementia", "치매"), ("dx_diabetes", "당뇨병"), ("dx_depression", "우울증"),
                    ("dx_stroke", "뇌혈관"), ("dx_parkinson", "파킨슨"), ("dx_hypertension", "고혈압")]:
        out[col] = dis.apply(lambda L: float(any(kw in d for d in L))).values

    h = to_num(b["height"])
    w = to_num(b["weight"])
    out["bmi"] = (w / (h / 100) ** 2).values
    out["sbp"] = to_num(b["systolic_bp"]).values
    out["dbp"] = to_num(b["diastolic_bp"]).values

    g = lambda c: pd.to_numeric(b[c], errors="coerce").fillna(0)
    out["met_total"] = (g("vigorous_activity_days") * g("vigorous_activity_time") * 8.0
                        + g("moderate_activity_days") * g("moderate_activity_time") * 4.0
                        + g("walking_days") * g("walking_time") * 3.3).values
    out["sitting_min"] = to_num(b["sitting_time"]).values

    bmi = out["bmi"]
    bmi_cat = np.select([bmi < 19, bmi < 21, bmi < 23], [0, 1, 2], default=3).astype(float)
    bmi_cat = np.where(bmi.isna(), pd.to_numeric(b["mna_bmi_category"], errors="coerce"), bmi_cat)
    defaults = {"mna_appetite_change": 2, "mna_weight_change": 3, "mna_mobility": 2,
                "mna_stress_illness": 2, "mna_neuropsychological_problem": 2}
    mna = sum(pd.to_numeric(b[c], errors="coerce").fillna(d) for c, d in defaults.items()) + bmi_cat
    out["mna_sf"] = mna.values
    out["mna_risk"] = (out["mna_sf"] < 12).astype(float)

    km = b.apply(kmbi_row, axis=1, result_type="expand")
    out["kmbi_pct"] = km[0].values
    out["kmbi_mobility_wheelchair"] = km[1].values

    mm = b[MMSE_ITEMS].apply(pd.to_numeric, errors="coerce")
    untested = mm.isna().all(axis=1)
    out["mmse"] = np.where(untested, np.nan, mm.fillna(0).sum(axis=1))
    out["mmse_untested"] = untested.astype(float).values

    gds_cols = [f"gds_{i}" for i in range(1, 16)]
    def gds_row(r):
        answered, score = 0, 0
        for i in range(1, 16):
            v = r.get(f"gds_{i}")
            if v not in ("예", "아니오"):
                continue
            answered += 1
            score += (v == "아니오") if i in GDS_REVERSE else (v == "예")
        if answered < 12:
            return np.nan
        return score * 15 / answered
    gds = b[gds_cols].apply(gds_row, axis=1)
    out["gds"] = gds.values
    out["gds_untested"] = gds.isna().astype(float).values

    out["chewing_difficulty"] = b["chewing_difficulty"].apply(to_bool).values
    out["swallowing_difficulty"] = b["swallowing_difficulty"].apply(to_bool).values
    out["texture_level"] = b["meal_type"].map(TEXTURE).values
    out["eating_dependence"] = b["eating_independence"].map(EATING).values
    return out

# =====================================================================
# 3. 영양 조사표 → 5일 섭취율 (잔반 0=다 먹음 … 4=모두 남김, 섭취율=1-잔반/4)
# =====================================================================

SNACK_DEFAULT_PORTIONS = {
    1: {"간식1": {"간식": 190}, "간식2": {"간식": 150}},
    2: {"간식1": {"간식": 125}, "간식2": {"간식A": 23, "간식B": 190}},
    3: {"간식1": {"간식": 80}, "간식2": {"간식A": 23.8, "간식B": 65}},
    4: {"간식1": {"간식": 190}, "간식2": {"간식": 118}},
    5: {"간식1": {"간식": 125}, "간식2": {"간식": 124.9}},
}
MAIN_MEALS = ("아침", "점심", "저녁")
MEAL_ORDER = {"아침": 0, "간식1": 1, "점심": 2, "간식2": 3, "저녁": 4}
COMPONENT = {"밥/죽": "rice", "국/탕": "soup", "주찬": "main", "부찬1": "side", "부찬2": "side",
             "김치1": "kimchi", "김치2": "kimchi"}


def build_nutrition(n):
    rows = []
    for _, r in n.iterrows():
        mp = parse_json_obj(r.get("meal_portions"))
        pw = parse_json_obj(r.get("plate_waste"))
        served = Counter(); eaten = Counter()
        meal_served = Counter(); meal_eaten = Counter()
        day_served = Counter(); day_eaten = Counter()
        log = {}          # 일자×끼니 식사 기록 (리포트 식단표용)
        snack_rates = []
        days = sorted(set(mp) | set(pw))
        for d in days:
            dnum = int(re.sub(r"\D", "", d) or 0)
            for meal in MAIN_MEALS:
                foods = mp.get(d, {}).get(meal, {})
                for food, g in foods.items():
                    if isinstance(g, str) or g is None:
                        continue
                    wv = pw.get(d, {}).get(meal, {}).get(food, 0)
                    if wv == "추후섭취":
                        continue
                    try:
                        rate = 1 - float(wv) / 4
                    except (TypeError, ValueError):
                        continue
                    comp = COMPONENT.get(food, "other")
                    served[comp] += g; eaten[comp] += g * rate
                    meal_served[meal] += g; meal_eaten[meal] += g * rate
                    day_served[d] += g; day_eaten[d] += g * rate
                    cell = log.setdefault((dnum, meal), {"served": 0.0, "eaten": 0.0, "items": []})
                    cell["served"] += g; cell["eaten"] += g * rate
                    cell["items"].append({"slot": food, "name": None, "g": round(float(g), 1),
                                          "rate": round(100 * rate)})
            for meal in ("간식1", "간식2"):
                waste = pw.get(d, {}).get(meal, {})
                defaults = SNACK_DEFAULT_PORTIONS.get(dnum, {}).get(meal, {})
                for food, g in defaults.items():
                    wv = waste.get(food, 0)
                    if wv == "추후섭취":
                        continue
                    try:
                        rate = 1 - float(wv) / 4
                    except (TypeError, ValueError):
                        continue
                    snack_rates.append((g, rate))
                    cell = log.setdefault((dnum, meal), {"served": 0.0, "eaten": 0.0, "items": []})
                    cell["served"] += g; cell["eaten"] += g * rate
                    cell["items"].append({"slot": food, "name": None, "g": round(float(g), 1),
                                          "rate": round(100 * rate)})
        tot_s = sum(served.values()); tot_e = sum(eaten.values())
        rec = {"key": r["key"], "n_days": len(days)}
        rec["intake_total"] = 100 * tot_e / tot_s if tot_s else np.nan
        for comp in ("rice", "soup", "main", "side", "kimchi"):
            rec[f"intake_{comp}"] = 100 * eaten[comp] / served[comp] if served[comp] else np.nan
        if snack_rates:
            gs = sum(g for g, _ in snack_rates)
            rec["intake_snack"] = 100 * sum(g * x for g, x in snack_rates) / gs
        else:
            rec["intake_snack"] = np.nan
        for meal, key in (("아침", "breakfast"), ("점심", "lunch"), ("저녁", "dinner")):
            rec[f"intake_{key}"] = 100 * meal_eaten[meal] / meal_served[meal] if meal_served[meal] else np.nan
        nd = max(len(day_served), 1)
        rec["served_g_day"] = tot_s / nd if tot_s else np.nan
        rec["intake_g_day"] = tot_e / nd if tot_s else np.nan
        daily = [100 * day_eaten[d] / day_served[d] for d in day_served if day_served[d]]
        rec["intake_day_sd"] = float(np.std(daily, ddof=1)) if len(daily) > 1 else np.nan
        rec["meal_log"] = [{"day": dn, "meal": ml, "rate": round(100 * c["eaten"] / c["served"]) if c["served"] else None,
                            "served_g": round(c["served"], 1), "items": c["items"]}
                           for (dn, ml), c in sorted(log.items(), key=lambda kv: (kv[0][0], MEAL_ORDER.get(kv[0][1], 9)))]
        rows.append(rec)
    cols = ["key", "n_days", "meal_log", "intake_total", "intake_rice", "intake_soup", "intake_main", "intake_side",
            "intake_kimchi", "intake_snack", "intake_breakfast", "intake_lunch", "intake_dinner",
            "served_g_day", "intake_g_day", "intake_day_sd"]
    return pd.DataFrame(rows, columns=cols)

# =====================================================================
# 4. 만족도 조사표
# =====================================================================

COMMENT_RULES = {
    "cmt_seasoning": r"간|싱겁|싱거|짜",
    "cmt_portion": r"양",
    "cmt_variety": r"다양|종류|반찬",
    "cmt_diabetic": r"당뇨",
    "cmt_fruit": r"과일|딸기",
    "cmt_texture_fishy": r"물렁|비린|가시",
}


def build_satisfaction(s):
    out = pd.DataFrame({"key": s["key"].values})
    out["sat_overall"] = pd.to_numeric(s["overall_satisfaction"], errors="coerce").values
    out["sat_portion"] = pd.to_numeric(s["portion_adequacy"], errors="coerce").values
    out["sat_quality"] = pd.to_numeric(s["food_quality"], errors="coerce").values
    fg = s["preferred_food_groups"].apply(parse_json_list)
    out["n_food_groups"] = fg.apply(lambda L: len([x for x in L if x != "기타"])).values
    out["pref_seafood"] = fg.apply(lambda L: float("생선·해산물류" in L)).values
    out["pref_meat"] = fg.apply(lambda L: float("고기류" in L)).values
    out["pref_fruit"] = fg.apply(lambda L: float("과일" in L)).values
    out["pref_vegetable"] = fg.apply(lambda L: float(("채소·나물류" in L) or ("채소류" in L))).values
    txt = s["improvement_suggestions"].fillna("").astype(str)
    for col, pat in COMMENT_RULES.items():
        out[col] = txt.str.contains(pat, regex=True).astype(float).values
    out["improvement_text"] = txt.values
    return out

# =====================================================================
# 5. 통합
# =====================================================================

def build_dataset_frames(b, n, s):
    """이미 로드된 DataFrame 3종으로 통합 특징 데이터셋 생성 (API·CSV 공용)."""
    b = dedupe_latest(b)
    n = dedupe_latest(n) if len(n) else n.assign(key=pd.Series(dtype=str))
    s = dedupe_latest(s) if len(s) else s.assign(key=pd.Series(dtype=str))
    H = build_health(b)
    N = build_nutrition(n) if len(n) else build_nutrition(n.head(0))
    S = build_satisfaction(s) if len(s) else pd.DataFrame(columns=["key", "sat_overall", "sat_portion", "sat_quality",
                                                                    "n_food_groups", "pref_seafood", "pref_meat", "pref_fruit",
                                                                    "pref_vegetable", *COMMENT_RULES.keys(), "improvement_text"])
    df = H.merge(N, on="key", how="left").merge(S, on="key", how="left")
    df["has_nutrition"] = df["intake_total"].notna().astype(float)
    return df.set_index("key")


def build_dataset(basic_path, nutrition_path, satisfaction_path):
    return build_dataset_frames(read_csv_any(basic_path), read_csv_any(nutrition_path),
                                read_csv_any(satisfaction_path))

# =====================================================================
# 6. 전처리
# =====================================================================

def cluster_vars():
    return [v for vs in CLUSTER_BLOCKS.values() for v in vs]


def block_weights():
    w = {}
    for vs in CLUSTER_BLOCKS.values():
        for v in vs:
            w[v] = 1 / np.sqrt(len(vs))
    return pd.Series(w)


class Preprocessor:
    """학습 데이터 기준으로 평균·SD·KNN 참조셋을 고정 → 새 대상자 배정에 그대로 재사용."""

    def fit(self, X):
        from sklearn.impute import KNNImputer
        self.cols = list(X.columns)
        self.mean_ = X.mean()
        self.sd_ = X.std(ddof=0).replace(0, 1)
        Z = (X - self.mean_) / self.sd_
        self.imputer = KNNImputer(n_neighbors=KNN_NEIGHBORS, weights="distance").fit(Z)
        self.w_ = block_weights()[self.cols]
        return self

    def transform(self, X):
        Z = (X[self.cols] - self.mean_) / self.sd_
        Zi = pd.DataFrame(self.imputer.transform(Z), index=X.index, columns=self.cols)
        return Zi * self.w_, Zi

    def inverse_imputed(self, Zi):
        return Zi * self.sd_ + self.mean_

# =====================================================================
# 7. 군집 알고리즘 & 평가
# =====================================================================

def ward_labels(Xw, k):
    from scipy.cluster.hierarchy import linkage, fcluster
    Z = linkage(Xw, method="ward")
    return fcluster(Z, k, criterion="maxclust") - 1


def kmeans_labels(Xw, k, init=None):
    from sklearn.cluster import KMeans
    if init is not None:
        km = KMeans(n_clusters=k, init=init, n_init=1, random_state=RANDOM_STATE).fit(Xw)
    else:
        km = KMeans(n_clusters=k, n_init=50, random_state=RANDOM_STATE).fit(Xw)
    return km.labels_, km.cluster_centers_


def pam_labels(D, k, max_iter=100, seed=RANDOM_STATE):
    n = D.shape[0]
    medoids = [int(np.argmin(D.sum(axis=1)))]
    while len(medoids) < k:
        dmin = D[:, medoids].min(axis=1)
        gains = [(np.maximum(dmin - D[:, c], 0).sum() if c not in medoids else -1) for c in range(n)]
        medoids.append(int(np.argmax(gains)))
    cost = D[:, medoids].min(axis=1).sum()
    for _ in range(max_iter):
        improved = False
        for i in range(k):
            for c in range(n):
                if c in medoids:
                    continue
                trial = medoids.copy(); trial[i] = c
                tc = D[:, trial].min(axis=1).sum()
                if tc < cost - 1e-9:
                    medoids, cost, improved = trial, tc, True
        if not improved:
            break
    return np.argmin(D[:, medoids], axis=1)


def relabel_by_size(labels):
    order = pd.Series(labels).value_counts().index.tolist()
    mp = {old: new for new, old in enumerate(order)}
    return np.array([mp[l] for l in labels])


def bootstrap_jaccard(Xw, labels, k, n_boot=N_BOOT, seed=RANDOM_STATE):
    rng = np.random.default_rng(seed)
    n = len(labels)
    J = np.zeros((n_boot, k))
    for bi in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        uniq = np.unique(idx)
        bl = ward_labels(Xw[idx], k)
        first = {}
        for pos, i in enumerate(idx):
            first.setdefault(i, bl[pos])
        bl_u = np.array([first[i] for i in uniq])
        orig_u = labels[uniq]
        for c in range(k):
            A = set(uniq[orig_u == c])
            if not A:
                J[bi, c] = np.nan; continue
            best = 0
            for c2 in np.unique(bl_u):
                B = set(uniq[bl_u == c2])
                best = max(best, len(A & B) / len(A | B))
            J[bi, c] = best
    return np.nanmean(J, axis=0)


def evaluate_k(Xw):
    from sklearn.metrics import silhouette_score, calinski_harabasz_score, davies_bouldin_score, adjusted_rand_score
    from scipy.spatial.distance import cdist
    D1 = cdist(Xw, Xw, metric="cityblock")
    rows = []
    n = len(Xw)
    for k in K_RANGE:
        lw = ward_labels(Xw, k)
        lk, _ = kmeans_labels(Xw, k)
        lp = pam_labels(D1, k)
        jac = bootstrap_jaccard(Xw, lw, k)
        sizes = np.bincount(lw, minlength=k)
        rows.append({
            "k": k,
            "silhouette": silhouette_score(Xw, lw),
            "calinski_harabasz": calinski_harabasz_score(Xw, lw),
            "davies_bouldin": davies_bouldin_score(Xw, lw),
            "min_size": int(sizes.min()),
            "sizes": "/".join(map(str, sorted(sizes, reverse=True))),
            "jaccard_mean": float(np.mean(jac)),
            "jaccard_min": float(np.min(jac)),
            "ARI_ward_kmeans": adjusted_rand_score(lw, lk),
            "ARI_ward_pam": adjusted_rand_score(lw, lp),
        })
    res = pd.DataFrame(rows)
    min_size = max(5, int(np.ceil(MIN_CLUSTER_FRAC * n)))
    ok = res[(res.min_size >= min_size) & (res.jaccard_min >= MIN_JACCARD)]
    if len(ok):
        best_sil = ok.silhouette.max()
        cand = ok[ok.silhouette >= best_sil - 0.01]
        k_auto = int(cand.sort_values(["jaccard_mean", "k"], ascending=[False, True]).iloc[0].k)
        rule = f"최소군집≥{min_size}명 & 최소 Jaccard≥{MIN_JACCARD} 조건 만족 k 중 실루엣 최고"
    else:
        k_auto = int(res.sort_values("jaccard_mean", ascending=False).iloc[0].k)
        rule = "조건 만족 k 없음 → 부트스트랩 안정성 최고 k"
    res["selected_auto"] = res.k == k_auto
    return res, k_auto, rule


def final_clustering(Xw, k):
    lw = ward_labels(Xw, k)
    cent = np.vstack([Xw[lw == c].mean(axis=0) for c in range(k)])
    lk, cents = kmeans_labels(Xw, k, init=cent)
    lab = relabel_by_size(lk)
    cents = np.vstack([Xw[lab == c].mean(axis=0) for c in range(k)])
    return lab, cents, lw

# =====================================================================
# 8. 프로파일링
# =====================================================================

def profile_table(df, labels, k):
    from scipy.stats import kruskal, chi2_contingency
    vars_ = cluster_vars() + [v for v in PROFILE_ONLY if v in df.columns]
    rows = []
    for v in vars_:
        x = pd.to_numeric(df[v], errors="coerce")
        binary = set(x.dropna().unique()) <= {0.0, 1.0}
        rec = {"변수": VAR_LABELS.get(v, v), "code": v, "군집투입": v in cluster_vars(),
               "유형": "비율(%)" if binary else "평균±SD"}
        rec["전체"] = f"{100 * x.mean():.0f}" if binary else f"{x.mean():.1f}±{x.std():.1f}"
        groups = [x[labels == c].dropna() for c in range(k)]
        for c in range(k):
            g = groups[c]
            rec[f"C{c + 1}"] = (f"{100 * g.mean():.0f}" if binary else f"{g.mean():.1f}±{g.std():.1f}") if len(g) else "-"
        try:
            if binary:
                tab = pd.crosstab(labels[x.notna().values], x.dropna())
                p = chi2_contingency(tab)[1] if tab.shape[1] > 1 else np.nan
            else:
                p = kruskal(*[g for g in groups if len(g) > 0])[1]
        except ValueError:
            p = np.nan
        rec["p"] = p
        rec["결측(n)"] = int(x.isna().sum())
        rows.append(rec)
    return pd.DataFrame(rows)


def cluster_signature(Zi, labels, k, top=5):
    sig = []
    M = Zi.groupby(labels).mean()
    for c in range(k):
        s = M.loc[c].sort_values(key=np.abs, ascending=False)
        parts = [f"{VAR_LABELS.get(v, v)} {'↑' if s[v] > 0 else '↓'}({s[v]:+.1f})" for v in s.index[:top] if abs(s[v]) >= 0.4]
        sig.append({"cluster": f"C{c + 1}", "n": int((labels == c).sum()), "주요 특징(z)": ", ".join(parts)})
    return pd.DataFrame(sig)

# =====================================================================
# 9. 그림
# =====================================================================

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
MARKERS = ["o", "s", "^", "D", "v", "P"]
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"


def setup_fonts():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for cand in ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans KR", "Noto Sans CJK KR", "Noto Sans CJK JP"]:
        if any(cand == f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = cand
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
                         "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.dpi": 200,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def fig_k_selection(res, k_sel, path):
    plt = setup_fonts()
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.3))
    panels = [("silhouette", "실루엣 (높을수록 좋음)"), ("jaccard_min", "부트스트랩 최소 Jaccard"),
              ("ARI_ward_kmeans", "Ward–K-means 일치도 (ARI)")]
    for ax, (col, title) in zip(axes, panels):
        ax.plot(res.k, res[col], color=SERIES[0], lw=2, marker="o", ms=7, mec="#fcfcfb", mew=2)
        sel = res[res.k == k_sel]
        ax.plot(sel.k, sel[col], marker="o", ms=11, color=SERIES[1], mec="#fcfcfb", mew=2, ls="none")
        ax.set_title(title, fontsize=10, loc="left")
        ax.set_xticks(list(res.k)); ax.set_xlabel("군집 수 k")
        ax.grid(axis="y", color=GRID, lw=0.6)
        if col == "jaccard_min":
            ax.axhline(MIN_JACCARD, color=MUTED, lw=1, ls="--")
            ax.set_ylim(0, 1)
        else:
            ax.set_ylim(0, max(1.0 if col != "silhouette" else 0.5, res[col].max() * 1.15))
    fig.suptitle(f"k 선택 지표 (주황 = 선택된 k={k_sel})", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def fig_heatmap(Zi, labels, k, path, names=None):
    plt = setup_fonts()
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("div", ["#1c5cab", "#86b6ef", "#f0efec", "#f0a09f", "#c62f2e"])
    M = Zi.groupby(labels).mean().T
    M.index = [VAR_LABELS.get(v, v) for v in M.index]
    cols = [f"C{c + 1}" + (f"\n{names[c]}" if names else "") + f"\n(n={(labels == c).sum()})" for c in range(k)]
    fig, ax = plt.subplots(figsize=(1.6 * k + 3.2, 0.36 * len(M) + 1.2))
    im = ax.imshow(M.values, cmap=cmap, vmin=-1.5, vmax=1.5, aspect="auto")
    ax.set_xticks(range(k)); ax.set_xticklabels(cols, fontsize=9, color=INK)
    ax.set_yticks(range(len(M))); ax.set_yticklabels(M.index, fontsize=9, color=INK2)
    ax.tick_params(length=0)
    for i in range(M.shape[0]):
        for j in range(k):
            v = M.values[i, j]
            ax.text(j, i, f"{v:+.1f}", ha="center", va="center", fontsize=8,
                    color="#ffffff" if abs(v) > 1.0 else INK)
    pos = 0
    for vs in list(CLUSTER_BLOCKS.values())[:-1]:
        pos += len(vs); ax.axhline(pos - 0.5, color="#fcfcfb", lw=3)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("전체 평균 대비 표준점수 (z)", color=INK2, fontsize=9); cb.outline.set_visible(False)
    ax.set_title("군집별 투입 변수 프로파일", loc="left", fontsize=11)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def fig_pca(Xw, labels, k, path, names=None):
    plt = setup_fonts()
    from sklearn.decomposition import PCA
    p = PCA(n_components=2, random_state=RANDOM_STATE).fit(Xw)
    P = p.transform(Xw)
    fig, ax = plt.subplots(figsize=(6.4, 5))
    for c in range(k):
        m = labels == c
        lab = f"C{c + 1}" + (f" {names[c]}" if names else "") + f" (n={m.sum()})"
        ax.scatter(P[m, 0], P[m, 1], s=52, color=SERIES[c % len(SERIES)], marker=MARKERS[c % len(MARKERS)],
                   edgecolor="#fcfcfb", linewidth=1.5, label=lab, zorder=3)
        cx, cy = P[m].mean(axis=0)
        ax.annotate(f"C{c + 1}", (cx, cy), fontsize=12, fontweight="bold", color=INK, ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.25", fc="#fcfcfb", ec=SERIES[c % len(SERIES)], lw=1.5), zorder=4)
    ev = p.explained_variance_ratio_ * 100
    ax.set_xlabel(f"PC1 ({ev[0]:.0f}%)"); ax.set_ylabel(f"PC2 ({ev[1]:.0f}%)")
    ax.grid(color=GRID, lw=0.6); ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9, loc="best")
    ax.set_title("주성분 공간의 군집 분포", loc="left", fontsize=11)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)
    load = pd.DataFrame(p.components_.T, index=[VAR_LABELS.get(c, c) for c in Xw_cols_cache], columns=["PC1", "PC2"])
    return load


def fig_dendrogram(Xw, k, path):
    plt = setup_fonts()
    from scipy.cluster.hierarchy import linkage, dendrogram
    Z = linkage(Xw, method="ward")
    fig, ax = plt.subplots(figsize=(10, 3.6))
    thr = Z[-(k - 1), 2] - 1e-9 if k > 1 else None
    dendrogram(Z, ax=ax, color_threshold=thr, above_threshold_color=MUTED, no_labels=True)
    if thr:
        ax.axhline(thr, color=SERIES[1], lw=1.2, ls="--")
    ax.set_ylabel("Ward 거리"); ax.set_title(f"계층적 군집 덴드로그램 (점선 = k={k} 절단)", loc="left", fontsize=11)
    ax.spines["bottom"].set_visible(False)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)


def fig_key_bars(df, labels, k, path, names=None):
    plt = setup_fonts()
    items = [("mna_sf", "MNA-SF (점)"), ("kmbi_pct", "K-MBI (%)"), ("mmse", "K-MMSE-2 (점)"),
             ("intake_total", "전체 섭취율 (%)"), ("intake_main", "주찬 섭취율 (%)"), ("sat_overall", "급식 만족 (1–5)")]
    fig, axes = plt.subplots(2, 3, figsize=(11, 6))
    rng = np.random.default_rng(0)
    for ax, (v, t) in zip(axes.ravel(), items):
        x = pd.to_numeric(df[v], errors="coerce")
        for c in range(k):
            g = x[labels == c].dropna()
            ax.bar(c, g.mean(), width=0.62, color=SERIES[c % len(SERIES)], alpha=0.9, zorder=2)
            ax.scatter(c + rng.uniform(-0.18, 0.18, len(g)), g, s=12, color=INK, alpha=0.45, zorder=3, linewidth=0)
            ax.text(c, g.mean(), f"{g.mean():.1f}", ha="center", va="bottom", fontsize=8.5, color=INK,
                    bbox=dict(fc="#fcfcfb", ec="none", pad=1), zorder=4)
        ax.set_xticks(range(k)); ax.set_xticklabels([f"C{c + 1}" for c in range(k)])
        ax.set_title(t, loc="left", fontsize=10); ax.grid(axis="y", color=GRID, lw=0.6); ax.set_axisbelow(True)
    fig.suptitle("핵심 지표의 군집별 비교 (막대 = 평균, 점 = 개인, 대치값 제외)", x=0.01, ha="left", fontsize=11)
    fig.tight_layout(); fig.savefig(path, bbox_inches="tight"); plt.close(fig)


Xw_cols_cache = []

# =====================================================================
# 10. 실행
# =====================================================================

def run_fit(args, df=None):
    """args.out 에 결과 저장. df 를 주면 CSV 대신 그 데이터셋을 사용(API/학습 스크립트용)."""
    global Xw_cols_cache
    os.makedirs(args.out, exist_ok=True)
    if df is None:
        df = build_dataset(args.basic, args.nutrition, args.satisfaction)
    cv = cluster_vars()
    Xw_cols_cache = cv
    X = df[cv].apply(pd.to_numeric, errors="coerce")

    dq = pd.DataFrame({"변수": [VAR_LABELS.get(c, c) for c in cv], "code": cv,
                       "결측(n)": X.isna().sum().values, "결측(%)": (100 * X.isna().mean()).round(1).values})
    row_missing = X.isna().sum(axis=1)
    excluded = row_missing[row_missing > len(cv) * 0.5].index.tolist()
    if excluded:
        print(f"[제외] 투입변수 50% 이상 결측: {excluded}")
    Xf = X.drop(index=excluded)
    pre = Preprocessor().fit(Xf)
    Xw_df, Zi = pre.transform(Xf)
    Xw = Xw_df.values
    dff = df.drop(index=excluded)

    res, k_auto, rule = evaluate_k(Xw)
    k = args.k or k_auto
    labels, cents, ward_lab = final_clustering(Xw, k)

    from sklearn.metrics import silhouette_samples, adjusted_rand_score
    sil = silhouette_samples(Xw, labels)
    cent_dist = np.linalg.norm(Xw[:, None, :] - cents[None, :, :], axis=2)
    srt = np.sort(cent_dist, axis=1)

    sens = []
    m = dff["has_nutrition"].values == 1
    if m.sum() > k * 3 and (~m).sum() > 0:
        l2, _, _ = final_clustering(Xw[m], k)
        sens.append({"분석": "영양조사 완료자만 재군집", "n": int(m.sum()), "ARI(주분석 대비)": adjusted_rand_score(labels[m], l2)})
    keep = [i for i, c in enumerate(cv) if c not in CLUSTER_BLOCKS.get("인지·정서", [])]
    l3, _, _ = final_clustering(Xw[:, keep], k)
    sens.append({"분석": "인지·정서 블록 제외", "n": len(labels), "ARI(주분석 대비)": adjusted_rand_score(labels, l3)})
    l4, _, _ = final_clustering(Zi.values, k)
    sens.append({"분석": "블록 가중 없음(변수 동일 가중)", "n": len(labels), "ARI(주분석 대비)": adjusted_rand_score(labels, l4)})
    sens.append({"분석": "Ward 단독 (정제 전)", "n": len(labels), "ARI(주분석 대비)": adjusted_rand_score(labels, ward_lab)})
    sens = pd.DataFrame(sens)

    names = None
    if getattr(args, "names", None):
        names = [s.strip() for s in args.names.split(",")]
        if len(names) != k:
            names = None

    assign = dff[["elderly_id", "nursing_home_id"]].copy()
    assign["cluster"] = [f"C{l + 1}" for l in labels]
    if names:
        assign["cluster_name"] = [names[l] for l in labels]
    assign["silhouette"] = sil.round(3)
    assign["centroid_margin"] = (srt[:, 1] - srt[:, 0]).round(3)
    assign["imputed_vars"] = X.drop(index=excluded).isna().apply(lambda r: ",".join([c for c in cv if r[c]]), axis=1)
    imputed_raw = pre.inverse_imputed(Zi)
    prof = profile_table(dff, labels, k)
    sig = cluster_signature(Zi, labels, k)

    feat_out = dff.drop(columns=["improvement_text"], errors="ignore").copy()
    feat_out.insert(0, "cluster", assign["cluster"])
    for c in cv:
        feat_out[c + "_imputed"] = imputed_raw[c].round(2)
    feat_out.to_csv(os.path.join(args.out, "features_with_clusters.csv"), encoding="utf-8-sig")
    assign.to_csv(os.path.join(args.out, "cluster_assignments.csv"), encoding="utf-8-sig")
    res.to_csv(os.path.join(args.out, "k_selection.csv"), index=False, encoding="utf-8-sig")
    prof.to_csv(os.path.join(args.out, "cluster_profile.csv"), index=False, encoding="utf-8-sig")

    if not getattr(args, "no_figures", False):
        fig_k_selection(res, k, os.path.join(args.out, "fig1_k_selection.png"))
        fig_heatmap(Zi, labels, k, os.path.join(args.out, "fig2_profile_heatmap.png"), names)
        load = fig_pca(Xw_df, labels, k, os.path.join(args.out, "fig3_pca.png"), names)
        fig_dendrogram(Xw, k, os.path.join(args.out, "fig4_dendrogram.png"))
        fig_key_bars(dff, labels, k, os.path.join(args.out, "fig5_key_indicators.png"), names)

        with pd.ExcelWriter(os.path.join(args.out, "clustering_results.xlsx")) as xw:
            pd.DataFrame({"항목": ["분석 대상(n)", "제외(n)", "선택 k", "k 자동선택 규칙", "자동선택 k", "최종 군집 크기"],
                          "값": [len(labels), len(excluded), k, rule, k_auto,
                                " / ".join(f"C{c + 1}={int((labels == c).sum())}" for c in range(k))]}
                         ).to_excel(xw, sheet_name="요약", index=False)
            sig.to_excel(xw, sheet_name="군집 특징", index=False)
            prof.to_excel(xw, sheet_name="군집 프로파일", index=False)
            res.to_excel(xw, sheet_name="k 선택", index=False)
            sens.to_excel(xw, sheet_name="민감도 분석", index=False)
            dq.to_excel(xw, sheet_name="결측 현황", index=False)
            assign.to_excel(xw, sheet_name="개인별 배정")
            load.round(3).to_excel(xw, sheet_name="PCA 적재량")
            txt = dff[["elderly_id", "improvement_text"]].copy(); txt.insert(1, "cluster", assign["cluster"])
            txt.sort_values("cluster").to_excel(xw, sheet_name="급식 개선 의견", index=False)
    import joblib
    model = {"pre": pre, "centroids": cents, "k": k, "names": names, "cluster_vars": cv,
             "blocks": CLUSTER_BLOCKS, "n_train": len(labels),
             "train_relative_margin": ((srt[:, 1] - srt[:, 0]) / np.maximum(srt[:, 1], 1e-9)).tolist()}
    joblib.dump(model, os.path.join(args.out, "model.joblib"))
    summary = {"n": int(len(labels)), "excluded": excluded, "k": int(k), "k_auto": int(k_auto), "rule": rule,
               "sizes": {f"C{c + 1}": int((labels == c).sum()) for c in range(k)},
               "silhouette_mean": float(sil.mean()),
               "n_negative_silhouette": int((sil < 0).sum()),
               "sensitivity": sens.to_dict("records")}
    with open(os.path.join(args.out, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=float)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=float))
    print(res.round(3).to_string())
    print(sig.to_string())
    return {"model": model, "labels": labels, "index": dff.index, "summary": summary, "signature": sig}


def run_assign(args):
    import joblib
    os.makedirs(args.out, exist_ok=True)
    M = joblib.load(args.model)
    df = build_dataset(args.basic, args.nutrition, args.satisfaction)
    X = df[M["cluster_vars"]].apply(pd.to_numeric, errors="coerce")
    Xw, _ = M["pre"].transform(X)
    d = np.linalg.norm(Xw.values[:, None, :] - M["centroids"][None, :, :], axis=2)
    lab = d.argmin(axis=1); srt = np.sort(d, axis=1)
    out = df[["elderly_id", "nursing_home_id"]].copy()
    out["cluster"] = [f"C{l + 1}" for l in lab]
    if M.get("names"):
        out["cluster_name"] = [M["names"][l] for l in lab]
    out["centroid_margin"] = (srt[:, 1] - srt[:, 0]).round(3)
    out["n_missing_vars"] = X.isna().sum(axis=1).values
    out.to_csv(os.path.join(args.out, "assigned_by_pilot_model.csv"), encoding="utf-8-sig")
    print(out["cluster"].value_counts().sort_index().to_string())


def main():
    ap = argparse.ArgumentParser(description="블루푸드 고령자 유형분류 파이프라인")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fit", "assign"):
        p = sub.add_parser(name)
        p.add_argument("--basic", required=True)
        p.add_argument("--nutrition", required=True)
        p.add_argument("--satisfaction", required=True)
        p.add_argument("--out", default="results")
        if name == "fit":
            p.add_argument("--k", type=int, default=None)
            p.add_argument("--names", default=None)
        else:
            p.add_argument("--model", required=True)
    args = ap.parse_args()
    run_fit(args) if args.cmd == "fit" else run_assign(args)


if __name__ == "__main__":
    main()
