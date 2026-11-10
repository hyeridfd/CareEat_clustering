# -*- coding: utf-8 -*-
"""도메인 에이전트 공통 구조 (NutriOrion 의 Stage 1 '병렬 독립 평가' 를 Care-Eat 식단 설계에 맞춘 것)

  · 각 에이전트는 CONTEXT_KEYS 에 적힌 정보만 받는다 (맥락 격리) → 다른 영역 판단에 끌려가지 않음
  · 산출물은 모두 구조화된 값 (자유 서술 아님):
      Issue       해결할 문제 1개 — 심각도·시급성·개선 가능성(0~1)과 근거
      ConstraintSpec  영양 기준 1개 — 절대값(mg, g) 또는 열량 비율(%E). 종합 단계에서 목표 열량으로 환산
      Avoid       피해야 할 식재료 (약물·알레르기) — hard=True 면 대체찬·제품 선택에서 절대 제외
  · 우선순위 점수 S(j) = w_sev·심각도 + w_urg·시급성 + w_mod·개선 가능성 (NutriOrion Eq.4)
  · 단, 안전성 문제(Level 1)는 S 와 무관하게 항상 먼저 (issue_level)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

W_SEV, W_URG, W_MOD = 0.5, 0.3, 0.2

# [2026-11-09] 우선순위 2단계
#   Level 1 안전성: 알레르기 · 연하(삼킴)·식사형태 안전 · 약물 상호작용(약물-식품, 저혈당)
#                  → 가중합 S 와 무관하게 항상 먼저 확인 (정렬·대체찬 모두 최우선)
#   Level 2 영양 중재: 영양불량 · 섭취 부족 · 단백질 부족 · 질환별 영양 관리 등 → S 로 순위
SAFETY_CODES = {"allergy", "aspiration_risk", "texture_mismatch", "chewing", "hypoglycemia_risk"}
SAFETY_AGENTS = {"medication"}          # 약물·알레르기 에이전트의 문제는 모두 안전성
LEVEL_LABEL = {1: "안전성", 2: "영양 중재"}


def issue_level(code: str, agent: str) -> int:
    return 1 if (code in SAFETY_CODES or agent in SAFETY_AGENTS) else 2


def sort_key(it) -> tuple:
    """Level 1 먼저, 같은 Level 안에서는 S 높은 순 (Issue 또는 dict)"""
    if isinstance(it, dict):
        return (it.get("level") or issue_level(it.get("code"), it.get("agent")), -float(it.get("priority") or 0))
    return (it.level, -it.priority)


# [2026-11-10] 3단계: Level 2 순위를 '파레토 우선순위'로
#   심각도·시급성·개선 가능성 세 축에서 다른 문제에 모두 뒤지는(지배당하는) 문제는 뒤로.
#   1순위 묶음(front 1) = 어느 문제에도 지배당하지 않는 문제들 → 그 안에서는 S 순.
#   가중치 0.5/0.3/0.2 를 정한 값에 순서가 덜 휘둘리게 하려는 것 (NutriOrion 다목적 우선순위).
#   대체찬 가중치는 그대로 0.5 + S (substitute_agent.priority_weights) — 순서는 보고·계획(ADIME)에 쓰인다.
_AX = ("severity", "urgency", "modifiability")


def _dominates(a: dict, b: dict) -> bool:
    ge = all(float(a.get(k) or 0) >= float(b.get(k) or 0) - 1e-9 for k in _AX)
    gt = any(float(a.get(k) or 0) > float(b.get(k) or 0) + 1e-9 for k in _AX)
    return ge and gt


def rank_priorities(items: list) -> list:
    """문제 dict 목록 → Level 1(S 순) + Level 2(파레토 묶음 → S 순). 각 dict 에 pareto_rank 기록 (Level 1 은 0)"""
    l1 = [i for i in items if (i.get("level") or issue_level(i.get("code"), i.get("agent"))) == 1]
    rest = [i for i in items if i not in l1]
    for i in l1:
        i["pareto_rank"] = 0
    front, left = 1, list(rest)
    while left:
        cur = [i for i in left if not any(_dominates(j, i) for j in left if j is not i)]
        for i in cur:
            i["pareto_rank"] = front
        left = [i for i in left if i not in cur]
        front += 1
    by_s = lambda i: -float(i.get("priority") or 0)
    return sorted(l1, key=by_s) + sorted(rest, key=lambda i: (i["pareto_rank"], by_s(i)))


@dataclass
class Issue:
    code: str                      # 예: "sodium_high", "hypoglycemia_risk"
    title: str                     # 화면 표시 문구
    severity: float                # 0~1 임상적 중요도
    urgency: float                 # 0~1 지금 손대야 하는 정도
    modifiability: float           # 0~1 식단(대체·배식)으로 바꿀 수 있는 정도
    nutrients: list = field(default_factory=list)    # 관련 영양소 키 (sodium, sugar …)
    action: str = "monitor"        # limit | increase | avoid | texture | monitor | check
    evidence: list = field(default_factory=list)     # 판단에 쓴 값 ["수축기 혈압 152", …]
    source: Optional[str] = None   # 근거 문헌 id (care/knowledge/sources.json) 또는 기준 이름
    agent: str = ""
    # [2026-11-10] LLM 영역 전문가 판단 (llm_agent.py) — 규칙 점수는 scores_rule 에 남긴다
    rationale: str = ""            # 판단 근거 문장 ([E1] 인용 포함)
    cites: list = field(default_factory=list)        # 인용한 근거 번호
    scores_rule: Optional[dict] = None

    @property
    def priority(self) -> float:
        return round(W_SEV * self.severity + W_URG * self.urgency + W_MOD * self.modifiability, 3)

    @property
    def level(self) -> int:
        return issue_level(self.code, self.agent)

    def to_dict(self):
        return {**asdict(self), "priority": self.priority, "level": self.level, "level_label": LEVEL_LABEL[self.level]}


@dataclass
class ConstraintSpec:
    nutrient: str                  # energy | protein | sugar | sat_fat | fat | sodium | potassium | fiber
    bound: str                     # min | max
    value: float
    unit: str = "abs"              # abs (g·mg·kcal 끼니당) | pctE (끼니 열량의 비율, kcal/g 로 환산)
    kcal_per_g: float = 0.0        # pctE 환산용 (당류 4, 지방 9)
    source: Optional[str] = None
    agent: str = ""

    def resolve(self, energy: float) -> float:
        if self.unit == "pctE":
            return round(energy * self.value / self.kcal_per_g, 2)
        return self.value

    def to_dict(self):
        return asdict(self)


@dataclass
class Avoid:
    keywords: list                 # 식재료·제품 이름에 들어가면 해당 (예: ["자몽"])
    reason: str
    hard: bool = True              # True: 대체찬·제품에서 절대 제외 / False: 주의 표시만
    min_g: float = 0.0             # 메뉴 안 해당 식재료 양이 이 이상일 때만 (예: 녹색 잎채소 30g)
    severity: float = 0.8
    source: Optional[str] = None
    agent: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Assessment:
    agent: str
    label: str
    active: bool
    summary: str = ""
    issues: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    avoid: list = field(default_factory=list)
    notes: list = field(default_factory=list)     # 식단으로 다루지 않는 돌봄 안내 (복약 시간 등)
    context_keys: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)   # 다른 단계가 쓸 값 (예: target_energy)
    evidence: list = field(default_factory=list)  # 근거 문단 목록 (rag.evidence_for 의 refs)
    llm: Optional[dict] = None                    # LLM 영역 전문가 판단 기록 (mode, model, summary, warnings …)

    def to_dict(self):
        return {"agent": self.agent, "label": self.label, "active": self.active, "summary": self.summary,
                "issues": [i.to_dict() for i in self.issues], "constraints": [c.to_dict() for c in self.constraints],
                "avoid": [a.to_dict() for a in self.avoid], "notes": self.notes,
                "context_keys": self.context_keys, "outputs": self.outputs,
                **({"evidence": self.evidence} if self.evidence else {}), **({"llm": self.llm} if self.llm else {})}


class DomainAgent:
    NAME = "base"
    LABEL = ""
    CONTEXT_KEYS: tuple = ()

    def applicable(self, ctx: dict) -> bool:          # 관리자가 활성화 여부를 정할 때 사용
        return True

    def assess(self, ctx: dict) -> Assessment:        # ctx 에는 CONTEXT_KEYS 만 들어 있다
        raise NotImplementedError

    # 편의 함수
    def _a(self, active=True, **kw) -> Assessment:
        return Assessment(agent=self.NAME, label=self.LABEL, active=active, context_keys=list(self.CONTEXT_KEYS), **kw)

    def issue(self, **kw) -> Issue:
        return Issue(agent=self.NAME, **kw)

    def spec(self, *a, **kw) -> ConstraintSpec:
        return ConstraintSpec(*a, agent=self.NAME, **kw)

    def avoid(self, **kw) -> Avoid:
        return Avoid(agent=self.NAME, **kw)
