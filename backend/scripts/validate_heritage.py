# -*- coding: utf-8 -*-
"""[검증] 헤리티지 실제 제공 식단 vs Care-Eat 식단 — 어르신별 목표 영양성분에 얼마나 맞는가

    python -m scripts.validate_heritage --xlsx "C:\\...\\헤리티지_영양성분_v.2.xlsx" --home 헤리티지
    python -m scripts.validate_heritage --xlsx ... --home 헤리티지 --run <diet_runs.id>   # 이미 돌린 설계 결과 사용
    python -m scripts.validate_heritage --xlsx ... --home 헤리티지 --seeds 7,11,23,31,47 --design-seeds 42,43,44
        # 반복 검증: 설계 시드 3개 × 날짜 추출 5개 = 15회 → 평균과 범위 (scripts/validate_heritage_repeat.xlsx)

  비교하는 식단 (모두 '배식량' 기준 — 섭취율은 반영하지 않음)
    (A) 헤리티지 제공 식단   엑셀 '어르신별_메뉴별' — 조사 5일, 어르신별 배식량의 영양성분
                             (엑셀 값은 섭취량 기준이라 배식량 ÷ 섭취량 비율로 되돌림. 섭취량 0 인 칸은 같은 식약처 식품의 g당 값 사용)
    (B) Care-Eat 공통 식단   28일 중 무작위 5일, 개인화 전(1인분 그대로)
    (C) Care-Eat 개인화 식단 같은 5일, 대체찬·식사형태·배식량 조정 후 (어르신별)
  목표 = Care-Eat 개인 영양 기준 (에이전트 종합 결과, 끼니 기준 × 3 = 하루)
    열량: 목표 ±10%  ·  단백질 ≥ 하한  ·  나트륨 ≤ 상한  ·  식이섬유 ≥ 하한  ·  칼륨 ≥ 하한(고혈압)
    지방(하한~상한)·포화지방·당류·탄수화물(55~65%)은 그 날 실제 열량 대비 비율(%E)로 판정
  하루 적합도 = 맞은 항목 수 ÷ 해당 항목 수 (0~100)  →  어르신별 5일 평균  →  (C) vs (A) 대응 비교 (Wilcoxon)

  출력: scripts/validate_heritage_result.xlsx (식별번호만 — 이름은 넣지 않음)
  주의: 헤리티지는 식약처 음식 DB, Care-Eat 은 메뉴 풀 영양값을 쓴다 (DB 차이는 한계로 보고)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

NUT = {"energy": "에너지(kcal)", "protein": "단백질(g)", "fat": "지방(g)", "carb": "탄수화물(g)", "sugar": "당류(g)",
       "fiber": "식이섬유(g)", "potassium": "칼륨(mg)", "sodium": "나트륨(mg)", "sat_fat": "포화지방산(g)"}
SRV = {"energy": "예상열량", "protein": "예상단백질", "fat": "예상지방", "carb": "예상탄수화물", "sugar": "예상당류",
       "fiber": "예상식이섬유", "potassium": "예상칼륨", "sodium": "예상나트륨", "sat_fat": "예상포화지방"}
KCAL = {"fat": 9, "sat_fat": 9, "sugar": 4, "carb": 4}
LABEL = {"energy": "열량(목표±10%)", "protein": "단백질", "sodium": "나트륨", "fiber": "식이섬유", "potassium": "칼륨",
         "fat_min": "지방 하한(%E)", "fat_max": "지방 상한(%E)", "sat_fat": "포화지방(%E)", "sugar": "당류(%E)",
         "carb": "탄수화물 55~65%E"}
SLOTS = ("밥", "국", "주찬", "부찬1", "부찬2", "김치")
CAT = {"밥": "밥", "국": "국", "주찬": "주찬", "부찬1": "부찬", "부찬2": "부찬", "김치": "김치"}


# ─────────────────────────── (A) 헤리티지 ───────────────────────────
def find_xlsx(path: str) -> str:
    """폴더를 주면 '어르신별_메뉴별' 시트가 있는 엑셀 중 가장 최근 파일"""
    p = Path(path)
    if p.is_file():
        return str(p)
    if not p.is_dir():
        raise SystemExit(f"파일·폴더가 없습니다: {path}")
    import openpyxl
    found = []
    for f in sorted(p.glob("*.xlsx"), key=lambda x: -x.stat().st_mtime):
        if f.name.startswith("~$"):
            continue
        try:
            wb = openpyxl.load_workbook(f, read_only=True)
            if "어르신별_메뉴별" in wb.sheetnames:
                found.append(f)
            wb.close()
        except Exception:
            continue
    if not found:
        raise SystemExit(f"'어르신별_메뉴별' 시트가 있는 엑셀을 {path} 에서 찾지 못했습니다")
    print(f"엑셀: {found[0].name}" + (f" (후보 {len(found)}개 중 가장 최근)" if len(found) > 1 else ""))
    return str(found[0])


def heritage_daily(xlsx: str) -> pd.DataFrame:
    df = pd.read_excel(find_xlsx(xlsx), sheet_name="어르신별_메뉴별")
    cols = list(NUT.values())
    eat = pd.to_numeric(df["섭취량_g"], errors="coerce").fillna(0)
    srv = pd.to_numeric(df["배식량_g"], errors="coerce").fillna(0)
    vals = df[cols].apply(pd.to_numeric, errors="coerce")
    # 식약처 식품별 g당 값 (섭취량 > 0 인 칸에서)
    per_g = (vals[eat > 0].div(eat[eat > 0], axis=0)).groupby(df.loc[eat > 0, "식약처 식품명"]).median()
    out = vals.copy()
    ok = eat > 0
    out[ok] = vals[ok].mul((srv[ok] / eat[ok]), axis=0)
    zero = ~ok & (srv > 0)
    if zero.any():
        g = per_g.reindex(df.loc[zero, "식약처 식품명"]).set_index(df.index[zero])
        out[zero] = g.mul(srv[zero], axis=0)
    out = out.fillna(0)
    out.columns = list(NUT.keys())
    out["hid"], out["day"], out["meal"], out["form"] = df["식별번호"], df["일차"], df["끼니"], df["식사형태"]
    d = out.groupby(["hid", "day"])[list(NUT)].sum().reset_index()
    d["arm"] = "A 헤리티지"
    return d, df[["식별번호", "이름", "식사형태"]].drop_duplicates()


def basic_done_only(sb, home_id, hid2eid: dict) -> dict:
    """기초조사 완료자만 — survey_progress.basic_survey_completed 기준 (없으면 basic_survey 응답 행)"""
    from care.data import fetch_all
    rule = "survey_progress.basic_survey_completed"
    try:
        rows = fetch_all(sb, "survey_progress", "elderly_id,basic_survey_completed,nutrition_survey_completed",
                         eq={"nursing_home_id": home_id})
        ids = {r["elderly_id"] for r in rows if r.get("basic_survey_completed")}
        nut = {r["elderly_id"] for r in rows if r.get("nutrition_survey_completed")}
        print(f"  조사 진행표: 기초조사 완료 {len(ids)}명 · 영양조사 완료 {len(nut)}명 · 둘 다 {len(ids & nut)}명")
    except Exception as e:
        print(f"  survey_progress 조회 실패 ({str(e)[:80]}) → basic_survey 응답 행 기준")
        rows = fetch_all(sb, "basic_survey", "elderly_id", eq={"nursing_home_id": home_id})
        ids, rule = {r["elderly_id"] for r in rows}, "basic_survey 응답 행"
    keep = {h: e for h, e in hid2eid.items() if e in ids}
    print(f"기초조사 완료 ({rule}): 시설 {len(ids)}명 · 영양조사 엑셀과 겹치는 어르신 {len(keep)}명")
    return keep


def read_hids(spec: str) -> set:
    """--hids: 'HS01,HS03' 또는 식별번호가 든 txt/csv/xlsx 파일 ('식별번호'·'ID' 열 또는 첫 열)
       설문 분석 결과 analysis_tables.xlsx 를 주면 '대상선정' 시트에서 '분석 포함'인 어르신만"""
    p = Path(spec)
    if p.is_file():
        if p.suffix.lower() in (".xlsx", ".xls", ".csv"):
            if p.suffix.lower() == ".csv":
                df = pd.read_csv(p)
            else:                                   # 설문 분석 결과(analysis_tables.xlsx)면 '대상선정' 시트
                xl = pd.ExcelFile(p)
                df = pd.read_excel(p, sheet_name="대상선정" if "대상선정" in xl.sheet_names else 0)
            if "판정" in df.columns:                # careeat_survey_analysis.py 의 대상선정: '분석 포함'만
                df = df[df["판정"] == "분석 포함"]
            col = next((c for c in ("식별번호", "ID", "id") if c in df.columns), df.columns[0])
            vals = df[col].dropna().astype(str)
        else:
            vals = re.split(r"[\s,]+", p.read_text(encoding="utf-8"))
    else:
        vals = spec.split(",")
    return {v.strip().upper() for v in vals if re.match(r"^\s*HS\d+", str(v), re.I)}


# ─────────────────────────── 목표 ───────────────────────────
def targets_of(synth: dict) -> dict:
    c = {k: v["value"] for k, v in (synth.get("constraints") or {}).items()}
    te = synth.get("target_energy") or 600
    t = {"energy": 3 * te}
    for k in ("protein_min", "sodium_max", "fiber_min", "potassium_min", "protein_max"):
        if c.get(k):
            t[k] = 3 * c[k]
    for n in ("fat", "sat_fat", "sugar", "carb"):
        for b in ("min", "max"):
            if c.get(f"{n}_{b}"):
                t[f"{n}_{b}_pct"] = c[f"{n}_{b}"] * KCAL[n] / te       # 끼니 g 기준 → 열량 비율
    return t


def judge(row: dict, t: dict) -> dict:
    e = row["energy"] or 1e-9
    pct = lambda n: row[n] * KCAL[n] / e
    r = {"energy": abs(row["energy"] - t["energy"]) <= 0.10 * t["energy"]}
    if "protein_max" in t:
        r["protein"] = row["protein"] <= t["protein_max"]
    elif "protein_min" in t:
        r["protein"] = row["protein"] >= t["protein_min"]
    if "sodium_max" in t:
        r["sodium"] = row["sodium"] <= t["sodium_max"]
    if "fiber_min" in t:
        r["fiber"] = row["fiber"] >= t["fiber_min"]
    if "potassium_min" in t:
        r["potassium"] = row["potassium"] >= t["potassium_min"]
    if "fat_min_pct" in t:
        r["fat_min"] = pct("fat") >= t["fat_min_pct"] - 1e-9
    if "fat_max_pct" in t:
        r["fat_max"] = pct("fat") <= t["fat_max_pct"] + 1e-9
    if "sat_fat_max_pct" in t:
        r["sat_fat"] = pct("sat_fat") <= t["sat_fat_max_pct"] + 1e-9
    if "sugar_max_pct" in t:
        r["sugar"] = pct("sugar") <= t["sugar_max_pct"] + 1e-9
    if "carb_min_pct" in t and "carb_max_pct" in t:
        r["carb"] = t["carb_min_pct"] - 1e-9 <= pct("carb") <= t["carb_max_pct"] + 1e-9
    return r


# ─────────────────────────── (B)(C) Care-Eat ───────────────────────────
def careeat_daily(result: dict, eids: list, days: list) -> pd.DataFrame:
    from diet.pipeline import POOL_JSON
    pool = json.load(open(POOL_JSON, encoding="utf-8"))
    pidx = {(cat, m["menu_name"]): m for cat, ms in pool.items() for m in ms}
    dn = lambda d: int(re.sub(r"\D", "", str(d)) or 0)
    common = defaultdict(lambda: {k: 0.0 for k in NUT})
    for rec in result["menu"]:
        d = dn(rec["일차"])
        if d not in days:
            continue
        for s in SLOTS:
            m = pidx.get((CAT[s], rec.get(s)))
            if m:
                for k in NUT:
                    common[d][k] += float(m.get(k) or 0)
    rows = []
    for eid in eids:
        per = defaultdict(lambda: {k: 0.0 for k in NUT})
        for x in result["servings"].get(eid, []):
            d = dn(x["일차"])
            if d in days:
                for k, col in SRV.items():
                    per[d][k] += float(x.get(col) or 0)
        for d in days:
            rows.append({"eid": eid, "day": d, "arm": "B Care-Eat 공통(개인화 전)", **common[d]})
            rows.append({"eid": eid, "day": d, "arm": "C Care-Eat 개인화", **per[d]})
    return pd.DataFrame(rows)


# ─────────────────────────── 평가 ───────────────────────────
def evaluate(daily: pd.DataFrame, T: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    det = []
    for _, r in daily.iterrows():
        t = T[r["hid"]]
        j = judge(r.to_dict(), t)
        det.append({"hid": r["hid"], "arm": r["arm"], "day": r["day"], **{f"ok_{k}": v for k, v in j.items()},
                    "적합도": 100 * sum(j.values()) / len(j), "열량편차%": 100 * (r["energy"] - t["energy"]) / t["energy"],
                    "열량": r["energy"], "단백질": r["protein"], "나트륨": r["sodium"],
                    "지방%E": 100 * r["fat"] * 9 / max(r["energy"], 1), "당류%E": 100 * r["sugar"] * 4 / max(r["energy"], 1),
                    "식이섬유": r["fiber"], "칼륨": r["potassium"], "탄수화물": r["carb"], "지방": r["fat"],
                    "당류": r["sugar"], "포화지방": r["sat_fat"],
                    "탄수화물%E": 100 * r["carb"] * 4 / max(r["energy"], 1),
                    "단백질%E": 100 * r["protein"] * 4 / max(r["energy"], 1)})
    det = pd.DataFrame(det)
    per = det.groupby(["hid", "arm"]).agg(적합도=("적합도", "mean"), 열량편차_절대=("열량편차%", lambda s: s.abs().mean())).reset_index()
    return det, per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--home", help="요양원 id 또는 이름 일부")
    ap.add_argument("--run", help="diet_runs.id (없으면 규칙 모드로 새로 설계)")
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7, help="5일 무작위 추출 시드")
    ap.add_argument("--design-seed", type=int, default=42)
    ap.add_argument("--seeds", help="반복 검증: 날짜 추출 시드 여러 개 (예 7,11,23,31,47)")
    ap.add_argument("--design-seeds", help="반복 검증: 설계 시드 여러 개 (예 42,43,44) — 시드마다 설계를 새로 돌림")
    ap.add_argument("--out")
    ap.add_argument("--basic-done", action="store_true",
                    help="기초조사까지 완료한 어르신만 비교 (조사 진행표 survey_progress 기준)")
    ap.add_argument("--hids", help="비교할 식별번호만: 'HS01,HS03,…' 또는 식별번호 목록 파일(txt/csv/xlsx)")
    ap.add_argument("--mock", help=argparse.SUPPRESS)          # 개발용: 합성 데이터 (scratch mock_data)
    a = ap.parse_args()
    ints = lambda x: [int(v) for v in str(x).split(",") if v.strip()]
    seeds = ints(a.seeds) if a.seeds else [a.seed]
    dseeds = ints(a.design_seeds) if (a.design_seeds and not a.run) else [a.design_seed]
    a.out_set = bool(a.out)
    a.out = a.out or str(BACKEND / "scripts" / "validate_heritage_result.xlsx")

    H, names = heritage_daily(a.xlsx)
    print(f"(A) 헤리티지: 어르신 {H['hid'].nunique()}명 × {H['day'].nunique()}일")

    if a.mock:                                                  # 개발 시험용
        sys.path.insert(0, a.mock)
        from mock_data import mock
        from diet import pipeline as P
        residents, assess, settings = mock()
        design = lambda ds: P.run_design(residents, assess, settings, None, None, preset="standard", seed=ds,
                                         selector="rule", reviewer="off", refiner="off")
        result = design(dseeds[0])
        eids = list(result["servings"])
        hid2eid = dict(zip(sorted(H["hid"].unique()), eids))
    else:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env")
        from care.data import fetch_all
        from dependencies import get_supabase
        sb = get_supabase()
        homes = sb.table("nursing_homes").select("*").execute().data or []
        home = next((h for h in homes if str(h.get("id")) == a.home or a.home in str(h.get("name") or "")), None)
        if not home:
            raise SystemExit(f"요양원을 찾지 못했습니다: {a.home}")
        hid_home = home["id"]
        residents = fetch_all(sb, "elderly_residents", eq={"nursing_home_id": hid_home})
        by_name = defaultdict(list)
        for r in residents:
            by_name[str(r.get("name") or r.get("elderly_name") or "").strip()].append(r["id"])
        hid2eid, miss = {}, []
        for _, r in names.iterrows():
            c = by_name.get(str(r["이름"]).strip()) or []
            if len(c) == 1:
                hid2eid[r["식별번호"]] = c[0]
            else:
                miss.append((r["식별번호"], "동명이인" if c else "없음"))
        print(f"이름으로 연결: {len(hid2eid)}명 · 연결 안 됨 {len(miss)}명 {miss[:10]}")
        if a.basic_done:
            hid2eid = basic_done_only(sb, hid_home, hid2eid)
        if a.hids:
            want = read_hids(a.hids)
            lost = sorted(want - set(hid2eid))
            hid2eid = {h: e for h, e in hid2eid.items() if h in want}
            print(f"지정 식별번호 {len(want)}개 → 비교 {len(hid2eid)}명" + (f" · 제외 {lost}" if lost else ""))
        if a.run:
            result = (sb.table("diet_runs").select("result").eq("id", a.run).execute().data or [{}])[0].get("result")
            if not result:
                raise SystemExit("설계 결과를 찾지 못했습니다")
        else:
            from routers.diet import _load_ehr, _load_inputs
            from diet import pipeline as P
            res_, assess, settings, inv, pref = _load_inputs(sb, hid_home)
            ehr = _load_ehr(sb, hid_home)

            def design(ds):
                print(f"Care-Eat 설계 실행 (규칙 모드, LLM 없음, 설계 시드 {ds}) …")
                return P.run_design(res_, assess, settings, inv, pref, preset="standard", seed=ds,
                                    ehr=ehr, selector="rule", reviewer="off", refiner="off",
                                    progress=lambda m: print("  ", m))
            result = design(dseeds[0])

    if a.run and a.design_seeds:
        print("--run 을 주면 --design-seeds 는 쓰지 않습니다 (설계 결과 1개)")
    reps = []
    for k, ds in enumerate(dseeds):
        res = result if k == 0 else design(ds)
        for sd in seeds:
            reps.append(analyze(res, hid2eid, H, sd, a.days, a.run or ds))
    if len(reps) == 1:
        write_single(reps[0], a)
    else:
        write_repeat(reps, a)


ARMS = ["A 헤리티지", "B Care-Eat 공통(개인화 전)", "C Care-Eat 개인화"]
NUT_COLS = ["열량", "탄수화물", "탄수화물%E", "단백질", "단백질%E", "지방", "지방%E", "식이섬유", "나트륨", "당류", "당류%E", "포화지방", "칼륨"]


def analyze(result: dict, hid2eid: dict, H: pd.DataFrame, seed: int, ndays: int, design_tag) -> dict:
    """설계 결과 1개 × 날짜 추출 1회 → 평가표"""
    hid2eid = {h: e for h, e in hid2eid.items() if e in (result.get("assessments") or {}) and e in result.get("servings", {})}
    days = sorted(random.Random(seed).sample(range(1, 29), ndays))
    print(f"[설계 {design_tag} · 추출 시드 {seed}] 비교 {len(hid2eid)}명 · Care-Eat {ndays}일 {days}")
    C = careeat_daily(result, list(hid2eid.values()), days)
    eid2hid = {e: h for h, e in hid2eid.items()}
    C["hid"] = C["eid"].map(eid2hid)
    H = H[H["hid"].isin(hid2eid)]
    T = {h: targets_of(result["assessments"][e]["synth"]) for h, e in hid2eid.items()}
    daily = pd.concat([H, C.drop(columns=["eid"])], ignore_index=True)
    det, per = evaluate(daily, T)
    grp = {}
    for h, e in hid2eid.items():
        meta = next((r for r in result.get("residents", []) if r["elderly_id"] == e), {})
        grp[h] = meta.get("type") or "-"
    per["유형"] = per["hid"].map(grp)
    return {"det": det, "per": per, "T": T, "days": days, "seed": seed, "design": design_tag, "n": len(hid2eid)}


def paired(wide: pd.DataFrame) -> dict:
    stats = {}
    try:
        from scipy.stats import wilcoxon
    except Exception as e:
        return {"오류": {"메시지": str(e)[:120]}}
    pairs = [(ARMS[1], ARMS[0], f"{ARMS[1]} − A"), (ARMS[2], ARMS[0], f"{ARMS[2]} − A"), (ARMS[2], ARMS[1], "C − B (개인화 효과)")]
    for x, y, name in pairs:
        d = (wide[x] - wide[y]).dropna()
        stats[name] = {"차이 평균": round(float(d.mean()), 1), "개선 어르신": int((d > 0).sum()), "같음": int((d == 0).sum()),
                       "악화 어르신": int((d < 0).sum()), "Wilcoxon p": float(wilcoxon(d).pvalue) if (d != 0).any() else 1.0}
    return stats


def tables(rep: dict) -> dict:
    det, per = rep["det"], rep["per"]
    okcols = [c for c in det.columns if c.startswith("ok_")]
    rate = det.groupby("arm")[okcols].mean().T.reindex(columns=ARMS) * 100
    rate.index = [LABEL.get(c[3:], c[3:]) for c in rate.index]
    summ = per.groupby("arm").agg(어르신=("hid", "nunique"), 적합도_평균=("적합도", "mean"), 적합도_SD=("적합도", "std"),
                                  열량편차_평균=("열량편차_절대", "mean")).reindex(ARMS)
    wide = per.pivot(index="hid", columns="arm", values="적합도").reindex(columns=ARMS)
    # 영양성분: 어르신별 평균 → 집단 평균
    nut = det.groupby(["arm", "hid"])[["적합도"] + NUT_COLS].mean().groupby("arm").mean().reindex(ARMS)
    return {"rate": rate, "summ": summ, "wide": wide, "nut": nut, "stats": paired(wide),
            "n_app": det.groupby("arm")[okcols].count().T.reindex(columns=ARMS)}


def write_single(rep: dict, a):
    t = tables(rep)
    det, per, T = rep["det"], rep["per"], rep["T"]
    by_type = per.pivot_table(index="유형", columns="arm", values="적합도", aggfunc="mean").reindex(columns=ARMS)
    by_type["어르신"] = per.groupby("유형")["hid"].nunique()
    print("\n=== 어르신별 하루 목표 적합도 (0~100, 5일 평균) ===")
    print(t["summ"].round(1).to_string())
    print("\n=== 평균 영양성분 (하루) ===")
    print(t["nut"].round(1).T.to_string())
    print("\n=== 항목별 충족률 (%) — 어르신·일 단위 ===")
    print(t["rate"].round(1).to_string())
    print("\n=== 대응 비교 ===")
    for k, v in t["stats"].items():
        print(" ", k, v)
    print("\n=== 유형별 적합도 ===")
    print(by_type.round(1).to_string())
    with pd.ExcelWriter(a.out) as w:
        pd.DataFrame([{"항목": "비교 어르신", "값": rep["n"]},
                      {"항목": "대상", "값": ("지정 식별번호 " if a.hids else "") + ("기초조사 + 영양조사 완료자" if a.basic_done else "영양조사 엑셀 + Care-Eat 평가가 있는 어르신")}, {"항목": "Care-Eat 추출 일차", "값": ", ".join(map(str, rep["days"]))},
                      {"항목": "추출 시드", "값": rep["seed"]}, {"항목": "설계", "값": a.run or f"규칙 모드 새 설계 (seed {rep['design']})"},
                      {"항목": "기준", "값": "배식량 기준 · 목표 = Care-Eat 개인 영양 기준(끼니×3) · 열량 ±10% · 비율 영양소는 실제 열량 대비 %E"}]
                     ).to_excel(w, sheet_name="설정", index=False)
        t["summ"].round(2).to_excel(w, sheet_name="요약")
        t["nut"].round(1).T.to_excel(w, sheet_name="평균_영양성분")
        t["rate"].round(1).assign(**{f"해당수_{c[:1]}": t["n_app"][c].values for c in ARMS}).to_excel(w, sheet_name="항목별_충족률")
        pd.DataFrame(t["stats"]).T.to_excel(w, sheet_name="대응비교")
        by_type.round(1).to_excel(w, sheet_name="유형별")
        t["wide"].round(1).to_excel(w, sheet_name="어르신별_적합도")
        det.round(2).to_excel(w, sheet_name="일별_상세", index=False)
        pd.DataFrame([{"식별번호": h, **{k: round(v, 3) for k, v in T[h].items()}} for h in T]).to_excel(w, sheet_name="어르신별_목표", index=False)
    print("\n결과:", a.out)


def _rng(df: pd.DataFrame, digits: int = 1) -> pd.DataFrame:
    """반복별 값(행=반복) → 평균 [최소–최대]"""
    m, lo, hi = df.mean(), df.min(), df.max()
    f = lambda v: f"{v:,.{digits}f}"
    return pd.Series({c: f"{f(m[c])} [{f(lo[c])}–{f(hi[c])}]" for c in df.columns})


def write_repeat(reps: list, a):
    out = a.out if a.out_set else str(Path(a.out).with_name("validate_heritage_repeat.xlsx"))
    T_all = [tables(r) for r in reps]
    rows = []
    for r, t in zip(reps, T_all):
        row = {"설계 시드": r["design"], "추출 시드": r["seed"], "일차": ", ".join(map(str, r["days"])), "어르신": r["n"]}
        for arm in ARMS:
            row[f"적합도 {arm[0]}"] = t["summ"].loc[arm, "적합도_평균"]
            row[f"열량편차 {arm[0]}"] = t["summ"].loc[arm, "열량편차_평균"]
        for k, v in t["stats"].items():
            if "차이 평균" in v:
                tag = k.split(" ")[0][0] + "−" + ("B" if "C − B" in k else "A")
                row[f"{tag} 차이"] = v["차이 평균"]
                row[f"{tag} 개선"] = v["개선 어르신"]
                row[f"{tag} 악화"] = v["악화 어르신"]
                row[f"{tag} p"] = v["Wilcoxon p"]
        rows.append(row)
    R = pd.DataFrame(rows)

    # 종합: 집단별 영양성분·적합도 — 반복 평균 [최소–최대]
    nut = pd.DataFrame({arm: _rng(pd.DataFrame([t["nut"].loc[arm] for t in T_all])) for arm in ARMS})
    rate = pd.DataFrame({arm: _rng(pd.DataFrame([t["rate"][arm] for t in T_all])) for arm in ARMS})
    pair = []
    for tag in ("B−A", "C−A", "C−B"):
        if f"{tag} 차이" not in R:
            continue
        pair.append({"비교": tag, "차이 평균": _rng(R[[f"{tag} 차이"]]).iloc[0],
                     "개선 어르신": f"{R[f'{tag} 개선'].mean():.1f} [{R[f'{tag} 개선'].min()}–{R[f'{tag} 개선'].max()}]",
                     "악화 어르신": f"{R[f'{tag} 악화'].mean():.1f} [{R[f'{tag} 악화'].min()}–{R[f'{tag} 악화'].max()}]",
                     "Wilcoxon p 최대": f"{R[f'{tag} p'].max():.2e}",
                     "p<0.05 반복": f"{int((R[f'{tag} p'] < 0.05).sum())}/{len(R)}"})
    pair = pd.DataFrame(pair)
    # 어르신별: 15회 평균
    per_all = pd.concat([t["wide"].assign(rep=i) for i, t in enumerate(T_all)])
    per_hid = per_all.groupby(level=0)[ARMS].agg(["mean", "min", "max"]).round(1)
    worse = (per_all[ARMS[2]] < per_all[ARMS[0]]).groupby(level=0).sum()
    per_hid[("C<A 반복수", "")] = worse
    # 설계 시드 내 / 날짜 추출 간 변동 (C 적합도)
    var = R.groupby("설계 시드")[["적합도 C", "C−A 차이"]].agg(["mean", "min", "max"]).round(1)

    print(f"\n=== 반복 {len(reps)}회 (설계 {R['설계 시드'].nunique()} × 추출 {R['추출 시드'].nunique()}) — 평균 [최소–최대] ===")
    print(nut.to_string())
    print("\n=== 항목별 충족률 (%) ===")
    print(rate.to_string())
    print("\n=== 대응 비교 ===")
    print(pair.to_string(index=False))
    print("\n=== 설계 시드별 (C 적합도 · C−A 차이) ===")
    print(var.to_string())
    print(f"\nC 가 A 보다 낮았던 적이 있는 어르신: {int((worse > 0).sum())}명 " + str(worse[worse > 0].to_dict()))

    with pd.ExcelWriter(out) as w:
        pd.DataFrame([{"항목": "반복", "값": f"{len(reps)}회 = 설계 시드 {sorted((int(v) if str(v).isdigit() else v for v in R['설계 시드'].unique()), key=str)} × 날짜 추출 시드 {sorted(int(v) for v in R['추출 시드'].unique())}"},
                      {"항목": "비교 어르신", "값": int(R["어르신"].max())},
                      {"항목": "대상", "값": ("지정 식별번호 " if a.hids else "") + ("기초조사 + 영양조사 완료자" if a.basic_done else "영양조사 엑셀 + Care-Eat 평가가 있는 어르신")},
                      {"항목": "헤리티지(A)", "값": "조사 5일 고정 — 반복해도 같음 (Care-Eat 쪽 표본만 바뀜)"},
                      {"항목": "표기", "값": "평균 [최소–최대] — 각 반복의 집단 평균(어르신별 5일 평균의 평균)을 반복 간에 요약"},
                      {"항목": "기준", "값": "배식량 기준 · 목표 = Care-Eat 개인 영양 기준(끼니×3) · 열량 ±10% · 비율 영양소는 실제 열량 대비 %E"}]
                     ).to_excel(w, sheet_name="설정", index=False)
        nut.to_excel(w, sheet_name="종합_적합도·영양성분")
        rate.to_excel(w, sheet_name="종합_항목별_충족률")
        pair.to_excel(w, sheet_name="종합_대응비교", index=False)
        var.to_excel(w, sheet_name="설계시드별")
        R.round(4).to_excel(w, sheet_name="반복별", index=False)
        per_hid.to_excel(w, sheet_name="어르신별_적합도")
        pd.concat([r["det"].assign(설계=r["design"], 추출=r["seed"]) for r in reps]).round(2).to_excel(w, sheet_name="일별_상세", index=False)
    print("\n결과:", out)


if __name__ == "__main__":
    main()
