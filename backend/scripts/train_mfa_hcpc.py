# -*- coding: utf-8 -*-
"""
유형 모델 v2 (MFA-HCPC) 학습 → model.joblib

  python scripts/train_mfa_hcpc.py \\
      --basic "basic_survey_rows (8).xlsx" \\
      --intake "대상자별_영양섭취량.xlsx" \\
      --out models_build/v2-mfa-n72 --k 3

  이어서 등록·활성화:
  python -m care.train register --version v2-mfa-n72 --model models_build/v2-mfa-n72/model.joblib --activate

투입 변수 (3개 영역 9개, 앱 변수명)
  영양 상태   : mna_sf, bmi
  영양소 섭취 : energy_kcal_kg, protein_g_kg, intake_total
  섭식 기능   : chewing_difficulty, swallowing_difficulty, texture_level, eating_dependence
설문 점수는 앱 채점(bluefood_cluster.build_health)을 그대로 쓰고,
섭취량은 통합 섭취 파일('대상자별_하루평균' 에너지·단백질 ÷ 체중, '메뉴별_상세' 배식량 가중 섭취율)을 쓴다.
앱은 같은 계산(care/nutrition.py 시설별 산출)으로 신규 대상자의 섭취량을 구한다.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from care import bluefood_cluster as bc  # noqa: E402
from care.mfa import MFAPreprocessor, ward_kmeans  # noqa: E402

GROUPS = {
    "영양 상태": ["mna_sf", "bmi"],
    "영양소 섭취": ["energy_kcal_kg", "protein_g_kg", "intake_total"],
    "섭식 기능": ["chewing_difficulty", "swallowing_difficulty", "texture_level", "eating_dependence"],
}
NAMES = ["영양 양호형", "저체중·영양위험형", "저작곤란·조정식·식사보조형"]


def read_any(path):
    p = str(path)
    return pd.read_excel(p) if p.lower().endswith((".xlsx", ".xls")) else bc.read_csv_any(p)


def build_training(basic_path, intake_path):
    b = read_any(basic_path)
    for c in ("elderly_id", "nursing_home_id"):
        b[c] = b[c].astype(str).str.strip()
    b["key"] = bc.make_key(b)
    b = bc.dedupe_latest(b)
    H = bc.build_health(b).set_index("key")
    H["weight_kg"] = bc.to_num(b.set_index("key")["weight"]).reindex(H.index)
    H["eid"] = H.index.str.split("|").str[1]

    day = pd.read_excel(intake_path, sheet_name="대상자별_하루평균")
    day["대상자ID"] = day["대상자ID"].astype(str).str.strip()
    day = day.set_index("대상자ID")
    m = pd.read_excel(intake_path, sheet_name="메뉴별_상세")
    m = m[m["요약집계_포함여부"] != "제외"].copy()
    m["대상자ID"] = m["대상자ID"].astype(str).str.strip()
    m["rate"] = pd.to_numeric(m["섭취율(%)"], errors="coerce")
    m = m[m["rate"].notna() & m["배식량(g)"].notna()]
    rate = m.groupby("대상자ID").apply(lambda g: 100 * (g["배식량(g)"] * g["rate"] / 100).sum() / g["배식량(g)"].sum())

    H = H[H["eid"].isin(day.index)].copy()
    H["energy_kcal_kg"] = day.loc[H["eid"], "에너지(kcal)"].values / H["weight_kg"].values
    H["protein_g_kg"] = day.loc[H["eid"], "단백질(g)"].values / H["weight_kg"].values
    H["intake_total"] = rate.reindex(H["eid"]).values
    cols = [v for vs in GROUPS.values() for v in vs]
    return H.dropna(subset=cols), cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basic", required=True)
    ap.add_argument("--intake", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--ncp", type=int, default=5)
    ap.add_argument("--names", default=",".join(NAMES))
    a = ap.parse_args()

    df, cols = build_training(a.basic, a.intake)
    pre = MFAPreprocessor().fit(df[cols], GROUPS, a.ncp)
    coords, _ = pre.transform(df[cols])
    C = coords.values
    lab = ward_kmeans(C, a.k)
    cent = np.vstack([C[lab == c].mean(0) for c in range(a.k)])
    d = np.linalg.norm(C[:, None, :] - cent[None], axis=2)
    o = np.sort(d, axis=1)
    rel = ((o[:, 1] - o[:, 0]) / np.maximum(o[:, 1], 1e-9)).tolist()
    assert (d.argmin(1) == lab).all(), "학습 자료 재배정이 군집 결과와 다릅니다"

    names = [s.strip() for s in a.names.split(",")]
    bundle = {"pre": pre, "centroids": cent, "k": a.k, "names": names, "cluster_vars": cols,
              "blocks": GROUPS, "n_train": int(len(df)), "train_relative_margin": rel,
              "method": "MFA-HCPC (Ward + k-means 정제, 5개 차원)",
              "train_ids": df.index.tolist(), "train_labels": lab.tolist()}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import joblib
    joblib.dump(bundle, out / "model.joblib")
    summary = {"n_train": int(len(df)), "facilities": df["nursing_home_id"].value_counts().to_dict(),
               "sizes": np.bincount(lab).tolist(), "explained_pct": np.round(pre.explained(), 1).tolist(),
               "group_weights": {g: round(float(pre.w_[vs[0]]), 3) for g, vs in GROUPS.items()},
               "cluster_means": df.assign(c=[f"C{i + 1}" for i in lab]).groupby("c")[cols].mean().round(2).to_dict("index")}
    (out / "train_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("저장:", out / "model.joblib")


if __name__ == "__main__":
    main()
