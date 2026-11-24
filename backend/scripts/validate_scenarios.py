# -*- coding: utf-8 -*-
"""[검증] 시나리오 기반 안전성·규칙 검증 — 제약조건 위반율 · 문제 탐지율 · 충돌 탐지 일치 · 강제 제약 준수

    python -m scripts.make_scenarios                     # 시나리오 정의 (diet/data/validation_scenarios.json)
    python -m scripts.validate_scenarios                 # 규칙 모드 (LLM 없음)
    python -m scripts.validate_scenarios --ai            # AI 영역 전문가·임상 영양사·충돌 전문가 켬 (OPENAI 키 필요)

  · 시나리오 어르신(합성, 식별정보 없음)을 한 시설로 묶어 전체 설계(공통 최적화 → 개인화 → 대체찬 → 배식)를 1회 실행
  · 판정
      식재료 위반     최종 식단(대체찬·식사형태 반영) 끼니에 피해야 할 식재료가 남은 비율
                      - 규칙표 기준: 시스템이 쓰는 키워드·최소량 그대로 (시스템이 약속을 지켰는가)
                      - 확장 기준: 식약처 알레르기 표시 대상 등 더 넓은 키워드 (사람이 검토할 후보 — 위반으로 단정하지 않음)
      문제 탐지       나와야 할 문제가 나왔는가(민감도) · 나오면 안 되는 문제가 안 나왔는가(특이도)
      충돌 탐지       탐지된 충돌 집합이 정답과 같은가
      강제 제약       약물·질환 강제 제약 적용, 해제돼야 할 기준이 빠졌는가
      식사형태        죽식은 모든 끼니 죽, 대체 제품 조리법(다지기·갈기)
      안전성 고정     Level 1 문제가 우선순위 맨 앞인가 (AI 모드에서 특히 중요)
  · 출력: scripts/validate_scenarios_result.xlsx
          scripts/expert_form.xlsx  (전문가 평가지 — 시스템 결과는 '2_시스템결과' 시트에만, 판정 후 보도록 안내)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
SCEN_JSON = BACKEND / "diet" / "data" / "validation_scenarios.json"
SLOTS = ("밥", "국", "주찬", "부찬1", "부찬2", "김치")

# 전문가 평가지의 문제 범주 ← 시스템 문제 코드
PROBLEM_CATS = [
    ("저체중", {"underweight"}), ("비만", {"obesity"}), ("영양불량(위험)", {"malnutrition_risk"}),
    ("근감소 위험", {"sarcopenia_risk"}), ("당류 관리", {"sugar_control"}), ("저혈당 위험", {"hypoglycemia_risk"}),
    ("나트륨 제한", {"sodium_control", "sodium_intake_high"}), ("섭취 저하", {"slot_low_intake", "energy_intake_low",
                                                                       "protein_intake_low", "fiber_intake_low"}),
    ("뇌건강 식재료", {"brain_food"}), ("식사 도움", {"eating_assist"}), ("흡인 위험", {"aspiration_risk"}),
    ("저작곤란", {"chewing"}), ("식사형태 부적합", {"texture_mismatch"}), ("알레르기", {"allergy"}),
    ("약물-식품 상호작용", {"warfarin_vitk", "k_sparing", "mao_b_tyramine", "grapefruit_statin_ccb", "digoxin_fiber",
                     "levodopa_protein", "iron_tea", "levothyroxine", "bisphosphonate", "sulfonylurea_insulin",
                     "nsaid_food", "antithrombotic_check"}),
]
CONFLICT_OPTIONS = {
    "energy_vs_sugar": ("당류 상한을 더 조이지 않고 열량·단백질 확보 우선", "당류 제한을 우선해 더 엄격히"),
    "dysphagia_vs_protein": ("부드러운 고단백·영양 강화식으로 열량·단백질 확보를 더 시급히", "식사형태만 조정하고 영양 목표는 그대로"),
    "sodium_vs_low_intake": ("나트륨 상한을 기본보다 더 조이지 않고 섭취 유지 우선", "나트륨을 더 엄격히 제한"),
    "obesity_vs_muscle": ("열량·단백질 하한 유지 (근육 유지 우선)", "열량을 줄여 감량 우선"),
    "warfarin_vs_vegetables": ("잎채소는 매일 일정량, 칼륨·식이섬유는 다른 채소·과일로", "녹색 잎채소 전면 제한"),
    "k_sparing_vs_potassium": ("칼륨 하한 해제, 고칼륨 식품 제한", "칼륨 섭취 권장 유지"),
    "protein_vs_kidney": ("단백질 증량 보류, 의료진 확인 후 결정", "영양불량 개선을 위해 단백질 증량"),
}
FORM_OPTIONS = ["밥/일반찬", "밥/다진찬", "죽/일반찬", "죽/다진찬", "죽/갈찬"]


def scenario_inputs(scen: list):
    """시나리오 → run_design 입력 (residents, assessments, settings, ehr)"""
    residents, assess, settings, ehr = [], {}, {}, {}
    for s in scen:
        eid = f"SC_{s['id']}"
        f = dict(s["features"])
        rate = f.pop("intake_rate", 85)
        f["meal_log"] = [{"day": d, "meal": m, "items": [{"slot": sl, "name": "-", "g": 100, "rate": rate}
                                                         for sl in ("밥", "국/탕", "주찬", "부찬1", "부찬2", "김치1")]}
                         for d in range(1, 6) for m in ("아침", "점심", "저녁")]
        residents.append({"id": eid, "name": f"시나리오 {s['id']}", "meal_form": s["meal_form"]})
        assess[eid] = {"features": f}
        settings[eid] = {}
        ehr[eid] = s["ehr"]
    return residents, assess, settings, ehr


# ─────────────────────────── 식단 속 식재료 ───────────────────────────
class MenuIngredients:
    def __init__(self):
        from diet.inventory import recipe_ingredients
        from diet.extra_recipes import load_extra_recipes
        self.recipe = recipe_ingredients()
        for ms in load_extra_recipes().values():
            for m in ms:
                if m.get("ingredients"):
                    self.recipe.setdefault(m["menu_name"], m["ingredients"])

    def of(self, name: str) -> dict | None:
        """{재료: g} — 레시피가 없으면(제품 등) None → 이름으로 판단"""
        return self.recipe.get(name)


def hits(ings: dict | None, name: str, kws: list, min_g: float = 0.0) -> list:
    if ings:
        found = {i: g for i, g in ings.items() if any(k in i for k in kws)}
        return sorted(found) if found and sum(found.values()) >= (min_g or 0) and sum(found.values()) > 0 else []
    return [k for k in kws if k in (name or "")]


def check_rules(kb: dict):
    groups = {g["group"]: g for g in kb["allergens"]}
    rules = {r["id"]: r for r in kb["rules"]}
    return groups, rules


# ─────────────────────────── 평가 ───────────────────────────
def evaluate(scen: list, result: dict) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    from diet.agents.medication import kb
    groups, rules = check_rules(kb())
    MI = MenuIngredients()
    checks, menu_rows, system_answers = [], [], []
    flagged = {(x.get("elderly_id"), str(x.get("day")), str(x.get("meal")), x.get("slot"))
               for x in result.get("safety_flags") or []}

    for s in scen:
        eid, exp = f"SC_{s['id']}", s["expected"]
        a = (result.get("assessments") or {}).get(eid)
        if not a:
            checks.append({"시나리오": s["id"], "영역": s["domain"], "점검": "평가 결과", "기대": "있음", "결과": "없음", "통과": False})
            continue
        syn = a["synth"]
        pri = syn.get("priorities") or []
        codes = {p.get("code") for p in pri}
        avoid = syn.get("avoid") or []
        avoid_kws = {k for av in avoid for k in av.get("keywords") or []}
        info = syn.get("synthesis") or {}
        conflicts = {c.get("id") for c in info.get("conflicts") or []}
        overrides = {o.get("id") for o in info.get("overrides") or []}
        cons = set((syn.get("constraints") or {}).keys())

        def add(kind, expect, got, ok):
            checks.append({"시나리오": s["id"], "영역": s["domain"], "점검": kind, "기대": expect, "결과": got, "통과": bool(ok)})

        for c in exp["issues_present"]:
            add("문제 탐지(있어야 함)", c, "탐지" if c in codes else "미탐지", c in codes)
        for c in exp["issues_absent"]:
            add("오탐 점검(없어야 함)", c, "나옴" if c in codes else "안 나옴", c not in codes)
        for k in exp["avoid_kw"]:
            add("피할 식재료 등록", k, "등록" if k in avoid_kws else "누락", k in avoid_kws)
        ex_c = set(exp["conflicts"])
        add("충돌 탐지(집합 일치)", ", ".join(sorted(ex_c)) or "없음", ", ".join(sorted(conflicts)) or "없음", ex_c == conflicts)
        for o in exp["overrides"]:
            add("강제 제약 적용", o, "적용" if o in overrides else "미적용", o in overrides)
        for r in exp["removed"]:
            add("기준 해제", r, "해제" if r not in cons else "남아 있음", r not in cons)
        # Level 1 이 맨 앞인가
        lv = [p.get("level") for p in pri]
        if 1 in lv:
            ok = all(l == 1 for l in lv[:lv.count(1)])
            add("안전성 우선(Level 1 맨 앞)", "맨 앞", "맨 앞" if ok else "뒤섞임", ok)

        # 최종 식단 점검
        meals = (result.get("servings") or {}).get(eid) or []
        if exp["porridge"]:
            bad = [m for m in meals if "죽" not in str((m.get("메뉴") or {}).get("밥", ""))]
            add("죽식 적용(모든 끼니)", f"{len(meals)}끼", f"죽 아닌 끼니 {len(bad)}", meals and not bad)
        if exp["cook"]:
            subs = [x for x in result.get("substitutions") or [] if x.get("name") == eid]
            badc = [x for x in subs if x.get("cook") not in (exp["cook"],)]
            add("대체 제품 조리법", exp["cook"], f"대체 {len(subs)}건 중 불일치 {len(badc)}", not badc)
        for mc in exp["menu_check"]:
            if mc.get("group"):
                kws, min_g = groups[mc["group"]]["ingredients"], 0.0
            else:
                r = rules[mc["rule"]]
                kws, min_g = r["ingredients"], float(r.get("min_g") or 0)
            extra = [k for k in mc.get("extra") or [] if k not in kws]
            n_bad = n_ext = n_silent = 0
            for m in meals:
                menu = m.get("메뉴") or {}
                bad_items, ext_items, silent = [], [], []
                for sl in SLOTS:
                    nm = menu.get(sl)
                    if not nm:
                        continue
                    ings = MI.of(nm)
                    h = hits(ings, nm, kws, min_g)
                    if h:
                        bad_items.append(f"{sl}:{nm}({', '.join(h)})")
                        if (eid, str(m.get("일차")), str(m.get("끼니")), sl) not in flagged:
                            silent.append(sl)
                    elif extra:
                        he = hits(ings, nm, extra, 0)
                        if he:
                            ext_items.append(f"{sl}:{nm}({', '.join(he)})")
                n_bad += bool(bad_items)
                n_ext += bool(ext_items)
                n_silent += bool(silent)
                if bad_items or ext_items:
                    menu_rows.append({"시나리오": s["id"], "점검": mc["label"], "일차": m.get("일차"), "끼니": m.get("끼니"),
                                      "규칙표 기준 위반": " / ".join(bad_items),
                                      "영양사 확인 표시": ("" if not bad_items else "표시 안 됨: " + ", ".join(silent) if silent else "표시됨"),
                                      "확장 기준(검토 필요)": " / ".join(ext_items)})
            add(f"식단 위반 — {mc['label']}", "0끼", f"{n_bad}/{len(meals)}끼 (표시 안 된 {n_silent}끼 · 확장 {n_ext}끼)", n_bad == 0)
            checks[-1].update({"끼니": len(meals), "위반 끼니": n_bad, "표시 안 된 위반 끼니": n_silent, "확장 기준 끼니": n_ext})
            add(f"위반 시 영양사 확인 표시 — {mc['label']}", "모두 표시", f"표시 안 된 {n_silent}끼", n_silent == 0)

        # 전문가 비교용 시스템 판정
        cats = {lab: int(bool(codes & cs)) for lab, cs in PROBLEM_CATS}
        system_answers.append({"시나리오": s["id"], **{f"문제:{k}": v for k, v in cats.items()},
                               "권장 식사형태": recommended_form(s, codes),
                               **{f"충돌:{cid}": ("A" if cid in conflicts else "") for cid in CONFLICT_OPTIONS},
                               "피할 식재료": ", ".join(sorted({av.get("reason", "") for av in avoid}))})
    return pd.DataFrame(checks), pd.DataFrame(menu_rows), system_answers


def recommended_form(s: dict, codes: set) -> str:
    """시스템이 사실상 권하는 식사형태 — 현재 형태 + 흡인 위험이면 갈찬, 저작곤란이면 최소 다진찬"""
    rice, side = s["meal_form"].split("/")
    rice = "죽" if "죽" in rice else "밥"
    if "aspiration_risk" in codes:
        return "죽/갈찬"
    if "chewing" in codes and side == "일반찬":
        side = "다진찬"
    return f"{rice}/{side}"


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for kind, g in df.groupby("점검", sort=False):
        k = "식단 위반" if kind.startswith("식단 위반") else "위반 시 영양사 확인 표시" if kind.startswith("위반 시") else kind
        rows.append((k, g))
    out = []
    agg = defaultdict(list)
    for k, g in rows:
        agg[k].append(g)
    for k, gs in agg.items():
        g = pd.concat(gs)
        r = {"지표": k, "점검 수": len(g), "통과": int(g["통과"].sum()), "통과율(%)": round(100 * g["통과"].mean(), 1)}
        if k == "식단 위반":
            r.update({"끼니": int(g["끼니"].sum()), "위반 끼니": int(g["위반 끼니"].sum()),
                      "위반율(%)": round(100 * g["위반 끼니"].sum() / max(g["끼니"].sum(), 1), 2),
                      "표시 안 된 위반 끼니": int(g["표시 안 된 위반 끼니"].sum()),
                      "표시 안 된 위반율(%)": round(100 * g["표시 안 된 위반 끼니"].sum() / max(g["끼니"].sum(), 1), 2),
                      "확장 기준 끼니(검토)": int(g["확장 기준 끼니"].sum())})
        out.append(r)
    return pd.DataFrame(out)


def by_domain(df: pd.DataFrame) -> pd.DataFrame:
    return (df.groupby("영역", sort=False)["통과"].agg(["count", "sum", "mean"])
            .rename(columns={"count": "점검 수", "sum": "통과", "mean": "통과율(%)"})
            .assign(**{"통과율(%)": lambda d: (100 * d["통과율(%)"]).round(1)}))


def expert_form(scen: list, system_answers: list, result: dict, path: Path):
    """전문가 평가지 — 1_독립판정(시스템 결과 없이) · 2_시스템결과(판정 후 적절성 평가) · 보기"""
    def describe(s):
        f = s["features"]
        bmi = f["weight_kg"] / (f["height_cm"] / 100) ** 2
        parts = [f"{f['age']}세 {'여' if f['female'] else '남'}", f"BMI {bmi:.1f}", f"MNA-SF {f['mna_sf']}",
                 f"K-MBI {f['kmbi_score']}/{f['kmbi_max']}", f"혈압 {f['sbp']}/{f['dbp']}", f"MMSE {f['mmse']}",
                 f"섭취율 {f.get('intake_rate', 85)}%", f"현재 식사형태 {s['meal_form'].replace('일반밥', '밥')}"]
        if f["diseases"]:
            parts.append("질환 " + "·".join(f["diseases"]))
        if f.get("chewing_difficulty"):
            parts.append("저작곤란")
        if f.get("swallowing_difficulty"):
            parts.append("연하곤란")
        if f.get("eating_dependence"):
            parts.append("식사 도움 필요")
        meds = [m["name"] for m in s["ehr"]["medications"]] + (f.get("medications") or [])
        if meds:
            parts.append("복용약 " + ", ".join(meds))
        if s["ehr"]["allergies"]:
            parts.append("알레르기 " + ", ".join(a["allergen"] for a in s["ehr"]["allergies"]))
        return " · ".join(parts)

    rows1 = []
    for s in scen:
        r = {"시나리오": s["id"], "어르신 정보": describe(s)}
        r.update({f"문제:{lab}": "" for lab, _ in PROBLEM_CATS})
        r["권장 식사형태"] = ""
        r.update({f"충돌:{cid}": "" for cid in CONFLICT_OPTIONS})
        r["피해야 할 식재료(자유 기술)"] = ""
        r["메모"] = ""
        rows1.append(r)
    sys_by = {x["시나리오"]: x for x in system_answers}
    rows2 = []
    for s in scen:
        a = sys_by.get(s["id"], {})
        eid = f"SC_{s['id']}"
        syn = ((result.get("assessments") or {}).get(eid) or {}).get("synth") or {}
        top = [p.get("title") for p in (syn.get("priorities") or [])[:5]]
        cons = syn.get("constraints") or {}
        crit = ", ".join(f"{k} {round(v['value'], 1)}" for k, v in cons.items()
                         if k in ("energy_min", "protein_min", "sodium_max", "sugar_max", "potassium_min"))
        rows2.append({"시나리오": s["id"], "시스템 주요 문제(우선순위 순)": " / ".join(top),
                      "피할 식재료": a.get("피할 식재료", ""), "권장 식사형태": a.get("권장 식사형태", ""),
                      "충돌 처리": ", ".join(CONFLICT_OPTIONS[c][0] for c in CONFLICT_OPTIONS if a.get(f"충돌:{c}") == "A"),
                      "끼니 기준": crit, "적절성(적절/부분 적절/부적절)": "", "의견": ""})
    guide = [{"항목": "작성 순서", "설명": "① '1_독립판정'을 먼저 작성 → ② 그 뒤에 '2_시스템결과'를 열어 적절성 평가 (순서를 바꾸면 판정이 시스템 결과에 끌려감)"},
             {"항목": "문제:○○", "설명": "해당하면 1, 아니면 0"},
             {"항목": "권장 식사형태", "설명": " / ".join(FORM_OPTIONS)},
             *[{"항목": f"충돌:{cid}", "설명": f"해당 충돌이 있다고 보면 A 또는 B, 없으면 빈칸 — A: {o[0]} / B: {o[1]}"}
               for cid, o in CONFLICT_OPTIONS.items()],
             {"항목": "적절성", "설명": "적절 / 부분 적절 / 부적절"}]
    with pd.ExcelWriter(path) as w:
        pd.DataFrame(guide).to_excel(w, sheet_name="보기", index=False)
        pd.DataFrame(rows1).to_excel(w, sheet_name="1_독립판정", index=False)
        pd.DataFrame(rows2).to_excel(w, sheet_name="2_시스템결과", index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", action="store_true", help="AI 영역 전문가·임상 영양사·충돌 전문가 켬")
    ap.add_argument("--preset", default="quick", help="공통 최적화 강도 (quick/standard)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(BACKEND / "scripts" / "validate_scenarios_result.xlsx"))
    ap.add_argument("--dump", help=argparse.SUPPRESS)
    ap.add_argument("--form", default=str(BACKEND / "scripts" / "expert_form.xlsx"))
    a = ap.parse_args()
    if a.ai:
        from dotenv import load_dotenv
        load_dotenv(BACKEND / ".env")

    scen = json.loads(SCEN_JSON.read_text(encoding="utf-8"))["scenarios"]
    residents, assess, settings, ehr = scenario_inputs(scen)
    from diet import pipeline as P
    mode = "llm" if a.ai else "off"
    print(f"시나리오 {len(scen)}개 · 설계 실행 ({'AI 켬' if a.ai else '규칙 모드'}, {a.preset}) …")
    result = P.run_design(residents, assess, settings, None, None, preset=a.preset, seed=a.seed, ehr=ehr,
                          selector="rule", reviewer="off", refiner=mode, agent_mode="llm" if a.ai else "rule",
                          progress=lambda m: None)
    df, menu_rows, sys_ans = evaluate(scen, result)
    if a.dump:
        import pickle
        pickle.dump(result, open(a.dump, "wb"))
    summ, dom = summarize(df), by_domain(df)
    fails = df[~df["통과"]]

    print("\n=== 지표별 ===")
    print(summ.to_string(index=False))
    print("\n=== 영역별 ===")
    print(dom.to_string())
    print(f"\n=== 통과하지 못한 점검 {len(fails)}건 ===")
    print(fails[["시나리오", "점검", "기대", "결과"]].to_string(index=False) if len(fails) else "없음")

    with pd.ExcelWriter(a.out) as w:
        pd.DataFrame([{"항목": "시나리오", "값": len(scen)}, {"항목": "모드", "값": "AI 켬" if a.ai else "규칙 모드 (LLM 없음)"},
                      {"항목": "공통 최적화", "값": f"{a.preset} · seed {a.seed}"},
                      {"항목": "주의", "값": "확장 기준은 사람이 검토할 후보 (예: 간장·고추장의 대두·밀) — 위반율에는 넣지 않음"}]
                     ).to_excel(w, sheet_name="설정", index=False)
        summ.to_excel(w, sheet_name="지표별", index=False)
        dom.to_excel(w, sheet_name="영역별")
        df.to_excel(w, sheet_name="점검_상세", index=False)
        (menu_rows if len(menu_rows) else pd.DataFrame([{"내용": "위반·검토 대상 끼니 없음"}])).to_excel(w, sheet_name="식단_위반·검토", index=False)
        pd.DataFrame(sys_ans).to_excel(w, sheet_name="시스템_판정", index=False)
        pd.DataFrame([{"시나리오": s["id"], "영역": s["domain"], "내용": s["title"], **{k: json.dumps(v, ensure_ascii=False)
                       for k, v in s["expected"].items()}} for s in scen]).to_excel(w, sheet_name="시나리오_정답", index=False)
    expert_form(scen, sys_ans, result, Path(a.form))
    print("\n결과:", a.out, "\n전문가 평가지:", a.form)


if __name__ == "__main__":
    main()
