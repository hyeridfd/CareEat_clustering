# -*- coding: utf-8 -*-
"""영역별 평가 에이전트 7종 — 각자 자기 영역 정보(CONTEXT_KEYS)만 보고 독립적으로 판단

  신체·영양   BodyAgent         체격·영양 위험·기능 → 목표 열량, 단백질 필요, 저체중·영양불량
  당뇨        DiabetesAgent     당뇨 진단·약 → 당류·포화지방 상한, 저혈당 위험
  고혈압      HypertensionAgent 고혈압 진단·혈압·약·실제 나트륨 섭취 → 나트륨·지방 상한, 칼륨·식이섬유
  인지        CognitionAgent    치매·MMSE·우울 → 뇌건강 식재료, 식사 도움
  구강·연하   OralAgent         저작·연하 곤란, 식사형태 → 다지기·갈기·죽 (안전 조건)
  섭취·선호   IntakeAgent       조사 기간 실제 섭취(목측) → 부족 영양소, 잘 안 드시는 칸
  약물·알레르기 MedicationAgent (medication.py)

  영양 기준 숫자·문제 점수·판정 임계값은 data/guideline_rules.json 에서 읽는다 (근거 지침 문단과 연결된 표).
  [2026-11-10] 코드에 박혀 있던 숫자를 그 파일로 옮김 — 값은 그대로이며 회귀 검사로 결과가 같음을 확인.
"""
from __future__ import annotations

import json
import os

from .base import DomainAgent

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_KDRI = None
_RULES = None


def rules() -> dict:
    """근거 연결 규칙표 (data/guideline_rules.json)"""
    global _RULES
    if _RULES is None:
        _RULES = json.load(open(os.path.join(DATA_DIR, "guideline_rules.json"), encoding="utf-8"))
    return _RULES


def T(name: str) -> float:
    """판정 임계값"""
    return rules()["thresholds"][name]["value"]


def SC(code: str, variant: str | None = None) -> dict:
    """문제 점수 {severity, urgency, modifiability} (variant 가 있으면 그 단계 값)"""
    r = rules()["issues"][code]
    base = {k: r[k] for k in ("severity", "urgency", "modifiability") if k in r}
    if variant:
        base.update(r["variants"][variant])
    return base


def C(key: str) -> dict:
    """기준값 한 줄 (예: 'diabetes.sugar_max')"""
    return rules()["constraints"][key]


E_MIN, E_MAX = C("kdri.energy_min")["value"], C("kdri.energy_max")["value"]   # 공통(KDRI) 끼니 열량 범위


def _num(v, d=None):
    try:
        f = float(v)
        return d if f != f else f
    except (TypeError, ValueError):
        return d


def _has(lst, *kws):
    return any(any(k in str(x) for k in kws) for x in (lst or []))


def kdri(female: bool, age: float) -> dict:
    global _KDRI
    if _KDRI is None:
        _KDRI = json.load(open(os.path.join(DATA_DIR, "kdri_targets.json"), encoding="utf-8"))
    base = _KDRI["female" if female else "male"]
    return base["75" if (age or 80) >= 75 else "65_74"]


def _clip01(x):
    return max(0.0, min(1.0, x))


# [2026-11-09] 혈압 기준 고혈압: 수축기 ≥140 mmHg 또는 이완기 ≥90 mmHg (대한고혈압학회 2026 진료지침의 진단 기준)
# 값은 guideline_rules.json thresholds.sbp_htn / dbp_htn


def bp_hypertension(sbp, dbp) -> bool:
    return (_num(sbp, 0) or 0) >= T("sbp_htn") or (_num(dbp, 0) or 0) >= T("dbp_htn")


# ─────────────────────────── 신체·영양 ───────────────────────────
def _specs(agent) -> list:
    """[2026-11-10] 그 영역의 끼니 기준 전부 (예: 당뇨 = 식단형 규격 + 당뇨병학회). 같은 영양소가 여러 개면
    종합(manager.resolve_constraints)에서 KDRI 공통까지 셋 중 가장 엄격한 값이 고른다"""
    pre = agent.NAME + "."
    return [_spec(agent, k[len(pre):]) for k, r in rules()["constraints"].items()
            if k.startswith(pre) and r.get("unit") in ("abs", "pctE")]


def strictest(prefixes, nutrient: str, bound: str):
    """요약 문구용: 여러 출처 중 가장 엄격한 절대값 (열량 비율 기준은 제외)"""
    vals = [r["value"] for k, r in rules()["constraints"].items()
            if k.split(".")[0] in prefixes and r["nutrient"] == nutrient and r["bound"] == bound and r.get("unit") == "abs"]
    return (min(vals) if bound == "max" else max(vals)) if vals else None


def adjusted_weight(w, h_cm, bmi, female) -> float:
    """[2026-11-10] 열량·단백질 계산용 체중. BMI 25 이상(비만)이면 조정체중:
    조정체중 = 표준체중 + (실제체중 − 표준체중) × 0.25,  표준체중 = 키(m)² × 22(남) / 21(여)
    키가 없으면 BMI 로 키² 를 역산 (체중 ÷ BMI)"""
    if not w or not bmi or bmi < T("protein_weight_bmi_cap"):
        return w
    h2 = (h_cm / 100) ** 2 if h_cm and h_cm > 100 else w / bmi
    std = h2 * T("std_bmi_female" if female else "std_bmi_male")
    return round(std + (w - std) * T("adj_weight_factor"), 1)


def _spec(agent, key):
    """guideline_rules.json 기준값 → ConstraintSpec"""
    c = C(f"{agent.NAME}.{key}")
    kw = {"unit": "pctE", "kcal_per_g": c["kcal_per_g"]} if c.get("unit") == "pctE" else {}
    return agent.spec(c["nutrient"], c["bound"], c["value"], source=c["source"], **kw)


class BodyAgent(DomainAgent):
    NAME, LABEL = "body", "신체·영양"
    CONTEXT_KEYS = ("age", "female", "height_cm", "weight_kg", "bmi", "mna_sf", "mna_risk", "kmbi_score", "kmbi_max")

    def assess(self, c):
        from ..patient_profile_final import calc_target_energy, Sex
        a = self._a()
        bmi, age = c.get("bmi"), c.get("age") or 80
        female = bool(c.get("female"))
        # 목표 열량: BMI 기반 (허리둘레는 조사 항목에 없어 성별 기본값) — 기존 PatientProfile 과 같은 식
        #   [2026-11-10] 열량 범위는 공통(KDRI 450~700) 또는 질환(식단형 500~800)과 합친 범위 → 종합에서 다시 계산.
        #   여기서는 BMI 점수(0~1)를 넘기고, 임시 목표 열량은 공통 범위로 계산
        from ..patient_profile_final import bmi_score, waist_score
        sex = Sex.FEMALE if female else Sex.MALE
        score = max(0.0, min(1.0, bmi_score(bmi or 22.0) + waist_score(82.0 if female else 87.0, sex)))
        e = calc_target_energy(bmi or 22.0, 82.0 if female else 87.0, sex, energy_min=E_MIN, energy_max=E_MAX)
        a.outputs["energy_score"] = round(score, 3)
        # [2026-11-10] ESPEN R1: 하루 30 kcal/kg — BMI 25 이상이면 조정체중 (단백질과 같은 방식)
        w0, h0 = c.get("weight_kg"), c.get("height_cm")
        if w0:
            wt0 = adjusted_weight(w0, h0, bmi, female)
            e = round(C("body.energy_per_kg")["value"] * wt0 / 3, 0)
            a.outputs["energy_by_weight"] = e
            a.outputs["energy_weight_used"] = wt0
        a.outputs["target_energy"] = e
        w = c.get("weight_kg")
        if bmi is not None and bmi < T("bmi_underweight"):
            a.issues.append(self.issue(code="underweight", title=f"저체중 (BMI {bmi})", **SC("underweight"),
                                       nutrients=["energy", "protein"], action="increase",
                                       evidence=[f"BMI {bmi}"], source="ESPEN_GERIATRIC"))
        elif bmi is not None and bmi >= T("bmi_obese"):
            a.issues.append(self.issue(code="obesity", title=f"비만 (BMI {bmi}) — 고령자는 감량보다 근육 유지",
                                       **SC("obesity"), nutrients=["energy"], action="monitor",
                                       evidence=[f"BMI {bmi}"], source="ESPEN_GERIATRIC"))
        # [2026-11-11] MNA-SF 점수로 판정: 0~7 영양불량 · 8~11 영양불량 위험 · 12~14 정상
        #   (mna_risk 는 '12점 미만 = 1' 인 0/1 값 — 점수가 없을 때만 '위험'으로 사용)
        sf, mr = c.get("mna_sf"), c.get("mna_risk")
        level = None
        if sf is not None:
            level = "malnourished" if sf <= T("mna_malnourished_max") else "risk" if sf <= T("mna_risk_max") else None
            ev = [f"MNA-SF {sf:.0f}점"]
        elif mr is not None and mr >= 1:
            level, ev = "risk", ["MNA-SF 12점 미만 (점수 없음)"]
        if level:
            a.issues.append(self.issue(code="malnutrition_risk",
                                       title="영양불량 (MNA-SF)" if level == "malnourished" else "영양불량 위험 (MNA-SF)",
                                       **SC("malnutrition_risk", level), nutrients=["energy", "protein"],
                                       action="increase", evidence=ev, source="ESPEN_GERIATRIC"))
        ks, km = c.get("kmbi_score"), c.get("kmbi_max")
        if ks is not None and km:
            pct = ks / km
            if pct < T("kmbi_low_ratio"):
                a.issues.append(self.issue(code="sarcopenia_risk", title=f"일상생활 기능 저하 (K-MBI {pct * 100:.0f}%) — 근감소 위험",
                                           **SC("sarcopenia_risk"), nutrients=["protein"], action="increase",
                                           evidence=[f"K-MBI {ks:.0f}/{km:.0f}"], source="SARCOPENIA_KR"))
        # [2026-11-10] 단백질 개인 하한 = max(공통 기준 하루 50 g ÷ 3, 체중 × g/kg ÷ 3)
        #   ESPEN R2: 노인 최소 1.0 g/kg/일, 영양불량·저체중·근감소 위험이면 1.2 g/kg/일 이상
        if w:
            risk = any(i.code in ("underweight", "malnutrition_risk", "sarcopenia_risk") for i in a.issues)
            per_kg = C("body.protein_per_kg_risk" if risk else "body.protein_need_per_kg")["value"]
            from ..base_standard import PROTEIN_DAILY_MIN
            # 비만이면 실제 체중 대신 조정체중(표준체중 + 초과분 × 0.25)으로 계산 — 과도한 하한 방지
            wt = adjusted_weight(w, c.get("height_cm"), bmi, female)
            need = round(max(PROTEIN_DAILY_MIN / 3, per_kg * wt / 3), 1)
            a.outputs["protein_need_meal"] = need
            a.outputs["protein_per_kg"] = per_kg
            if wt != w:
                a.outputs["protein_weight_used"] = wt
            a.constraints.append(self.spec("protein", "min", need, source="ESPEN_GERIATRIC"))
        a.summary = f"목표 열량 {e:.0f}kcal/끼" + (" (30kcal/kg" + (f", 조정체중 {a.outputs['energy_weight_used']}kg" if a.outputs.get("energy_weight_used") != w else "") + ")"
                                                 if "energy_by_weight" in a.outputs else "") + (f" · BMI {bmi}" if bmi else "") + \
                    (f" · 단백질 ≥{a.outputs['protein_need_meal']}g/끼 ({a.outputs['protein_per_kg']}g/kg"
                     + (f", 조정체중 {a.outputs['protein_weight_used']}kg" if "protein_weight_used" in a.outputs else "") + ")"
                     if "protein_need_meal" in a.outputs else "")
        return a


# ─────────────────────────── 당뇨 ───────────────────────────
class DiabetesAgent(DomainAgent):
    NAME, LABEL = "diabetes", "당뇨"
    CONTEXT_KEYS = ("diseases", "dx_diabetes", "medications", "intake_rate", "cmt_diabetic")

    def applicable(self, c):
        return _has(c.get("diseases"), "당뇨") or (c.get("dx_diabetes") or 0) >= 1

    def assess(self, c):
        a = self._a()
        a.constraints += _specs(self)          # 식단형 규격 + 당뇨병학회 (더 엄격한 값은 종합에서)
        sp = C("diabetes.sugar_max")["value"]
        a.issues.append(self.issue(code="sugar_control", title=f"당류 관리 (끼니 열량의 {sp * 100:.0f}% 이하)", **SC("sugar_control"),
                                   nutrients=["sugar"], action="limit", evidence=["당뇨 진단"],
                                   source="KDA_DM_2025"))
        on_drug = _has(c.get("medications"), "당뇨")
        rate = c.get("intake_rate")
        if on_drug and rate is not None and rate < T("hypo_intake_rate"):
            a.issues.append(self.issue(code="hypoglycemia_risk", title=f"당뇨약 복용 중 섭취율 낮음 ({rate * 100:.0f}%) — 저혈당 위험",
                                       **SC("hypoglycemia_risk"), nutrients=["energy"], action="increase",
                                       evidence=["당뇨병약 복용", f"평균 섭취율 {rate * 100:.0f}%"], source=rules()["issues"]["hypoglycemia_risk"]["source"]))
        a.summary = (f"당류 ≤{sp * 100:.0f}%E · 포화지방 ≤{C('diabetes.sat_fat_max')['value'] * 100:.0f}%E"
                     + (" · 당뇨약 복용" if on_drug else ""))
        return a


# ─────────────────────────── 고혈압 ───────────────────────────
class HypertensionAgent(DomainAgent):
    NAME, LABEL = "hypertension", "고혈압"
    CONTEXT_KEYS = ("diseases", "dx_hypertension", "sbp", "dbp", "medications", "na_day", "k_day", "age", "cmt_seasoning")

    def applicable(self, c):
        return _has(c.get("diseases"), "고혈압") or (c.get("dx_hypertension") or 0) >= 1 or bp_hypertension(c.get("sbp"), c.get("dbp"))

    def assess(self, c):
        a = self._a()
        dx_rec = _has(c.get("diseases"), "고혈압") or (c.get("dx_hypertension") or 0) >= 1
        sbp, dbp = c.get("sbp"), c.get("dbp")
        by_bp = bp_hypertension(sbp, dbp)
        dx = dx_rec or by_bp                 # 진단 기록이 없어도 혈압 기준을 넘으면 고혈압으로 판단
        a.outputs["hypertension_by_bp"] = by_bp and not dx_rec
        if dx:
            a.constraints += _specs(self)      # 식단형 규격 + 고혈압학회 (더 엄격한 값은 종합에서)
        stage = None
        if sbp or dbp:
            stage = 2 if ((sbp or 0) >= T("sbp_stage2") or (dbp or 0) >= T("dbp_stage2")) else 1 if by_bp else 0
        sc = SC("sodium_control", {2: "stage2", 1: "stage1", 0: "normal", None: "unknown"}[stage])
        bp_txt = (f"혈압 {sbp:.0f}/{dbp:.0f}" if sbp and dbp else f"수축기 {sbp:.0f}" if sbp else f"이완기 {dbp:.0f}" if dbp else None)
        ev = (["고혈압 진단"] if dx_rec else ["혈압 기준 고혈압 (수축기 ≥140 또는 이완기 ≥90)"] if by_bp else []) + ([bp_txt] if bp_txt else [])
        a.issues.append(self.issue(code="sodium_control", title="나트륨 제한" + (" (혈압 조절 안 됨)" if stage == 2 else ""),
                                   **sc, nutrients=["sodium"], action="limit",
                                   evidence=ev, source="KSH_HTN_2026"))
        na = c.get("na_day")
        if na:
            from ..sodium_config import daily_sodium_max_for_age
            cdrr = daily_sodium_max_for_age(int(c.get("age") or 80))
            if na > cdrr * T("na_intake_ratio"):
                a.issues.append(self.issue(code="sodium_intake_high", title=f"조사 기간 나트륨 섭취 {na:.0f}mg/일 (기준 {cdrr})",
                                           **SC("sodium_intake_high"), nutrients=["sodium"], action="limit",
                                           evidence=[f"목측 섭취 {na:.0f}mg/일"], source="KDRI2025"))
        if dx and c.get("k_day") is not None and c["k_day"] < T("k_day_low"):
            a.issues.append(self.issue(code="potassium_low", title=f"칼륨 섭취 부족 ({c['k_day']:.0f}mg/일)",
                                       **SC("potassium_low"), nutrients=["potassium"], action="increase",
                                       evidence=[f"목측 섭취 {c['k_day']:.0f}mg/일"], source="KSH_HTN_2026"))
        a.summary = ("혈압 기준 고혈압 (진단 기록 없음) · " if a.outputs["hypertension_by_bp"] else "") + \
                    (f"나트륨 ≤{strictest(('hypertension',), 'sodium', 'max'):,.0f}mg/끼(나이별 KDRI 가 더 엄격하면 그 값) · "
                     f"칼륨 ≥{strictest(('hypertension',), 'potassium', 'min'):.0f}mg · "
                     f"식이섬유 ≥{strictest(('hypertension',), 'fiber', 'min'):.0f}g (식단형 규격·고혈압학회 중 더 엄격한 값)") + \
                    (f" · {bp_txt}" if bp_txt else "")
        if a.outputs["hypertension_by_bp"]:
            a.notes.append(f"{bp_txt} — 고혈압 진단 기록은 없지만 혈압 기준({T('sbp_htn'):.0f}/{T('dbp_htn'):.0f})을 넘어 고혈압 식단 기준을 적용함. 의료진 확인 권장")
        return a


# ─────────────────────────── 인지 ───────────────────────────
class CognitionAgent(DomainAgent):
    NAME, LABEL = "cognition", "인지·정서"
    CONTEXT_KEYS = ("diseases", "dx_dementia", "mmse", "gds", "dx_depression", "eating_dependence")

    def applicable(self, c):
        return (_has(c.get("diseases"), "치매") or (c.get("dx_dementia") or 0) >= 1
                or (c.get("mmse") is not None and c["mmse"] < T("mmse_impaired"))
                or (c.get("gds") is not None and c["gds"] >= T("gds_depression"))
                or (c.get("dx_depression") or 0) >= 1)

    def assess(self, c):
        a = self._a()
        dem = _has(c.get("diseases"), "치매") or (c.get("dx_dementia") or 0) >= 1
        mmse = c.get("mmse")
        if dem or (mmse is not None and mmse < T("mmse_impaired")):
            severe = mmse is not None and mmse < T("mmse_severe")
            a.issues.append(self.issue(code="brain_food", title="뇌건강 식재료(생선·달걀·콩·녹색채소) 끼니마다",
                                       **SC("brain_food", "severe" if severe else "default"), nutrients=[], action="increase",
                                       evidence=(["치매 진단"] if dem else []) + ([f"MMSE {mmse:.0f}"] if mmse is not None else []),
                                       source="ESPEN_DEMENTIA"))
            a.outputs["brain_food"] = True
        dep = c.get("eating_dependence")
        if dep is not None and dep >= 1:
            a.issues.append(self.issue(code="eating_assist", title="식사 도움 필요 — 한입 크기·손으로 집기 쉬운 반찬",
                                       **SC("eating_assist"), action="monitor", evidence=[f"식사 의존도 {dep:.0f}"],
                                       source="ESPEN_DEMENTIA"))
        gds = c.get("gds")
        if (gds is not None and gds >= T("gds_depression")) or (c.get("dx_depression") or 0) >= 1:
            a.issues.append(self.issue(code="appetite_mood", title="우울 — 식욕 저하·섭취량 변화 관찰", **SC("appetite_mood"),
                                       nutrients=["energy"], action="monitor",
                                       evidence=[f"GDS {gds:.0f}"] if gds is not None else ["우울 진단"], source="ESPEN_GERIATRIC"))
        a.summary = " · ".join(i.title.split(" — ")[0] for i in a.issues) or "특이 사항 없음"
        return a


# ─────────────────────────── 구강·연하 ───────────────────────────
class OralAgent(DomainAgent):
    NAME, LABEL = "oral", "구강·연하"
    CONTEXT_KEYS = ("chewing_difficulty", "swallowing_difficulty", "texture_level", "meal_form")

    def applicable(self, c):
        return bool(c.get("chewing_difficulty") or c.get("swallowing_difficulty") or (c.get("texture_level") or 0) >= 1
                    or "다진" in str(c.get("meal_form")) or "갈" in str(c.get("meal_form")) or "죽" in str(c.get("meal_form")))

    def assess(self, c):
        a = self._a()
        form = str(c.get("meal_form") or "")
        if c.get("swallowing_difficulty"):
            a.issues.append(self.issue(code="aspiration_risk", title="연하곤란 — 흡인 위험, 갈찬·걸쭉한 국물",
                                       **SC("aspiration_risk"), action="texture", evidence=["연하곤란"], source="IDDSI"))
        if c.get("chewing_difficulty"):
            a.issues.append(self.issue(code="chewing", title="저작곤란 — 단단한 반찬은 다지기", **SC("chewing"),
                                       action="texture", evidence=["저작곤란"], source="IDDSI"))
        if c.get("swallowing_difficulty") and "갈" not in form:
            a.issues.append(self.issue(code="texture_mismatch", title=f"연하곤란인데 식사형태가 '{form or '일반'}' — 형태 재확인",
                                       **SC("texture_mismatch"), action="check",
                                       evidence=["연하곤란", f"식사형태 {form or '일반'}"], source="IDDSI"))
        a.outputs["texture"] = form
        a.summary = f"식사형태 {form or '일반'}" + ("" if not a.issues else " · " + a.issues[0].title.split(" — ")[0])
        return a


# ─────────────────────────── 섭취·선호 ───────────────────────────
class IntakeAgent(DomainAgent):
    NAME, LABEL = "intake", "섭취·선호"
    CONTEXT_KEYS = ("avg_day", "slot_rates", "intake_rate", "female", "age", "pref_meat", "pref_seafood", "pref_vegetable",
                    "pref_fruit", "cmt_portion", "cmt_seasoning")

    def assess(self, c):
        a = self._a()
        avg = c.get("avg_day") or {}
        t = kdri(bool(c.get("female")), c.get("age") or 80)
        lows = []
        ir = rules()["intake_rules"]
        for key, nut, label in (("energy", "energy", "열량"), ("protein", "protein", "단백질"),
                                ("fiber", "fiber", "식이섬유"), ("ca", None, "칼슘"), ("vd", None, "비타민 D")):
            sc = SC(f"{key}_intake_low")
            v, tg = _num(avg.get(key)), t.get(key)
            if v is None or not tg:
                continue
            pct = v / tg
            if pct < T("intake_low_ratio"):
                very = pct < T("intake_very_low")
                lows.append(f"{label} {pct * 100:.0f}%")
                a.issues.append(self.issue(code=f"{key}_intake_low", title=f"{label} 섭취 부족 (권장의 {pct * 100:.0f}%)",
                                           severity=_clip01(sc["severity"] + (ir["severity_bonus_very_low"] if very else 0)),
                                           urgency=ir["urgency_very_low"] if very else ir["urgency_low"],
                                           modifiability=sc["modifiability"], nutrients=[nut] if nut else [],
                                           action="increase", evidence=[f"목측 {v:.0f} / 권장 {tg}"], source="KDRI2025"))
        rates = c.get("slot_rates") or {}
        poor = [f"{s} {r * 100:.0f}%" for s, r in rates.items() if r is not None and r < T("slot_low_rate")]
        if poor:
            a.issues.append(self.issue(code="slot_low_intake", title="잘 안 드시는 칸: " + ", ".join(poor), **SC("slot_low_intake"),
                                       action="monitor", evidence=poor, source="LTC_MEAL_GUIDE"))
        a.outputs["slot_rates"] = rates
        r = c.get("intake_rate")
        if not avg and r is None:
            a.summary = "조사 기간 섭취 기록 없음"
            return a
        a.summary = " · ".join(x for x in ((f"평균 섭취율 {r * 100:.0f}%" if r is not None else ""),
                                          ("부족: " + ", ".join(lows) if lows else ""),
                                          ("" if avg else "영양소 계산 전(진단 재평가 필요)")) if x)
        return a
