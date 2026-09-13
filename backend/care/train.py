# -*- coding: utf-8 -*-
"""
유형 모델 학습·등록 (모델 고도화 루프)

  # A) 파일럿에서 이미 만든 model.joblib 등록
  python -m care.train register --version v1-pilot-n55 --model ../results/model.joblib \
      --names "양호 기능·양호 섭취형,섭취 저조·급식 불만족형,저작·연하곤란 고위험형" --activate

  # B) Supabase 에 쌓인 전체 데이터로 재학습 → 이전 모델과 라벨 매칭 → 등록
  python -m care.train fit --version v2-n200 --k 3 --activate
  #    (CSV 로 학습하려면 --basic/--nutrition/--satisfaction 지정)

재학습 시 새 군집을 이전 활성 모델의 유형 코드에 헝가리안 매칭으로 맞춰
C1/C2/C3 의미가 버전 간에 유지되도록 한다(유형명·보호자 표현·위험가중도 승계).
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from care import bluefood_cluster as bc  # noqa: E402
from care import engine  # noqa: E402

DEFAULT_META = {  # 파일럿(n=55) 해석 기준 기본값 — 재학습 후 반드시 검토
    "양호 기능·양호 섭취형": {"guardian_label": "안정 관리군", "risk_weight": 0,
                          "description": "신체기능과 식사 섭취가 양호한 유형"},
    "섭취 저조·급식 불만족형": {"guardian_label": "식사 관심군", "risk_weight": 10,
                          "description": "식사량이 적고 급식 만족도가 낮은 유형"},
    "저작·연하곤란 고위험형": {"guardian_label": "집중 돌봄군", "risk_weight": 20,
                          "description": "씹기·삼키기 어려움과 영양 위험이 큰 유형"},
}


def make_meta(k, names, parent_meta=None):
    """유형 메타(이름·보호자 표현·위험가중·설명). 이전 모델 메타를 코드 기준으로 승계."""
    meta = {}
    for i in range(k):
        code = f"C{i + 1}"
        prev = dict((parent_meta or {}).get(code, {}))
        name = (names[i] if names and i < len(names) and names[i] else None) or prev.get("name") or code
        base = DEFAULT_META.get(name, {})
        meta[code] = {
            "name": name,
            "guardian_label": prev.get("guardian_label") or base.get("guardian_label") or name,
            "risk_weight": prev.get("risk_weight", base.get("risk_weight", 0)),
            "description": prev.get("description") or base.get("description", ""),
        }
    return meta


def get_sb():
    from dependencies import get_supabase
    return get_supabase()


def register(sb, version, k, meta, n_train, parent=None, mapping=None, activate=False, notes=None):
    if sb is None:
        return
    row = {"version": version, "k": int(k), "type_meta": meta, "n_train": int(n_train) if n_train else None,
           "parent_version": parent, "label_mapping": mapping, "notes": notes}
    sb.table("type_models").upsert(row).execute()
    if activate:
        sb.table("type_models").update({"is_active": False}).neq("version", version).execute()
        sb.table("type_models").update({"is_active": True}).eq("version", version).execute()


def cmd_register(a):
    import joblib
    engine._install_pickle_shim()
    bundle = joblib.load(a.model)
    names = [s.strip() for s in a.names.split(",")] if a.names else bundle.get("names")
    bundle["names"] = names
    d = engine.MODEL_DIR / a.version
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, d / "model.joblib")
    meta = make_meta(bundle["k"], names)
    (d / "type_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    sb = None if a.no_db else get_sb()
    register(sb, a.version, bundle["k"], meta, bundle.get("n_train"), activate=a.activate, notes=a.notes)
    print(f"등록 완료: {d}  (활성화={a.activate})")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def match_labels(new_lab, old_lab, k_new, k_old):
    """새 군집 → 이전 유형 코드 헝가리안 매칭 (겹치는 인원 최대화)."""
    from scipy.optimize import linear_sum_assignment
    from sklearn.metrics import adjusted_rand_score
    C = np.zeros((k_new, k_old))
    for a, b in zip(new_lab, old_lab):
        C[a, b] += 1
    r, c = linear_sum_assignment(-C)
    perm = {}
    used = set()
    for i, j in zip(r, c):
        perm[i] = j
        used.add(j)
    nxt = k_old
    for i in range(k_new):  # k 가 늘었으면 남는 군집은 새 코드
        if i not in perm:
            perm[i] = nxt; nxt += 1
    return perm, float(adjusted_rand_score(new_lab, old_lab)), C


def cmd_fit(a):
    import joblib
    sb = None if a.no_db else get_sb()
    if a.basic:
        df = bc.build_dataset(a.basic, a.nutrition, a.satisfaction)
    else:
        from care.data import fetch_surveys
        b, n, s = fetch_surveys(sb)
        df = engine.build_features(b, n, s)
    print(f"학습 데이터: n={len(df)}")
    out = engine.MODEL_DIR / a.version
    report = out / "report"
    args = SimpleNamespace(out=str(report), k=a.k, names=a.names, no_figures=a.no_figures)
    res = bc.run_fit(args, df=df)
    model, labels = res["model"], res["labels"]
    k = model["k"]

    parent = None
    mapping = None
    parent_meta = None
    try:
        parent = a.parent or engine.active_version(sb)
    except RuntimeError:
        parent = None
    if parent and parent != a.version and (engine.MODEL_DIR / parent / "model.joblib").exists():
        old = engine.load_model(parent)
        old_codes = old.assign(df.loc[res["index"]])["type_code"].str[1:].astype(int).values - 1
        perm, ari, C = match_labels(labels, old_codes, k, old.k)
        # 이전 코드 순서대로 새 군집 정렬 (k 가 줄면 빈 코드는 건너뜀)
        targets = sorted(perm.values())
        inv = {tgt: new_i for new_i, tgt in perm.items()}
        order = [inv[t] for t in targets]
        model["centroids"] = np.asarray(model["centroids"])[order]
        if model.get("names"):
            model["names"] = [model["names"][o] for o in order]
        mapping = {"from_parent": parent, "ARI_vs_parent": round(ari, 3),
                   "new_cluster_to_parent_code": {f"new{i + 1}": f"C{perm[i] + 1}" for i in range(k)},
                   "code_to_parent_code": {f"C{pos + 1}": f"C{t + 1}" for pos, t in enumerate(targets)},
                   "overlap_matrix": C.astype(int).tolist()}
        parent_meta = {f"C{pos + 1}": old.meta.get(f"C{t + 1}", {}) for pos, t in enumerate(targets)}
        print(f"이전 모델({parent})과 라벨 매칭: ARI={ari:.3f}, {mapping['new_cluster_to_parent_code']}")
        if not model.get("names"):
            model["names"] = [old.type_info(f"C{t + 1}")["name"] if t < old.k else f"C{pos + 1}"
                              for pos, t in enumerate(targets)]
    joblib.dump(model, out / "model.joblib")
    meta = make_meta(k, model.get("names"), parent_meta)
    (out / "type_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    register(sb, a.version, k, meta, model["n_train"], parent, mapping, a.activate, a.notes)
    print(f"저장: {out}  (활성화={a.activate})")
    print("※ type_meta.json 의 유형명·보호자 표현·risk_weight 를 검토 후 필요 시 수정하세요.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--version", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--names")
    f = sub.add_parser("fit")
    f.add_argument("--version", required=True)
    f.add_argument("--k", type=int)
    f.add_argument("--names")
    f.add_argument("--parent", help="라벨을 맞출 이전 모델 버전 (기본: 현재 활성)")
    f.add_argument("--basic"); f.add_argument("--nutrition"); f.add_argument("--satisfaction")
    f.add_argument("--no-figures", action="store_true")
    for p in (r, f):
        p.add_argument("--activate", action="store_true")
        p.add_argument("--notes")
        p.add_argument("--no-db", action="store_true", help="Supabase 등록 생략 (로컬 테스트)")
    a = ap.parse_args()
    cmd_register(a) if a.cmd == "register" else cmd_fit(a)


if __name__ == "__main__":
    main()
