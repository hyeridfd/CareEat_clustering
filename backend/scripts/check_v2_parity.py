# -*- coding: utf-8 -*-
"""
유형 모델 v2 배포 전 점검 — 앱 계산값이 학습 자료(통합 섭취 파일)와 맞는지, 배정이 재현되는지

  python scripts/check_v2_parity.py --intake "대상자별_영양섭취량.xlsx" [--model v2-mfa-n72]

1) Supabase 의 조사 행으로 앱과 똑같이 특징을 만든다 (engine.build_features)
2) 학습 72명에 대해 체중당 에너지·단백질·섭취율을 통합 섭취 파일 값과 비교
3) v2 모델 배정이 학습 군집과 얼마나 일치하는지 출력 (불일치 대상자 목록 포함)
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from care import engine  # noqa: E402
from care.data import fetch_all, fetch_surveys  # noqa: E402
from dependencies import get_supabase  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", required=True, help="통합 섭취 파일 (대상자별_영양섭취량.xlsx)")
    ap.add_argument("--model", default="v2-mfa-n72")
    a = ap.parse_args()

    sb = get_supabase()
    b, n, s = fetch_surveys(sb)
    forms = {r["id"]: r.get("meal_form") for r in fetch_all(sb, "elderly_residents")}
    df = engine.build_features(b, n, s, meal_forms=forms)
    model = engine.load_model(a.model)
    import joblib
    bundle = joblib.load(engine.MODEL_DIR / a.model / "model.joblib")
    train = pd.Series(bundle["train_labels"], index=bundle["train_ids"])

    day = pd.read_excel(a.intake, sheet_name="대상자별_하루평균").set_index("대상자ID")
    common = df.index.intersection(train.index)
    x = df.loc[common]
    eid = x["elderly_id"].astype(str)
    ref_e = day.loc[eid, "에너지(kcal)"].values / x["weight_kg"].values
    ref_p = day.loc[eid, "단백질(g)"].values / x["weight_kg"].values
    print(f"학습 대상 {len(train)}명 중 앱 데이터에서 찾은 {len(common)}명")
    print(f"  섭취 계산 방식: {x['nutrition'].apply(lambda v: (v or {}).get('method') if isinstance(v, dict) else None).value_counts(dropna=False).to_dict()}")
    for name, app, ref in [("체중당 에너지", x["energy_kcal_kg"].values, ref_e),
                           ("체중당 단백질", x["protein_g_kg"].values, ref_p)]:
        ok = ~np.isnan(app) & ~np.isnan(ref)
        r = np.corrcoef(app[ok], ref[ok])[0, 1] if ok.sum() > 2 else np.nan
        print(f"  {name}: 앱 평균 {np.nanmean(app):.2f} / 학습 {np.nanmean(ref):.2f}, 상관 {r:.3f}, 결측 {int((~ok).sum())}명")

    res = model.assign(df)
    pred = res.loc[common, "type_code"].str[1:].astype(int) - 1
    agree = (pred.values == train.loc[common].values)
    print(f"  배정 일치율: {agree.mean():.1%} ({agree.sum()}/{len(common)})")
    if (~agree).any():
        bad = pd.DataFrame({"학습": [f"C{i + 1}" for i in train.loc[common][~agree]],
                            "앱": res.loc[common, "type_code"][~agree].values,
                            "경계": res.loc[common, "is_borderline"][~agree].values},
                           index=common[~agree])
        print(bad.to_string())
    print("\n전체 배정 분포:", res["type_code"].value_counts().sort_index().to_dict(),
          "| 경계 사례", int(res["is_borderline"].sum()))


if __name__ == "__main__":
    main()
