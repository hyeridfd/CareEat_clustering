# -*- coding: utf-8 -*-
"""[2026-11-11] 개인화 에이전트 그래프 (LangGraph) — 어르신 1명 = 그래프 1회 실행

  노드 (모두 이 파일의 build() 에 정의)
    · 영역 7개 × 3단계 = 21개      <영역>  →  (AI 영역 전문가 켬) <영역>_rag  →  <영역>_expert
        <영역>          규칙 선별 (domain.py / medication.py) — 그 영역 맥락만 봄
        <영역>_rag      근거 검색 (rag.py) — 그 영역 문헌에서 연결 조항 + 의미 검색
        <영역>_expert   영역 결론 — 근거가 있으면 LLM 영역 전문가 판단·코드 검증 (llm_agent.decide), 없으면 규칙 결과 그대로
        route_domain: AI 영역 전문가를 켰고 그 영역이 활성이면 "rag", 아니면 "expert" (근거 검색 건너뜀)
        7개 영역은 START 에서 동시에 갈라져 병렬로 실행된다 (서로의 결과를 보지 않음)
    · synthesize        1단계 종합 — 7개 <영역>_expert 가 모두 끝나면 (합류)
    · refine            2단계 AI 임상 영양사 (route_after_synthesize = "refine" 일 때)
    · 3단계 종합·안전성 6개 (agents/synthesis.py 단계 함수)
        safety_check → rank_priorities → detect_conflicts
          → (route_conflicts: AI 임상 영양사 켬 + LLM 이 맡을 충돌 있음) conflict_specialist → apply_locks
          → (그 외) apply_locks
        → hard_constraints → END

  · 상태의 work 는 {영역: {"a": Assessment, "sub": 맥락, "ev": 근거}} — 병렬 노드가 자기 영역 칸만 쓰고 합쳐짐
  · 여러 어르신: 시설 그래프(diet/workflow.py)가 Send 로 어르신마다 이 그래프를 실행하거나, run() 이 batch 로 실행
  · langgraph 가 없으면 available() = False → 기존 스레드 풀 경로 (manager.assess_residents / pipeline.apply_agents)
  · 흐름도: python -m scripts.check_langgraph --mermaid
"""
from __future__ import annotations

import json
import operator  # noqa: F401  (Annotated 리듀서 예시와의 일관성)
from typing import Annotated, TypedDict

from .manager import AGENTS, _slice, synthesize

AGENT_ORDER = [ag.NAME for ag in AGENTS]

try:                                               # 설치 여부 (requirements.txt: langgraph)
    from langgraph.graph import END, START, StateGraph
    from langchain_core.runnables import RunnableConfig
    _OK = True
except Exception:                                  # pragma: no cover
    _OK = False
    RunnableConfig = dict                          # type: ignore


def available() -> bool:
    return _OK


def merge(a: dict | None, b: dict | None) -> dict:
    """병렬 노드가 서로 다른 칸을 쓰면 합친다 (같은 칸이면 나중 값)"""
    return {**(a or {}), **(b or {})}


class ResidentState(TypedDict, total=False):
    eid: str
    ctx: dict
    work: Annotated[dict, merge]      # {영역: {"a", "sub", "ev"}}
    synth: dict                       # 현재 개인 기준·우선순위
    stage1: dict                      # 1단계 종합 사본 (3단계 잠금·허용 범위의 기준점)
    refine: dict                      # 2단계 결과
    s3: dict                          # 3단계 작업 상태 (synthesis.s3_* 이 이어 받음)


def _cfg(config) -> dict:
    return (config or {}).get("configurable") or {}


# ─────────────────────────── 영역 노드 (7 × 3) ───────────────────────────
def _rule_node(ag):
    def node(state: ResidentState) -> dict:
        ctx = state.get("ctx") or {}
        sub = _slice(ctx, ag.CONTEXT_KEYS)
        try:
            a = ag.assess(sub) if (ag.NAME == "body" or ag.applicable(sub)) else ag._a(active=False, summary="해당 없음")
        except Exception as e:
            a = ag._a(active=False, summary=f"평가 오류: {e}")
        return {"work": {ag.NAME: {"a": a, "sub": sub, "ev": None}}}
    node.__name__ = f"rule_{ag.NAME}"
    return node


def _route_domain(ag):
    def route(state: ResidentState, config: RunnableConfig) -> str:
        w = (state.get("work") or {}).get(ag.NAME) or {}
        return "rag" if (_cfg(config).get("judge") and w.get("a") is not None and w["a"].active) else "expert"
    route.__name__ = f"route_{ag.NAME}"
    return route


def _rag_node(ag):
    def node(state: ResidentState) -> dict:
        from .llm_agent import gather
        w = dict(state["work"][ag.NAME])
        w["ev"] = gather(ag, w["sub"], w["a"], state.get("ctx") or {})
        return {"work": {ag.NAME: w}}
    node.__name__ = f"rag_{ag.NAME}"
    return node


def _expert_node(ag):
    def node(state: ResidentState, config: RunnableConfig) -> dict:
        from .llm_agent import decide
        w = state["work"][ag.NAME]
        judge = _cfg(config).get("judge")
        if judge and w.get("ev"):
            decide(ag, w["sub"], w["a"], w["ev"], caller=getattr(judge, "caller", None))
        return {"work": {ag.NAME: {**w, "done": True}}}
    node.__name__ = f"expert_{ag.NAME}"
    return node


def _ordered(state) -> list:
    work = state.get("work") or {}
    return [work[n]["a"] for n in AGENT_ORDER if n in work]


# ─────────────────────────── 종합 · 정제 ───────────────────────────
def synthesize_node(state: ResidentState) -> dict:
    syn = synthesize(_ordered(state), (state.get("ctx") or {}).get("age") or 80)
    return {"synth": syn, "stage1": json.loads(json.dumps(syn, default=str))}


def route_after_synthesize(state: ResidentState, config: RunnableConfig) -> str:
    c = _cfg(config)
    if c.get("upto") == "stage1":
        return "end"
    return "refine" if c.get("refiner") == "llm" else "safety_check"


def refine_node(state: ResidentState, config: RunnableConfig) -> dict:
    from .refine import _eligible, apply_refine, refine_one
    c = _cfg(config)
    res = {"agents": _ordered(state), "synth": state["synth"]}
    if not _eligible(res):
        return {"refine": {"mode": "none"}}
    try:
        r = refine_one(state.get("ctx") or {}, res, caller=c.get("refine_caller"), prev=(c.get("prev") or {}).get(state["eid"]))
    except Exception as e:
        r = {"mode": "rule", "note": f"AI 임상 영양사 실패 → 1단계 결과 사용: {str(e)[:160]}"}
    syn = apply_refine(state["synth"], r)
    if r.get("mode") == "llm":
        r = {**r, "energy_rescaled": syn.get("energy_rescaled") or []}
    return {"synth": syn, "refine": r}


# ─────────────────────────── 3단계 종합·안전성 (6) ───────────────────────────
def safety_check_node(state: ResidentState) -> dict:
    from .synthesis import s3_safety, s3_start
    return {"s3": s3_safety(s3_start(state["synth"], state.get("stage1")))}


def rank_priorities_node(state: ResidentState) -> dict:
    from .synthesis import s3_rank
    return {"s3": s3_rank(state["s3"])}


def detect_conflicts_node(state: ResidentState) -> dict:
    from .synthesis import s3_detect
    return {"s3": s3_detect(state["s3"], state.get("ctx") or {})}


def route_conflicts(state: ResidentState, config: RunnableConfig) -> str:
    from .synthesis import needs_specialist
    return "conflict_specialist" if needs_specialist(state["s3"], _cfg(config).get("refiner") == "llm") else "apply_locks"


def conflict_specialist_node(state: ResidentState, config: RunnableConfig) -> dict:
    from .synthesis import s3_specialists
    return {"s3": s3_specialists(state["s3"], state.get("ctx") or {}, _cfg(config).get("specialist_caller"))}


def apply_locks_node(state: ResidentState) -> dict:
    from .synthesis import s3_locks
    return {"s3": s3_locks(state["s3"])}


def hard_constraints_node(state: ResidentState, config: RunnableConfig) -> dict:
    from .synthesis import s3_hard
    syn = s3_hard(state["s3"], state.get("ctx") or {}, _ordered(state), _cfg(config).get("refiner") == "llm")
    return {"synth": syn}


_COMPILED = None


def build():
    """그래프 정의 → compile (한 번만)"""
    global _COMPILED
    if _COMPILED is not None:
        return _COMPILED
    if not _OK:
        raise RuntimeError("langgraph 가 설치되지 않았습니다 (pip install langgraph)")
    g = StateGraph(ResidentState)
    for ag in AGENTS:
        n = ag.NAME
        g.add_node(n, _rule_node(ag))
        g.add_node(f"{n}_rag", _rag_node(ag))
        g.add_node(f"{n}_expert", _expert_node(ag))
        g.add_edge(START, n)                                         # START → 7개 영역 (병렬 분기)
        g.add_conditional_edges(n, _route_domain(ag), {"rag": f"{n}_rag", "expert": f"{n}_expert"})
        g.add_edge(f"{n}_rag", f"{n}_expert")
    g.add_node("synthesize", synthesize_node)
    g.add_edge([f"{n}_expert" for n in AGENT_ORDER], "synthesize")   # 7개 영역 결론이 모두 나와야 종합 (합류)
    g.add_node("refine", refine_node)
    g.add_node("safety_check", safety_check_node)
    g.add_node("rank_priorities", rank_priorities_node)
    g.add_node("detect_conflicts", detect_conflicts_node)
    g.add_node("conflict_specialist", conflict_specialist_node)
    g.add_node("apply_locks", apply_locks_node)
    g.add_node("hard_constraints", hard_constraints_node)
    g.add_conditional_edges("synthesize", route_after_synthesize,
                            {"refine": "refine", "safety_check": "safety_check", "end": END})
    g.add_edge("refine", "safety_check")
    g.add_edge("safety_check", "rank_priorities")
    g.add_edge("rank_priorities", "detect_conflicts")
    g.add_conditional_edges("detect_conflicts", route_conflicts,
                            {"conflict_specialist": "conflict_specialist", "apply_locks": "apply_locks"})
    g.add_edge("conflict_specialist", "apply_locks")
    g.add_edge("apply_locks", "hard_constraints")
    g.add_edge("hard_constraints", END)
    _COMPILED = g.compile()
    return _COMPILED


def resident_config(judge=None, refiner: str = "off", prev: dict | None = None, upto: str = "all",
                    refine_caller=None, specialist_caller=None) -> dict:
    return {"judge": judge, "refiner": refiner, "prev": prev or {}, "upto": upto,
            "refine_caller": refine_caller, "specialist_caller": specialist_caller}


def resident_input(eid: str, ctx: dict) -> dict:
    return {"eid": eid, "ctx": ctx or {}, "work": {}}


def result_of(st: dict) -> dict:
    return {"agents": _ordered(st), "synth": st["synth"], "stage1": st.get("stage1"), "refine": st.get("refine") or {}}


def run(contexts: dict, judge=None, refiner: str = "off", prev: dict | None = None, upto: str = "all",
        max_concurrency: int = 8, refine_caller=None, specialist_caller=None) -> dict:
    """{eid: ctx} → {eid: {"agents", "synth", "stage1", "refine"}} — 어르신마다 그래프 1회, 여러 명은 batch 로 동시에"""
    app = build()
    eids = list(contexts)
    config = {"max_concurrency": max_concurrency,
              "configurable": resident_config(judge, refiner, prev, upto, refine_caller, specialist_caller)}
    outs = app.batch([resident_input(e, contexts[e]) for e in eids], config=config)
    return {e: result_of(st) for e, st in zip(eids, outs)}


def mermaid() -> str:
    """실제 컴파일된 그래프의 흐름도 (Mermaid 문법)"""
    return build().get_graph().draw_mermaid()
