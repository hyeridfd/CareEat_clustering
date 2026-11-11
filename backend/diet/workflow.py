# -*- coding: utf-8 -*-
"""[2026-11-11] 맞춤 식단 설계 전체 워크플로우 (LangGraph 시설 그래프)

    START → build_profiles
          ─(Send: 어르신마다)→ personalize_resident      개인화 에이전트 그래프 1회 (agents/graph.py, 29개 노드)
          → apply_profiles                                개인 기준·목표 열량·피할 식재료·우선순위 가중치를 프로필에 반영
          → optimize                                      공통 식단 NSGA-II (KDRI 공통 기준)
          → select_menu                                   파레토 후보 중 선택 (AI 영양사 또는 균형점 규칙)
          → repair_repeats                                반복 메뉴 보정
          → (route_review: reviewer = "llm") review_menu   AI 식단 검토 → 코드 검증 후 반영
          → build_menu                                    식단표·지표
          → meal_form → substitute → serve                식사형태 → 개인 대체찬 → 개인 배식률
          → assemble → END                                배식표·충족 요약·대체찬 지침·발주

  · 노드 함수는 기존 pipeline.py 의 함수를 그대로 부른다 (계산은 바뀌지 않음)
  · langgraph 가 없으면 run_sequential() 이 같은 노드 함수를 순서대로 부른다 (어르신 개인화는 스레드 풀)
  · ADIME 계획은 화면에서 요청할 때만 만드는 별도 기능이라 그래프에 넣지 않았다 (agents/care_plan.py)
  · 흐름도: python -m scripts.check_langgraph --mermaid  (시설 그래프 + 개인화 그래프)
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, TypedDict

from .agents import graph as RG

try:
    from langgraph.graph import END, START, StateGraph
    from langchain_core.runnables import RunnableConfig
    try:
        from langgraph.types import Send
    except Exception:                                     # 예전 버전
        from langgraph.constants import Send  # type: ignore
    _OK = True
except Exception:                                         # pragma: no cover
    _OK = False
    RunnableConfig = dict                                 # type: ignore


def available() -> bool:
    return _OK


class FacilityState(TypedDict, total=False):
    inp: dict                                   # run_design 인자
    profiles: Any
    meta: dict
    skipped: list
    personal: Annotated[dict, RG.merge]         # {eid: 개인화 그래프 결과} — 어르신별 Send 결과가 합쳐짐
    agent_json: dict
    pool: dict
    inv: Any
    inv_model: Any
    problem: Any
    nsga: Any
    t0: Any
    fctx: dict
    pick: dict
    chrom: Any
    before: dict
    repairs: Any
    review: Any
    records: list
    metrics: dict
    ps: dict
    result: dict


def _say(config):
    return ((config or {}).get("configurable") or {}).get("progress") or (lambda *_: None)


# ─────────────────────────── 노드 ───────────────────────────
def build_profiles(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import build_profiles as bp
    i = state["inp"]
    _say(config)("어르신 프로파일 생성")
    profiles, meta, skipped = bp(i["residents"], i["assessments"], i["settings"], i.get("ehr"))
    if not profiles:
        raise ValueError("식단 설계에 쓸 어르신이 없습니다. 진단 화면에서 평가를 먼저 실행하세요.")
    return {"profiles": profiles, "meta": meta, "skipped": skipped}


def fan_out_residents(state: FacilityState):
    """어르신마다 개인화 그래프 실행 (Send — 같은 단계에서 동시에)"""
    return [Send("personalize_resident", {"eid": p.name, "ctx": getattr(p, "context", {}) or {}})
            for p in state["profiles"]]


def personalize_resident(payload: dict, config: RunnableConfig) -> dict:
    c = (config or {}).get("configurable") or {}
    st = RG.build().invoke(RG.resident_input(payload["eid"], payload["ctx"]),
                           config={"configurable": c.get("resident") or {}})
    return {"personal": {payload["eid"]: RG.result_of(st)}}


def apply_profiles(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import _finish_agents, _sync_meta
    i = state["inp"]
    res = {e: {"agents": v["agents"], "synth": v["synth"]} for e, v in state["personal"].items()}
    refs = {e: v["refine"] for e, v in state["personal"].items() if i.get("refiner") == "llm" and v.get("refine")}
    agent_json = _finish_agents(state["profiles"], res, refs)
    _sync_meta(state["profiles"], state["meta"])
    return {"agent_json": agent_json}


def optimize(state: FacilityState, config: RunnableConfig) -> dict:
    from . import nsga2
    from .base_standard import BaseStandard
    from .inventory import InventoryModel
    from .pipeline import BUDGET_PER_MEAL, PRESETS, MealPlanProblem, harmony_table, inventory_from_rows, load_pool
    i, say = state["inp"], _say(config)
    pref, inventory = i.get("preference") or {}, i.get("inventory") or {}
    pool = load_pool(pref.get("pool_scores"))
    inv = inventory_from_rows(inventory.get("items"), inventory.get("start_date"))
    inv_model = InventoryModel(pool, inv, len(state["profiles"])) if inv else None
    problem = MealPlanProblem(pool, BaseStandard(), BUDGET_PER_MEAL, inventory=inv_model, harmony=harmony_table(pool))
    pop, gen = PRESETS.get(i.get("preset"), PRESETS["standard"])
    say(f"일반식 최적화 (개체 {pop} · 세대 {gen})")
    t0 = dt.datetime.now()
    nsga = nsga2.minimize(problem, pop_size=pop, n_gen=gen, seed=i.get("seed", 42),
                          progress=lambda g, n, f1: say(f"일반식 최적화 {g}/{n}세대 · f1 {f1:.3f}"))
    return {"pool": pool, "inv": inv, "inv_model": inv_model, "problem": problem, "nsga": nsga, "t0": t0}


def select_menu(state: FacilityState, config: RunnableConfig) -> dict:
    from .llm_select import choose, facility_context
    from .pipeline import BUDGET_PER_MEAL
    i, problem = state["inp"], state["problem"]
    Xf, Ff, _, _ = state["nsga"]
    fctx = facility_context(state["profiles"], state["meta"], state["agent_json"],
                            (i.get("inventory") or {}).get("start_date"), BUDGET_PER_MEAL)
    pick = choose(problem, Xf, Ff, problem.constraint, fctx, mode=i.get("selector", "llm"), progress=_say(config))
    return {"fctx": fctx, "pick": pick, "chrom": Xf[pick["index"]]}


def repair_repeats(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import repair_repeats as rr
    _say(config)("반복 메뉴 보정")
    before = state["problem"].pattern_breakdown(state["chrom"])
    chrom, repairs = rr(state["problem"], state["chrom"])
    return {"chrom": chrom, "before": before, "repairs": repairs, "review": None}


def route_review(state: FacilityState) -> str:
    return "review_menu" if state["inp"].get("reviewer") == "llm" else "build_menu"


def review_menu(state: FacilityState, config: RunnableConfig) -> dict:
    from .llm_review import review_menu as rv
    chrom, review = rv(state["problem"], state["chrom"], state["fctx"], progress=_say(config))
    return {"chrom": chrom, "review": review}


def build_menu(state: FacilityState) -> dict:
    from .pipeline import menu_records, plan_metrics
    i, problem, chrom, pick = state["inp"], state["problem"], state["chrom"], state["pick"]
    _, Ff, _, Fa = state["nsga"]
    records = menu_records(problem, chrom)
    metrics = plan_metrics(problem, chrom, Ff, Fa, state.get("inv_model"))
    from .pipeline import PRESETS
    pop, gen = PRESETS.get(i.get("preset"), PRESETS["standard"])
    metrics["review"] = state.get("review")
    metrics["selection_rule"] = pick["selection"].get("rule")
    metrics["selection"] = pick["selection"]
    metrics["repeat_repair"] = {"changes": state["repairs"],
                                "before": {k: v for k, v in state["before"].items() if k.startswith("반복")}}
    metrics["optimize_sec"] = round((dt.datetime.now() - state["t0"]).total_seconds(), 1)
    metrics["preset"] = {"name": i.get("preset"), "pop": pop, "gen": gen}
    return {"records": records, "metrics": metrics}


def meal_form(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import ps_begin, ps_meal_form
    pref = state["inp"].get("preference") or {}
    ps = ps_begin(state["pool"], state["records"], state["profiles"], state.get("inv_model"), pref.get("product_scores"))
    return {"ps": ps_meal_form(ps, _say(config))}


def substitute(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import ps_substitute
    return {"ps": ps_substitute(state["ps"], _say(config))}


def serve(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import ps_end, ps_serve
    try:
        return {"ps": ps_serve(state["ps"], _say(config))}
    finally:
        ps_end(state["ps"])


def assemble(state: FacilityState, config: RunnableConfig) -> dict:
    from .pipeline import ps_assemble
    i = state["inp"]
    pref = i.get("preference") or {}
    pers = ps_assemble(state["ps"], state["meta"], _say(config), state.get("inv"))
    return {"result": {"menu": state["records"], "metrics": state["metrics"], "skipped": state["skipped"],
                       "n_residents": len(state["profiles"]), "inventory_used": state.get("inv") is not None,
                       "preference_used": bool(pref.get("pool_scores")), "assessments": state["agent_json"], **pers}}


# ─────────────────────────── 그래프 ───────────────────────────
_COMPILED = None
LINE = ["optimize", "select_menu", "repair_repeats"]
TAIL = ["build_menu", "meal_form", "substitute", "serve", "assemble"]
NODES = {"build_profiles": build_profiles, "personalize_resident": personalize_resident, "apply_profiles": apply_profiles,
         "optimize": optimize, "select_menu": select_menu, "repair_repeats": repair_repeats, "review_menu": review_menu,
         "build_menu": build_menu, "meal_form": meal_form, "substitute": substitute, "serve": serve, "assemble": assemble}


def build():
    global _COMPILED
    if _COMPILED is not None:
        return _COMPILED
    if not _OK:
        raise RuntimeError("langgraph 가 설치되지 않았습니다 (pip install langgraph)")
    g = StateGraph(FacilityState)
    for n, f in NODES.items():
        g.add_node(n, f)
    g.add_edge(START, "build_profiles")
    g.add_conditional_edges("build_profiles", fan_out_residents, ["personalize_resident"])
    g.add_edge("personalize_resident", "apply_profiles")
    g.add_edge("apply_profiles", "optimize")
    g.add_edge("optimize", "select_menu")
    g.add_edge("select_menu", "repair_repeats")
    g.add_conditional_edges("repair_repeats", route_review, {"review_menu": "review_menu", "build_menu": "build_menu"})
    g.add_edge("review_menu", "build_menu")
    for a, b in zip(TAIL, TAIL[1:]):
        g.add_edge(a, b)
    g.add_edge("assemble", END)
    _COMPILED = g.compile()
    return _COMPILED


def _config(inp: dict, progress=None, max_concurrency: int = 8, judge=None) -> dict:
    return {"max_concurrency": max_concurrency, "recursion_limit": 100,
            "configurable": {"progress": progress,
                             "resident": RG.resident_config(judge, inp.get("refiner", "off"), inp.get("prev"))}}


def run(inp: dict, progress=None, judge=None) -> dict:
    """LangGraph 로 전체 설계 실행 → run_design 과 같은 결과 dict"""
    st = build().invoke({"inp": inp, "personal": {}}, config=_config(inp, progress, judge=judge))
    return st["result"]


def run_sequential(inp: dict, progress=None, judge=None) -> dict:
    """langgraph 없이 같은 노드 함수를 순서대로 (어르신 개인화는 pipeline.apply_agents — 스레드 풀)"""
    from .pipeline import apply_agents, _sync_meta
    cfg = _config(inp, progress, judge=judge)
    st: dict = {"inp": inp, "personal": {}}

    def step(f, *a):
        st.update(f(st, *a) or {})
    step(build_profiles, cfg)
    st["agent_json"] = apply_agents(st["profiles"], progress, inp.get("refiner", "off"), inp.get("prev"),
                                    agent_mode=inp.get("agent_mode", "rule"))
    _sync_meta(st["profiles"], st["meta"])
    for n in LINE:
        step(NODES[n], cfg)
    if route_review(st) == "review_menu":
        step(review_menu, cfg)
    step(build_menu)
    for n in TAIL[1:]:
        step(NODES[n], cfg)
    return st["result"]


def mermaid() -> str:
    return build().get_graph().draw_mermaid()
