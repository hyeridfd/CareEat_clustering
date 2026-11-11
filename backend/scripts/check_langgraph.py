# -*- coding: utf-8 -*-
"""LangGraph 워크플로우 점검 — 설치 확인 · 흐름도 · 기존 경로와 결과 비교 (LLM 없음, 합성 어르신 6명)

    pip install "langgraph>=1.0,<2"
    python -m scripts.check_langgraph            # 결과가 '같음'이면 정상
    python -m scripts.check_langgraph --mermaid  # 흐름도만 → scripts/facility_graph.mmd, scripts/agent_graph.mmd
    python -m scripts.check_langgraph --png      # 흐름도 그림 → scripts/facility_graph.png, scripts/agent_graph.png
                                                 #   (그림은 mermaid.ink 서비스로 그리므로 인터넷 필요)
  그래프 2개
    · 시설 그래프 (diet/workflow.py)       프로필 → 어르신마다 개인화(Send) → 공통 최적화 → … → 대체찬 → 배식률 → 정리
    · 개인화 그래프 (diet/agents/graph.py)  7개 영역 × (규칙 → 근거 검색 → 영역 결론) → 종합 → 정제 → 3단계 6개 노드
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))


def main():
    from diet.agents import graph as G
    from diet.agents import manager as M
    if not G.available():
        raise SystemExit("langgraph 가 없습니다 → pip install \"langgraph>=1.0,<2\"")
    import importlib.metadata as md
    print("langgraph", md.version("langgraph"))
    from diet import workflow as WF
    for name, app in (("facility_graph", WF.build()), ("agent_graph", G.build())):
        mm = app.get_graph().draw_mermaid()
        (BACKEND / "scripts" / f"{name}.mmd").write_text(mm, encoding="utf-8")
        print(f"\n── {name} ({len(app.get_graph().nodes) - 2}개 노드) → scripts/{name}.mmd")
        if "--png" in sys.argv:
            try:
                (BACKEND / "scripts" / f"{name}.png").write_bytes(app.get_graph().draw_mermaid_png())
                print(f"   그림 → scripts/{name}.png")
            except Exception as e:
                print(f"   그림 실패 ({str(e)[:120]}) — .mmd 를 https://mermaid.live 에 붙여 넣으면 됩니다")
    if "--mermaid" in sys.argv or "--png" in sys.argv:
        return
    os.environ["RAG_BACKEND"] = "local"
    sys.argv = sys.argv[:1]
    from scripts.compare_agent_modes import SAMPLES
    from diet.agents.synthesis import finalize
    dump = lambda x: json.dumps(x, sort_keys=True, default=str, ensure_ascii=False)
    os.environ["DIET_LANGGRAPH"] = "0"
    t0 = time.time(); old = M.assess_residents(SAMPLES); t_old = time.time() - t0
    os.environ["DIET_LANGGRAPH"] = "1"
    t0 = time.time(); new = M.assess_residents(SAMPLES); t_new = time.time() - t0
    full = G.run(SAMPLES)
    ok = True
    for e in SAMPLES:
        s1 = dump(M.to_json({e: old[e]})) == dump(M.to_json({e: new[e]}))
        s3 = dump(finalize(old[e]["synth"], SAMPLES[e], None, old[e]["agents"])) == dump(full[e]["synth"])
        ok &= s1 and s3
        print(f"  {e}: 1단계 {'같음' if s1 else '다름'} · 3단계 {'같음' if s3 else '다름'}")
    print(f"\n{'정상' if ok else '확인 필요'} — 스레드 풀 {t_old:.2f}초 · LangGraph {t_new:.2f}초")


if __name__ == "__main__":
    main()
