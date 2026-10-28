# -*- coding: utf-8 -*-
"""약물·알레르기 에이전트 — 복용 약·알레르기 → 피해야 할 식재료(절대 조건)와 복약 안내

  입력 (이 에이전트만 봄)
    medications       기초조사표 '복용 약물' 종류 (고혈압약·항혈전제 …)
    med_records       어르신 기록 탭의 약 [{name, food_caution, is_active}]
    allergy_records   어르신 기록 탭의 알레르기 [{allergen, severity}]
  지식베이스  data/drug_food_rules.json (약물-식품 상호작용 규칙 · 알레르기 식재료 묶음)

  · 약 이름이 규칙에 맞으면 avoid/limit → 대체찬·제품에서 제외 (안전 게이트)
  · 종류만 알면 check → '약 이름 확인 필요' (종류 전체를 금기로 묶지 않음)
  · 기록 탭의 '음식 주의' 메모는 그대로 안내에 싣는다 (자유 서술은 식재료로 바꾸지 않음)
"""
from __future__ import annotations

import json
import os

from .base import DomainAgent

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_KB = None
SEV = {"severe": 1.0, "moderate": 0.85, "mild": 0.7}


def kb() -> dict:
    global _KB
    if _KB is None:
        _KB = json.load(open(os.path.join(DATA_DIR, "drug_food_rules.json"), encoding="utf-8"))
    return _KB


def allergen_groups(text: str) -> list:
    """'갑각류(새우)' → [갑각류 묶음]. 앞에서 맞은 단어는 지우고 계속 (예: '땅콩' 이 '콩'(대두)으로 다시 잡히지 않게)"""
    t, out = str(text), []
    for g in kb()["allergens"]:
        hit = [m for m in g["match"] if m in t]
        if hit:
            out.append(g)
            for m in hit:
                t = t.replace(m, " ")
    return out


class MedicationAgent(DomainAgent):
    NAME, LABEL = "medication", "약물·알레르기"
    CONTEXT_KEYS = ("medications", "med_records", "allergy_records")

    def applicable(self, c):
        meds = [m for m in (c.get("medications") or []) if m and "복용하지 않음" not in str(m)]
        return bool(meds or c.get("med_records") or c.get("allergy_records"))

    def assess(self, c):
        a = self._a()
        cats = [str(m) for m in (c.get("medications") or []) if m and "복용하지 않음" not in str(m)]
        recs = [m for m in (c.get("med_records") or []) if m.get("is_active", True) is not False]
        names = " ".join(str(m.get("name") or "") for m in recs).lower()
        fired = set()
        for r in kb()["rules"]:
            by_name = any(k.lower() in names for k in r["match_names"])
            by_cat = any(any(k in cat for k in r["match_categories"]) for cat in cats)
            if not (by_name or by_cat):
                continue
            if r["id"] == "antithrombotic_check" and "warfarin_vitk" in fired:
                continue                                  # 와파린이 이미 확인됨
            action = r["action"]
            # 종류로만 맞았는데 규칙이 특정 약에만 해당하면(match_names 있음) → 확인 필요로 낮춤
            if action in ("avoid", "limit") and not by_name and r["match_names"]:
                action = "check_strong" if r["id"] == "grapefruit_statin_ccb" else "check"
            fired.add(r["id"])
            ev = ([m.get("name") for m in recs if any(k.lower() in str(m.get("name") or "").lower() for k in r["match_names"])]
                  or [cat for cat in cats if any(k in cat for k in r["match_categories"])])
            if action in ("avoid", "limit", "check_strong") and r["ingredients"]:
                # 자몽처럼 피하기 쉬운 식품은 종류만 알아도 제외(값싼 예방), 나머지는 약 이름이 확인될 때만
                a.avoid.append(self.avoid(keywords=r["ingredients"], reason=r["title"], hard=True,
                                          min_g=float(r.get("min_g") or 0), severity=r["severity"], source=r["source"]))
            a.issues.append(self.issue(
                code=r["id"], title=r["title"] + (" — 약 이름 확인 필요" if action == "check" else ""),
                severity=r["severity"], urgency=r["urgency"],
                modifiability=0.9 if action in ("avoid", "limit", "check_strong") else 0.2,
                action={"check_strong": "avoid"}.get(action, action), evidence=[str(x) for x in ev], source=r["source"]))
            a.notes.append(f"{r['title']}: {r['effect']}")
        for m in recs:
            fc = (m.get("food_caution") or "").strip()
            if fc:
                a.notes.append(f"{m.get('name')}: {fc} (기록 탭 메모)")
        for al in c.get("allergy_records") or []:
            groups = allergen_groups(al.get("allergen", ""))
            sev = SEV.get(str(al.get("severity") or "mild"), 0.7)
            kws = sorted({k for g in groups for k in g["ingredients"]}) or [str(al.get("allergen")).strip()]
            label = "/".join(g["group"] for g in groups) or str(al.get("allergen"))
            a.avoid.append(self.avoid(keywords=kws, reason=f"알레르기: {label}", hard=True, severity=sev,
                                      source="알레르기 기록"))
            a.issues.append(self.issue(code="allergy", title=f"알레르기 {al.get('allergen')} ({al.get('severity') or 'mild'})",
                                       severity=sev, urgency=0.9, modifiability=0.9, action="avoid",
                                       evidence=[al.get("reaction") or al.get("allergen")], source="알레르기 기록"))
        a.outputs["fired_rules"] = sorted(fired)
        a.summary = (f"복용 {len(recs) or len(cats)}종" + (f" · 피할 식재료 {sum(len(x.keywords) for x in a.avoid)}개" if a.avoid else "")
                     + (f" · 확인 필요 {sum(1 for i in a.issues if i.action == 'check')}건" if any(i.action == 'check' for i in a.issues) else ""))
        return a
