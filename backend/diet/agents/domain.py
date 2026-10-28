# -*- coding: utf-8 -*-
"""영역별 평가 에이전트 7종 — 각자 자기 영역 정보(CONTEXT_KEYS)만 보고 독립적으로 판단

  신체·영양   BodyAgent         체격·영양 위험·기능 → 목표 열량, 단백질 필요, 저체중·영양불량
  당뇨        DiabetesAgent     당뇨 진단·약 → 당류·포화지방 상한, 저혈당 위험
  고혈압      HypertensionAgent 고혈압 진단·혈압·약·실제 나트륨 섭취 → 나트륨·지방 상한, 칼륨·식이섬유
  인지        CognitionAgent    치매·MMSE·우울 → 뇌건강 식재료, 식사 도움
  구강·연하   OralAgent         저작·연하 곤란, 식사형태 → 다지기·갈기·죽 (안전 조건)
  섭취·선호   IntakeAgent       조사 기간 실제 섭취(목측) → 부족 영양소, 잘 안 드시는 칸
  약물·알레르기 MedicationAgent (medication.py)

  영양 기준 숫자는 기존 patient_profile_final.DISEASE_CRITERIA 와 같다 (출처만 에이전트별로 기록).
"""
from __future__ import annotations

import json
import os

from .base import DomainAgent

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
E_MIN, E_MAX = 500, 800
_KDRI = None


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


# ─────────────────────────── 신체·영양 ───────────────────────────
class BodyAgent(DomainAgent):
    NAME, LABEL = "body", "신체·영양"
    CONTEXT_KEYS = ("age", "female", "height_cm", "weight_kg", "bmi", "mna_risk", "kmbi_score", "kmbi_max")

    def assess(self, c):
        from ..patient_profile_final import calc_target_energy, Sex
        a = self._a()
        bmi, age = c.get("bmi"), c.get("age") or 80
        female = bool(c.get("female"))
        # 목표 열량: BMI 기반 (허리둘레는 조사 항목에 없어 성별 기본값) — 기존 PatientProfile 과 같은 식
        e = calc_target_energy(bmi or 22.0, 82.0 if female else 87.0, Sex.FEMALE if female else Sex.MALE)
        a.outputs["target_energy"] = e
        a.constraints += [self.spec("energy", "min", E_MIN, source="LTC_MEAL_GUIDE"),
                          self.spec("energy", "max", E_MAX, source="LTC_MEAL_GUIDE")]
        w = c.get("weight_kg")
        if w:
            need = round(1.0 * w / 3, 1)            # ESPEN 노인 1.0 g/kg/일 → 끼니
            a.outputs["protein_need_meal"] = need
        if bmi is not None and bmi < 18.5:
            a.issues.append(self.issue(code="underweight", title=f"저체중 (BMI {bmi})", severity=0.8, urgency=0.7,
                                       modifiability=0.7, nutrients=["energy", "protein"], action="increase",
                                       evidence=[f"BMI {bmi}"], source="ESPEN_GERIATRIC"))
        elif bmi is not None and bmi >= 27:
            a.issues.append(self.issue(code="obesity", title=f"비만 (BMI {bmi}) — 고령자는 감량보다 근육 유지",
                                       severity=0.4, urgency=0.2, modifiability=0.5, nutrients=["energy"], action="monitor",
                                       evidence=[f"BMI {bmi}"], source="ESPEN_GERIATRIC"))
        mna = c.get("mna_risk")
        if mna is not None and mna >= 1:
            sev = 0.9 if mna >= 2 else 0.6
            a.issues.append(self.issue(code="malnutrition_risk", title="영양불량" + (" " if mna >= 2 else " 위험 ") + "(MNA-SF)",
                                       severity=sev, urgency=sev, modifiability=0.7, nutrients=["energy", "protein"],
                                       action="increase", evidence=[f"MNA 위험 단계 {int(mna)}"], source="ESPEN_GERIATRIC"))
        ks, km = c.get("kmbi_score"), c.get("kmbi_max")
        if ks is not None and km:
            pct = ks / km
            if pct < 0.5:
                a.issues.append(self.issue(code="sarcopenia_risk", title=f"일상생활 기능 저하 (K-MBI {pct * 100:.0f}%) — 근감소 위험",
                                           severity=0.6, urgency=0.4, modifiability=0.5, nutrients=["protein"], action="increase",
                                           evidence=[f"K-MBI {ks:.0f}/{km:.0f}"], source="SARCOPENIA_KR"))
        a.summary = f"목표 열량 {e:.0f}kcal/끼" + (f" · BMI {bmi}" if bmi else "") + \
                    (f" · 단백질 필요 {a.outputs['protein_need_meal']}g/끼" if "protein_need_meal" in a.outputs else "")
        return a


# ─────────────────────────── 당뇨 ───────────────────────────
class DiabetesAgent(DomainAgent):
    NAME, LABEL = "diabetes", "당뇨"
    CONTEXT_KEYS = ("diseases", "dx_diabetes", "medications", "intake_rate", "cmt_diabetic")

    def applicable(self, c):
        return _has(c.get("diseases"), "당뇨") or (c.get("dx_diabetes") or 0) >= 1

    def assess(self, c):
        a = self._a()
        a.constraints += [
            self.spec("sugar", "max", 0.10, unit="pctE", kcal_per_g=4, source="KDA_DM_2025"),
            self.spec("protein", "min", 18, source="KDA_DM_2025"),
            self.spec("sat_fat", "max", 0.10, unit="pctE", kcal_per_g=9, source="KDA_DM_2025"),
            self.spec("sodium", "max", 1350, source="KDA_DM_2025"),
        ]
        a.issues.append(self.issue(code="sugar_control", title="당류 관리 (끼니 열량의 10% 이하)", severity=0.7, urgency=0.5,
                                   modifiability=0.8, nutrients=["sugar"], action="limit", evidence=["당뇨 진단"],
                                   source="KDA_DM_2025"))
        on_drug = _has(c.get("medications"), "당뇨")
        rate = c.get("intake_rate")
        if on_drug and rate is not None and rate < 0.6:
            a.issues.append(self.issue(code="hypoglycemia_risk", title=f"당뇨약 복용 중 섭취율 낮음 ({rate * 100:.0f}%) — 저혈당 위험",
                                       severity=0.9, urgency=0.9, modifiability=0.6, nutrients=["energy"], action="increase",
                                       evidence=["당뇨병약 복용", f"평균 섭취율 {rate * 100:.0f}%"], source="KDA_DM_2025"))
        a.summary = "당류 ≤10%E · 포화지방 ≤10%E" + (" · 당뇨약 복용" if on_drug else "")
        return a


# ─────────────────────────── 고혈압 ───────────────────────────
class HypertensionAgent(DomainAgent):
    NAME, LABEL = "hypertension", "고혈압"
    CONTEXT_KEYS = ("diseases", "dx_hypertension", "sbp", "dbp", "medications", "na_day", "k_day", "age", "cmt_seasoning")

    def applicable(self, c):
        return _has(c.get("diseases"), "고혈압") or (c.get("dx_hypertension") or 0) >= 1 or (c.get("sbp") or 0) >= 140

    def assess(self, c):
        a = self._a()
        dx = _has(c.get("diseases"), "고혈압") or (c.get("dx_hypertension") or 0) >= 1
        sbp, dbp = c.get("sbp"), c.get("dbp")
        if dx:
            a.constraints += [
                self.spec("fat", "min", 0.15, unit="pctE", kcal_per_g=9, source="KSH_HTN_2026"),
                self.spec("fat", "max", 0.30, unit="pctE", kcal_per_g=9, source="KSH_HTN_2026"),
                self.spec("sat_fat", "max", 0.07, unit="pctE", kcal_per_g=9, source="KSH_HTN_2026"),
                self.spec("sodium", "max", 1350, source="KSH_HTN_2026"),
                self.spec("potassium", "min", 700, source="KSH_HTN_2026"),
                self.spec("fiber", "min", 7, source="KSH_HTN_2026"),
            ]
        stage = None
        if sbp:
            stage = 2 if (sbp >= 160 or (dbp or 0) >= 100) else 1 if (sbp >= 140 or (dbp or 0) >= 90) else 0
        sev = {2: 0.9, 1: 0.7, 0: 0.5, None: 0.6}[stage]
        urg = {2: 0.8, 1: 0.6, 0: 0.3, None: 0.5}[stage]
        ev = (["고혈압 진단"] if dx else []) + ([f"혈압 {sbp:.0f}/{dbp:.0f}" if dbp else f"수축기 {sbp:.0f}"] if sbp else [])
        a.issues.append(self.issue(code="sodium_control", title="나트륨 제한" + (" (혈압 조절 안 됨)" if stage == 2 else ""),
                                   severity=sev, urgency=urg, modifiability=0.8, nutrients=["sodium"], action="limit",
                                   evidence=ev, source="KSH_HTN_2026"))
        na = c.get("na_day")
        if na:
            from ..sodium_config import daily_sodium_max_for_age
            cdrr = daily_sodium_max_for_age(int(c.get("age") or 80))
            if na > cdrr * 1.3:
                a.issues.append(self.issue(code="sodium_intake_high", title=f"조사 기간 나트륨 섭취 {na:.0f}mg/일 (기준 {cdrr})",
                                           severity=0.7, urgency=0.6, modifiability=0.7, nutrients=["sodium"], action="limit",
                                           evidence=[f"목측 섭취 {na:.0f}mg/일"], source="KDRI2025"))
        if dx and c.get("k_day") is not None and c["k_day"] < 2000:
            a.issues.append(self.issue(code="potassium_low", title=f"칼륨 섭취 부족 ({c['k_day']:.0f}mg/일)", severity=0.4,
                                       urgency=0.3, modifiability=0.6, nutrients=["potassium"], action="increase",
                                       evidence=[f"목측 섭취 {c['k_day']:.0f}mg/일"], source="KSH_HTN_2026"))
        if not dx:
            a.summary = f"고혈압 진단은 없지만 혈압 {sbp:.0f}{'/' + format(dbp, '.0f') if dbp else ''} — 진단 확인 필요"
            a.issues[-1].action = "check"
        else:
            a.summary = "나트륨 ≤1,350mg/끼(나이별 기준이 더 엄격하면 그 값) · 칼륨 ≥700mg · 식이섬유 ≥7g" + \
                        (f" · 혈압 {sbp:.0f}/{dbp:.0f}" if sbp and dbp else "")
        return a


# ─────────────────────────── 인지 ───────────────────────────
class CognitionAgent(DomainAgent):
    NAME, LABEL = "cognition", "인지·정서"
    CONTEXT_KEYS = ("diseases", "dx_dementia", "mmse", "gds", "dx_depression", "eating_dependence")

    def applicable(self, c):
        return (_has(c.get("diseases"), "치매") or (c.get("dx_dementia") or 0) >= 1
                or (c.get("mmse") is not None and c["mmse"] < 24) or (c.get("gds") is not None and c["gds"] >= 8)
                or (c.get("dx_depression") or 0) >= 1)

    def assess(self, c):
        a = self._a()
        dem = _has(c.get("diseases"), "치매") or (c.get("dx_dementia") or 0) >= 1
        mmse = c.get("mmse")
        if dem or (mmse is not None and mmse < 24):
            sev = 0.7 if (mmse is not None and mmse < 18) else 0.5
            a.issues.append(self.issue(code="brain_food", title="뇌건강 식재료(생선·달걀·콩·녹색채소) 끼니마다", severity=sev,
                                       urgency=0.3, modifiability=0.8, nutrients=[], action="increase",
                                       evidence=(["치매 진단"] if dem else []) + ([f"MMSE {mmse:.0f}"] if mmse is not None else []),
                                       source="ESPEN_DEMENTIA"))
            a.outputs["brain_food"] = True
        dep = c.get("eating_dependence")
        if dep is not None and dep >= 1:
            a.issues.append(self.issue(code="eating_assist", title="식사 도움 필요 — 한입 크기·손으로 집기 쉬운 반찬", severity=0.5,
                                       urgency=0.4, modifiability=0.4, action="monitor", evidence=[f"식사 의존도 {dep:.0f}"],
                                       source="ESPEN_DEMENTIA"))
        gds = c.get("gds")
        if (gds is not None and gds >= 8) or (c.get("dx_depression") or 0) >= 1:
            a.issues.append(self.issue(code="appetite_mood", title="우울 — 식욕 저하·섭취량 변화 관찰", severity=0.5, urgency=0.4,
                                       modifiability=0.3, nutrients=["energy"], action="monitor",
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
            a.issues.append(self.issue(code="aspiration_risk", title="연하곤란 — 흡인 위험, 갈찬·걸쭉한 국물", severity=0.9,
                                       urgency=0.8, modifiability=0.6, action="texture", evidence=["연하곤란"], source="IDDSI"))
        if c.get("chewing_difficulty"):
            a.issues.append(self.issue(code="chewing", title="저작곤란 — 단단한 반찬은 다지기", severity=0.6, urgency=0.5,
                                       modifiability=0.8, action="texture", evidence=["저작곤란"], source="IDDSI"))
        if c.get("swallowing_difficulty") and "갈" not in form:
            a.issues.append(self.issue(code="texture_mismatch", title=f"연하곤란인데 식사형태가 '{form or '일반'}' — 형태 재확인",
                                       severity=0.8, urgency=0.8, modifiability=0.9, action="check",
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
        for key, nut, label, sev in (("energy", "energy", "열량", 0.7), ("protein", "protein", "단백질", 0.8),
                                     ("fiber", "fiber", "식이섬유", 0.4), ("ca", None, "칼슘", 0.4), ("vd", None, "비타민 D", 0.3)):
            v, tg = _num(avg.get(key)), t.get(key)
            if v is None or not tg:
                continue
            pct = v / tg
            if pct < 0.75:
                lows.append(f"{label} {pct * 100:.0f}%")
                a.issues.append(self.issue(code=f"{key}_intake_low", title=f"{label} 섭취 부족 (권장의 {pct * 100:.0f}%)",
                                           severity=_clip01(sev + (0.15 if pct < 0.5 else 0)), urgency=0.6 if pct < 0.5 else 0.4,
                                           modifiability=0.7 if nut else 0.4, nutrients=[nut] if nut else [],
                                           action="increase", evidence=[f"목측 {v:.0f} / 권장 {tg}"], source="KDRI2025"))
        rates = c.get("slot_rates") or {}
        poor = [f"{s} {r * 100:.0f}%" for s, r in rates.items() if r is not None and r < 0.5]
        if poor:
            a.issues.append(self.issue(code="slot_low_intake", title="잘 안 드시는 칸: " + ", ".join(poor), severity=0.4, urgency=0.4,
                                       modifiability=0.6, action="monitor", evidence=poor, source="LTC_MEAL_GUIDE"))
        a.outputs["slot_rates"] = rates
        r = c.get("intake_rate")
        if not avg and r is None:
            a.summary = "조사 기간 섭취 기록 없음"
            return a
        a.summary = " · ".join(x for x in ((f"평균 섭취율 {r * 100:.0f}%" if r is not None else ""),
                                          ("부족: " + ", ".join(lows) if lows else ""),
                                          ("" if avg else "영양소 계산 전(진단 재평가 필요)")) if x)
        return a
