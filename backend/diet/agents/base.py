# -*- coding: utf-8 -*-
"""도메인 에이전트 공통 구조 (NutriOrion 의 Stage 1 '병렬 독립 평가' 를 Care-Eat 식단 설계에 맞춘 것)

  · 각 에이전트는 CONTEXT_KEYS 에 적힌 정보만 받는다 (맥락 격리) → 다른 영역 판단에 끌려가지 않음
  · 산출물은 모두 구조화된 값 (자유 서술 아님):
      Issue       해결할 문제 1개 — 심각도·시급성·개선 가능성(0~1)과 근거
      ConstraintSpec  영양 기준 1개 — 절대값(mg, g) 또는 열량 비율(%E). 종합 단계에서 목표 열량으로 환산
      Avoid       피해야 할 식재료 (약물·알레르기) — hard=True 면 대체찬·제품 선택에서 절대 제외
  · 우선순위 점수 S(j) = w_sev·심각도 + w_urg·시급성 + w_mod·개선 가능성 (NutriOrion Eq.4)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

W_SEV, W_URG, W_MOD = 0.5, 0.3, 0.2


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

    @property
    def priority(self) -> float:
        return round(W_SEV * self.severity + W_URG * self.urgency + W_MOD * self.modifiability, 3)

    def to_dict(self):
        return {**asdict(self), "priority": self.priority}


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

    def to_dict(self):
        return {"agent": self.agent, "label": self.label, "active": self.active, "summary": self.summary,
                "issues": [i.to_dict() for i in self.issues], "constraints": [c.to_dict() for c in self.constraints],
                "avoid": [a.to_dict() for a in self.avoid], "notes": self.notes,
                "context_keys": self.context_keys, "outputs": self.outputs}


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
