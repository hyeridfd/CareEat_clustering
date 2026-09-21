# -*- coding: utf-8 -*-
"""식품·메뉴 그래프 연결 진단 — Aura에 붙었는지, 값이 맞는지 한 번에 확인한다.

    python scripts/check_graph.py            # 연결 확인 + 표본 검증
    python scripts/check_graph.py --menu 고등어조림
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from care import graph as G   # noqa: E402

OK, NO = "  OK  ", " 실패 "


def step1():
    print("\n[1] 설정")
    uri = os.getenv("NEO4J_URI", "")
    pw = os.getenv("NEO4J_PASSWORD", "")
    print(f"   NEO4J_URI       {uri or '(비어 있음)'}")
    print(f"   NEO4J_USER      {os.getenv('NEO4J_USER', 'neo4j')}")
    print(f"   NEO4J_PASSWORD  {'설정됨 (' + str(len(pw)) + '자)' if pw else '(비어 있음)'}")
    print(f"   NEO4J_DATABASE  {os.getenv('NEO4J_DATABASE', 'neo4j')}")
    print(f"   캐시 TTL        {G.CACHE_TTL}초")
    if not G.neo4j_configured():
        print("   → 설정이 없어 스냅샷으로 동작합니다. .env를 확인하세요.")
        return False
    try:
        import neo4j                                  # noqa: F401
        print(f"{OK} neo4j 드라이버 설치됨")
    except ImportError:
        print(f"{NO} neo4j 드라이버 없음 → pip install neo4j")
        return False
    return True


def step2():
    print("\n[2] 적재")
    G.reload(force=True)
    s = G.stats()
    src = s["source"]
    print(f"   출처            {src}" + ("  ← Aura 라이브" if src == "neo4j" else "  ← 스냅샷 폴백"))
    if s.get("note"):
        print(f"   알림            {s['note']}")
    print(f"   요리            {s['foods']}")
    print(f"   식재료          {s['ingredients']}")
    print(f"   근거            {s['evidence']}  (논문 {s['papers']})")
    print(f"   질환            {' · '.join(s['diseases'])}")
    print(f"   끼니 구분       {s['meal_categories']}")
    return src == "neo4j"


def step3(menu):
    print(f"\n[3] 표본 검증 — {menu}")
    m = G.menu_nutrition(menu)
    if not m:
        print(f"{NO} 식품 DB에 '{menu}' 이 없습니다")
        return
    n = m["nutrition"]
    print(f"   1인분 {m['serving_g']}g (국물 {m['broth_g']}g) · {n['energy_kcal']}kcal · "
          f"단백질 {n['protein_g']}g · 나트륨 {n['sodium_mg']}mg · 칼슘 {n['calcium_mg']}mg")
    if m.get("sodium_underestimated"):
        print(f"   ※ 나트륨 과소 추정 — {', '.join(m['sodium_underestimated'])} 자료 없음")
    print("   재료 (제공g / 가식부g)")
    for i in m["ingredients"][:8]:
        mark = "  ← 가식부 보정" if i["edible_g"] != i["g"] else ""
        print(f"      {i['name']:<18} {i['g']:>6.1f} / {i['edible_g']:>6.1f}{mark}")


def step4():
    print("\n[4] 안전장치")

    def fmt(rows, key):
        return " · ".join("{} {:.0f}mg".format(r["title"], r[key]) for r in rows)

    k = G.nutrient_sources("k", disease="고혈압", limit=50)
    salt = [r for r in k if r["ingredient"] in ("소금", "굵은소금", "맛소금")]
    top = k[0]["ingredient"] if k else "–"
    print(f"   {OK if not salt else NO} 고혈압 칼륨 급원에 소금 없음 (1위 {top})")

    pro = G.food_candidates("protein", meal_cat="주찬", limit=3)
    over = [r for r in pro if r["sodium_mg"] > G.MAX_SODIUM["주찬"] * 1.5]
    print(f"   {OK if not over else NO} 단백질 주찬 나트륨 상한 적용")
    print(f"        {fmt(pro, 'sodium_mg')}")

    low = G.low_salt_candidates("국", limit=3)
    bad = [r for r in low if r.get("sodium_underestimated")]
    print(f"   {OK if not bad else NO} 저염 후보에서 나트륨 결측 요리 제외")
    print(f"        {fmt(low, 'sodium_mg')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", default="고등어조림")
    a = ap.parse_args()

    print("=" * 62)
    print(" Care-Eat 식품·메뉴 그래프 진단")
    print("=" * 62)
    configured = step1()
    live = step2()
    step3(a.menu)
    step4()
    print("\n" + "=" * 62)
    if live:
        print(" Aura 라이브 연결 정상. 데이터가 바뀌면 TTL 후 자동 반영됩니다.")
    elif configured:
        print(" 설정은 있으나 Aura를 읽지 못했습니다. URI·비밀번호·인스턴스 상태를 확인하세요.")
        print(" (Aura Free는 3일 미사용 시 일시정지됩니다. 콘솔에서 Resume 하세요.)")
    else:
        print(" 스냅샷으로 동작 중입니다. .env에 NEO4J_* 를 넣으면 라이브로 전환됩니다.")
    print("=" * 62)


if __name__ == "__main__":
    main()
