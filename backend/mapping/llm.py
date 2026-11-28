# -*- coding: utf-8 -*-
"""애매한 구간만 LLM 에 묻는다 (diet/llm_select.call_llm 재사용: .env 의 LLM_PROVIDER · OPENAI_API_KEY).

입력: 식재료 정보(이름들·식약처 식품명·대분류) + 상품 정보(이름·분류·규격) + 사람이 승인·거절한 사례.
답: {"results": [{"i": 0, "same": true, "reason": "...", "state_match": true, "processed_match": true}]}
LLM 이 같다고 해도 규칙 점수가 LLM_APPROVE_MIN 이상이고 확정 조건(분류·상태·가공·가격·부위)을 지킬 때만 자동 승인한다.
"""
import json

from . import config as C
from .judge import gates

SYSTEM = """너는 급식 식자재 구매 담당자다. 레시피 식재료와 공급사 상품이 '같은 식재료'인지 판정한다.
같은 식재료 = 그 상품을 사서 레시피 재료로 그대로 쓸 수 있고, g당 가격을 그 재료 가격으로 써도 되는 경우.
- 손질·썰기·냉동·포장 차이는 같다 (깐마늘 = 마늘, 냉동 다진양파 = 양파).
- 다른 품종·부위는 다르다 (청양고추 ≠ 홍고추, 목살 ≠ 삼겹살, 단호박 ≠ 애호박, 방울토마토 ≠ 토마토).
- 그 재료로 만든 가공품은 다르다 (고추장 ≠ 고추, 배추김치 ≠ 배추, 새우젓 ≠ 새우살, 양념·소스·반찬·간편식).
- 말린 것과 생것, 국간장과 진간장은 다르다.
반드시 JSON 만 답한다: {"results":[{"i":번호,"same":true|false,"reason":"한 문장","state_match":true|false,"processed_match":true|false}]}"""

LLM_RESOLVABLE = ("대표 이름이 아닌 같은 코드 이름으로 일치", "여러 식재료가 같은 이름", "간편식 표시", "품종 표시")


class LLMJudge:
    def __init__(self, examples: list[dict] | None = None, max_calls: int = C.LLM_MAX_CALLS, batch: int = 10):
        self.examples = (examples or [])[:12]
        self.max_calls, self.batch = max_calls, batch
        self.calls, self.label, self.ready = 0, None, False
        try:
            from diet import llm_select as LS
            st = LS.status()
            self.ready, self._call = bool(st.get("ready")), LS.call_llm
        except Exception as e:                                   # noqa: BLE001
            print(f"[mapping] LLM 끔: {e}")

    def _ask(self, items: list[dict]) -> list[dict]:
        payload = {"examples": self.examples, "pairs": items}
        res, self.label = self._call(payload, system=SYSTEM, max_tokens=1500)
        self.calls += 1
        return res.get("results") or []

    def review(self, rows: list[dict], prods_by_key: dict, ings_by_id: dict):
        if not self.ready:
            return
        lo, hi = C.LLM_BAND
        todo = [r for r in rows if r["status"] == "pending" and lo <= r["score"] < hi
                and all(m.startswith(LLM_RESOLVABLE) for m in _miss(r))]
        todo.sort(key=lambda r: (-r["_usage"], -r["score"]))
        n_calls = min(-(-len(todo) // self.batch), self.max_calls)
        print(f"[mapping] LLM 판정 {len(todo):,}쌍 → 약 {n_calls}회 호출", flush=True)
        for s in range(0, len(todo), self.batch):
            if self.calls >= self.max_calls:
                break
            chunk = todo[s:s + self.batch]
            items = []
            for i, r in enumerate(chunk):
                p, raw = prods_by_key[(r["supplier"], r["item_cd"])]
                ing = ings_by_id[r["ingredient_id"]]
                items.append({"i": i, "ingredient": {"name": ing.rep_name, "names": ing.names[:12],
                                                    "mfds": ing.mfds_name, "group": ing.food_group},
                              "product": {"name": p.item_nm, "category": " > ".join(
                                  x for x in (raw.get("lcls_nm"), raw.get("mcls_nm"), raw.get("dcls_nm")) if x),
                                  "spec": raw.get("spec"), "unit": raw.get("unit")}})
            if self.calls and self.calls % 20 == 0:
                print(f"[mapping]   LLM {self.calls}/{n_calls}회", flush=True)
            try:
                answers = {int(a.get("i", -1)): a for a in self._ask(items)}
            except Exception as e:                               # noqa: BLE001
                print(f"[mapping] LLM 호출 실패: {e}")
                break
            for i, r in enumerate(chunk):
                a = answers.get(i)
                if not a:
                    continue
                r["features"]["llm"] = {k: a.get(k) for k in ("same", "state_match", "processed_match")}
                r["reason"] = f"LLM: {a.get('reason', '')}"[:300]
                r["method"] = "llm"
                if a.get("same") and a.get("state_match", True) and a.get("processed_match", True) \
                        and r["score"] >= C.LLM_APPROVE_MIN:
                    r["status"] = "auto_approved"
                elif not a.get("same") and r["score"] < 0.6:
                    r["status"] = "auto_rejected"
                r["model_version"] = f"{r['model_version']}+{self.label}"


def _miss(r: dict) -> list[str]:
    return gates(r["features"])


def examples_from_reviews(df) -> list[dict]:
    """사람이 승인·거절한 사례 → 프롬프트 예시 (승인 6 + 거절 6)."""
    if df is None or df.empty:
        return []
    out = []
    for st, n in (("approved", 6), ("rejected", 6)):
        sub = df[df["status"] == st].tail(n)
        for r in sub.to_dict("records"):
            f = r.get("features") or {}
            if isinstance(f, str):
                f = json.loads(f or "{}")
            out.append({"ingredient": r.get("rep_name") or r["ingredient_id"], "product": f.get("item_nm"),
                        "same": st == "approved", "reason": r.get("reason")})
    return out
