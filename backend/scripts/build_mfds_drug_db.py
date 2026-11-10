# -*- coding: utf-8 -*-
"""식약처 e약은요(의약품개요정보) 수집본 → 식단 설계용 약물-식품 DB + 근거 문서

    python -m scripts.build_mfds_drug_db "C:\\...\\outputs\\mfds_interactions.jsonl"

  입력: mfds_interactions.py 가 만든 JSONL (한 줄 = 제품 1개, text 에 문항5 상호작용, metadata 에 문항1~6)
  출력:
    diet/data/mfds_easy_drugs.json      제품별 {이름, 정규화 이름, 음식 관련 문장(분류), 복용 시점} — 약물 에이전트가 이름으로 찾음
    care/knowledge/docs/MFDS_EASY.md    음식 관련 문장이 있는 제품만 '## e약은요 <제품명>' 조항으로 — 근거 검색(RAG)용
  적재: python scripts/ingest_guidelines.py --only MFDS_EASY

  분류 원칙 (보수적)
    · 문항5(상호작용)를 문장 단위로 나눠 '음식'에 해당하는 말이 있는 문장만 고른다.
    · 약 이름 목록 안의 단어(예: 콜레스티라민의 '티라민', 약 성분으로서의 '카페인')는 음식으로 보지 않는다.
    · 식단에서 실제로 빼는 것은 티라민 식품(limit)만. 자몽·과일주스·우유·차는 '복용 전후 간격' 안내(timing),
      알코올·카페인·설사 중 식사는 돌봄 안내(note). 자동 판단 전 약사 확인이 전제다.
    · e약은요는 일반의약품 중심이다 — 처방약은 diet/data/drug_food_rules.json(수기 규칙)이 맡는다.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
OUT_JSON = BACKEND / "diet" / "data" / "mfds_easy_drugs.json"
OUT_DOC = BACKEND / "care" / "knowledge" / "docs" / "MFDS_EASY.md"

# (분류, 정규식, 조치, 식단에서 볼 식재료)
CATS = [
    # [2026-11-10] e약은요 문장은 '과일주스와 함께 복용하지 말 것'(복용 방법) → 식단 제외가 아니라 복용 간격 안내
    ("자몽·과일주스", r"자몽|과일\s?주스|오렌지\s?주스|사과\s?주스", "timing", []),
    ("티라민 식품", r"(?<![스])티라민", "limit", ["숙성치즈", "청국장", "젓갈", "액젓"]),
    ("우유·유제품", r"우유|유제품|요구르트", "timing", ["우유", "요구르트", "치즈"]),
    ("차(탄닌)", r"녹차|홍차|탄닌", "timing", ["녹차", "홍차"]),
    ("카페인 음료", r"커피|콜라|에너지\s?음료|카페인\s?(?:함유|음료)|카페인,\s?초콜", "note", []),
    ("알코올", r"알코올|음주|(?<![가-힣])술(?![가-힣])", "note", []),
    ("식사 주의", r"음식|식품|식사|생야채|초콜", "note", []),
]
TIMING = ["식사와 관계없이", "식후", "식전", "식간", "공복", "취침"]


def norm(name: str) -> str:
    """약물 에이전트와 같은 정규화 (diet/agents/medication.norm)"""
    sys.path.insert(0, str(BACKEND))
    from diet.agents.medication import norm as _n
    return _n(name)


def ingredients(name: str) -> list[str]:
    m = re.findall(r"\(([^()]*)\)", name or "")
    out = []
    for x in m:
        if "수출명" in x:
            continue
        out += [s.strip() for s in re.split(r"[,·/]", x) if 1 < len(s.strip()) < 40]
    return out


def timing_of(use: str) -> list[str]:
    """사용법(문항2) → 복용 시점. '공복시를 피하여'처럼 부정이면 공복이 아니라 식후로 본다"""
    u = re.sub(r"\s+", " ", use or "")
    neg = re.search(r"공복\s*(시|때)?\s*(를|을|에|는)?\s*(피|복용하지|삼가)", u)
    if neg:
        u = u.replace(neg.group(0), " 식후 ")
    return [k for k in TIMING if k in u]


def sentences(t: str) -> list[str]:
    t = re.sub(r"\s+", " ", t or "")
    return [s.strip() for s in re.split(r"(?<=[.다])\s+|(?<=시오\.)", t) if len(s.strip()) > 4]


def food_flags(q5: str) -> list[dict]:
    out, seen = [], set()
    for s in sentences(q5):
        for cat, pat, act, ings in CATS:
            if re.search(pat, s):
                # 긴 약 이름 나열 문장 속 카페인 등은 제외 (쉼표 8개 이상 + 음식 말이 '카페인'뿐)
                if cat == "카페인 음료" and s.count(",") >= 8 and not re.search(r"커피|콜라|음료", s):
                    continue
                key = (cat, s[:80])
                if key not in seen:
                    seen.add(key)
                    out.append({"cat": cat, "action": act, "ingredients": ings, "sentence": s[:300]})
                break                                   # 한 문장은 가장 강한 분류 하나로
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit("사용법: python -m scripts.build_mfds_drug_db <mfds_interactions.jsonl>")
    src = Path(sys.argv[1])
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    drugs, cats, n_food = [], Counter(), 0
    for r in rows:
        md = r.get("metadata") or {}
        oq = md.get("other_questions") or {}
        q5 = (r.get("text") or "").split("상호작용(문항5):", 1)[-1].strip()
        flags = food_flags(q5)
        use = oq.get("useMethodQesitm") or ""
        timing = timing_of(use)
        for f in flags:
            cats[f["cat"]] += 1
        n_food += bool(flags)
        drugs.append({"seq": md.get("itemSeq"), "name": md.get("itemName"), "key": norm(md.get("itemName")),
                      "entp": md.get("entpName"), "ingredients": ingredients(md.get("itemName")),
                      "efficacy": (oq.get("efcyQesitm") or "")[:120], "timing": timing, "use": use[:200],
                      "food": flags, "updated": md.get("updateDe")})
    meta = {"_설명": ["식약처 e약은요(의약품개요정보, data.go.kr 15075057) 수집본에서 만든 약물-식품 DB.",
                     "food: 문항5(상호작용) 중 음식 관련 문장과 분류 · action: avoid(식재료 제외) / limit(많이 든 반찬 제외) / timing(복용 전후 간격) / note(돌봄 안내)",
                     "일반의약품 중심 — 처방약은 drug_food_rules.json. 현장 적용 전 약사 확인 전제."],
            "source": "https://www.data.go.kr/data/15075057/openapi.do", "built_from": src.name,
            "n_products": len(drugs), "n_with_food": n_food, "by_category": dict(cats)}
    OUT_JSON.write_text(json.dumps({**meta, "drugs": drugs}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    lines = ["<!-- 출처: 식품의약품안전처 의약품개요정보(e약은요) Open API (공공데이터포털 15075057).",
             "     문항5(상호작용) 중 음식·음료 관련 문장과 문항2(사용법)의 복용 시점을 제품별로 옮겼다 (원문 문장 그대로).",
             "     일반의약품 중심이며 처방약은 포함되지 않는다. 생성: scripts/build_mfds_drug_db.py -->", ""]
    n_doc = 0
    for d in sorted(drugs, key=lambda x: x["name"] or ""):
        # 근거 문서에는 식단과 관련된 제품만 (알코올만 있는 제품은 돌봄 안내용으로 JSON 에만 둔다)
        if not any(f["cat"] != "알코올" for f in d["food"]):
            continue
        n_doc += 1
        lines.append(f"## e약은요 {d['name']}")
        lines.append("")
        head = f"{d['name']} ({d['entp']})" + (f" — {d['efficacy']}" if d["efficacy"] else "")
        lines.append(head + (f" 복용 시점: {', '.join(d['timing'])}." if d["timing"] else ""))
        lines.append("")
        for f in d["food"]:
            lines.append(f"- [{f['cat']}] {f['sentence']}")
        lines.append("")
    OUT_DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"제품 {len(drugs)}개 · 음식 관련 {n_food}개 → {OUT_JSON.name} / 근거 문서 조항 {n_doc}개 → {OUT_DOC.name}")
    print("분류별 문장 수:", dict(cats))


if __name__ == "__main__":
    main()
