# -*- coding: utf-8 -*-
"""⑦ 지식그래프(Neo4j Aura) 반영 — 매일 run 이 부른다 (run_daily.bat 은 --graph 로 실행).

    python -m mapping.run --graph                  # 하루치 판정 + 가격 + 그래프
    python -m mapping.run --price-only --graph     # 검수 반영 후 가격·그래프만
    python -m mapping.graph_export --dry-run       # 오늘 가격으로 반영할 내용만 확인 (Neo4j 안 씀)

[반영 내용] 기존 (:Recipe {id}) 노드는 MATCH 만 한다 (새로 만들지 않음 — 노드는 scripts/load_graph.py 가 만든다).

  (:Recipe)  += { price_per_kg            오늘 두 공급사 통틀어 최저 kg당 가격 (세금 포함, 원)
                  price_per_kg_28d        식단 최적화용 28일 중앙값
                  price_per_kg_hgreenfood 현대그린푸드 최저 kg당 가격,  price_item_hgreenfood  그 상품명
                  price_per_kg_sajo       사조푸디스트 최저 kg당 가격,  price_item_sajo        그 상품명
                  price_supplier          더 싼 공급사 (hgreenfood | sajo)
                  price_n_hgreenfood / price_n_sajo   오늘 판매 중인 승인 상품 수
                  price_date, price_status ('ok' | 'missing' | 'not_product') }
  (:Product {supplier, item_cd}) += {supplier_label, item_nm, spec, unit, pack_g, unit_price_tax, price_per_kg,
                                     price_date, on_sale}
  (:Recipe)-[:MAPPED_TO {score, status, method, selected, selected_in_supplier}]->(:Product)
     selected = 오늘 그 식재료 가격으로 뽑힌 상품,  selected_in_supplier = 공급사 안에서 최저가 상품
  승인이 취소된 관계와 어떤 식재료에도 이어지지 않은 Product 는 지운다.
  scripts/load_graph.py --wipe 로 그래프를 다시 적재했다면 `python -m mapping.run --price-only --graph` 를 한 번 실행한다.
"""
import argparse
import os
import sys
from datetime import date

from . import config as C

SUPPLIER_LABEL = {"hgreenfood": "현대그린푸드", "sajo": "사조푸디스트"}

Q_RECIPE = """
UNWIND $rows AS row
MATCH (r:Recipe {id: row.id})
SET r += row.props
RETURN count(r) AS n
"""
Q_PRODUCT = """
UNWIND $rows AS row
MERGE (p:Product {supplier: row.supplier, item_cd: row.item_cd})
SET p += row.props
"""
Q_EDGE = """
UNWIND $rows AS row
MATCH (r:Recipe {id: row.ingredient_id})
MATCH (p:Product {supplier: row.supplier, item_cd: row.item_cd})
MERGE (r)-[m:MAPPED_TO]->(p)
SET m += row.props
"""


def _kg(v):
    return None if v is None else round(float(v) * 1000)


def build(day: date, daily: list[dict], offers: list[dict], mapping_rows: list[dict], ings) -> dict:
    """그래프에 쓸 행 (Neo4j 없이도 만들 수 있게 순수 함수)."""
    by_ing = {r["ingredient_id"]: r for r in daily}
    recipes = []
    for ing in ings:
        r = by_ing.get(ing.ingredient_id) or {}
        status = "not_product" if ing.not_product else ("ok" if r.get("price_per_g") is not None else "missing")
        recipes.append({"id": ing.ingredient_id, "props": {
            "price_per_kg": _kg(r.get("price_per_g")),
            "price_per_kg_28d": _kg(r.get("price_per_g_28d")),
            "price_per_kg_hgreenfood": _kg(r.get("hgreenfood_min")),
            "price_item_hgreenfood": r.get("hgreenfood_item_nm"),
            "price_n_hgreenfood": int(r.get("hgreenfood_n") or 0),
            "price_per_kg_sajo": _kg(r.get("sajo_min")),
            "price_item_sajo": r.get("sajo_item_nm"),
            "price_n_sajo": int(r.get("sajo_n") or 0),
            "price_supplier": r.get("supplier"),
            "price_date": str(day), "price_status": status}})

    selected = {(r["ingredient_id"], r.get("supplier"), str(r.get("item_cd"))) for r in daily if r.get("item_cd")}
    sel_sup = set()
    for r in daily:
        for sup in C.SUPPLIERS:
            if r.get(f"{sup}_item_cd"):
                sel_sup.add((r["ingredient_id"], sup, str(r[f"{sup}_item_cd"])))
    today = {(o["supplier"], str(o["item_cd"])): o for o in offers}

    products, edges = {}, []
    for m in mapping_rows:
        key = (m["supplier"], str(m["item_cd"]))
        f = m.get("features") or {}
        o = today.get(key)
        products.setdefault(key, {"supplier": key[0], "item_cd": key[1], "props": {
            "supplier_label": SUPPLIER_LABEL.get(key[0], key[0]),
            "item_nm": (o or {}).get("item_nm") or f.get("item_nm"),
            "spec": (o or {}).get("spec") or f.get("spec"), "unit": (o or {}).get("unit") or f.get("unit"),
            "pack_g": (o or {}).get("pack_g") or f.get("pack_g"),
            "unit_price_tax": (o or {}).get("unit_price_tax"),
            "price_per_kg": _kg((o or {}).get("price_per_g") if o else f.get("price_per_g")),
            "price_date": str(day) if o else None, "on_sale": bool(o)}})
        k3 = (m["ingredient_id"], key[0], key[1])
        edges.append({"ingredient_id": m["ingredient_id"], "supplier": key[0], "item_cd": key[1], "props": {
            "score": float(m.get("score") or 0), "status": m["status"], "method": m.get("method"),
            "selected": k3 in selected, "selected_in_supplier": k3 in sel_sup}})
    return {"recipes": recipes, "products": list(products.values()), "edges": edges}


def summarize(g: dict) -> dict:
    rp = [r["props"] for r in g["recipes"]]
    return {"recipes": len(rp), "priced": sum(p["price_status"] == "ok" for p in rp),
            "hgreenfood_priced": sum(p["price_per_kg_hgreenfood"] is not None for p in rp),
            "sajo_priced": sum(p["price_per_kg_sajo"] is not None for p in rp),
            "products": len(g["products"]), "on_sale": sum(p["props"]["on_sale"] for p in g["products"]),
            "edges": len(g["edges"]), "selected": sum(e["props"]["selected"] for e in g["edges"])}


def write(g: dict, batch: int = 1000) -> dict:
    sys.path.insert(0, C.BACKEND)
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    load_dotenv(os.path.join(C.BACKEND, ".env"))
    uri, user, pw = os.getenv("NEO4J_URI", ""), os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")
    dbname = os.getenv("NEO4J_DATABASE", "neo4j")
    if not (uri and pw):
        raise RuntimeError("NEO4J_URI / NEO4J_PASSWORD 가 .env 에 없습니다.")
    from care.graph import driver_args                  # load_graph.py 와 같은 인증서 처리
    curi, extra = driver_args(uri)
    drv = GraphDatabase.driver(curi, auth=(user, pw), connection_timeout=60, **extra)
    matched = 0
    try:
        with drv.session(database=dbname) as ses:
            ses.run("CREATE CONSTRAINT product_key IF NOT EXISTS FOR (p:Product) REQUIRE (p.supplier, p.item_cd) IS UNIQUE").consume()
            for i in range(0, len(g["recipes"]), batch):
                matched += ses.run(Q_RECIPE, rows=g["recipes"][i:i + batch]).single()["n"]
            for i in range(0, len(g["products"]), batch):
                ses.run(Q_PRODUCT, rows=g["products"][i:i + batch]).consume()
            ses.run("MATCH (:Recipe)-[m:MAPPED_TO]->(:Product) SET m.keep = false").consume()
            for i in range(0, len(g["edges"]), batch):
                rows = [{**e, "props": {**e["props"], "keep": True}} for e in g["edges"][i:i + batch]]
                ses.run(Q_EDGE, rows=rows).consume()
            dropped = ses.run("MATCH (:Recipe)-[m:MAPPED_TO]->(:Product) WHERE m.keep = false DELETE m RETURN count(*) AS c").single()["c"]
            ses.run("MATCH ()-[m:MAPPED_TO]->() REMOVE m.keep").consume()
            orphan = ses.run("MATCH (p:Product) WHERE NOT EXISTS { (p)<-[:MAPPED_TO]-() } DETACH DELETE p RETURN count(*) AS c").single()["c"]
    finally:
        drv.close()
    return {**summarize(g), "recipe_matched": matched, "edges_dropped": dropped, "products_dropped": orphan,
            "written": True}


def export(day: date, daily, offers, mapping_rows, ings, dry_run: bool = False) -> dict:
    g = build(day, daily, offers, mapping_rows, ings)
    if dry_run:
        return {**summarize(g), "written": False}
    res = write(g)
    if res["recipe_matched"] < len(g["recipes"]):
        print(f"[mapping] ⚠ 그래프에 없는 식재료 {len(g['recipes']) - res['recipe_matched']}개 — "
              "scripts/load_graph.py 로 그래프를 새 레시피 DB 기준으로 적재했는지 확인")
    return res


def main(argv=None):
    from .run import run_day, today_kst
    ap = argparse.ArgumentParser(description="오늘 가격을 다시 계산해 그래프에 반영 (= run --price-only --graph)")
    ap.add_argument("--date")
    ap.add_argument("--source", choices=["supabase", "csv"], default="supabase")
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    day = date.fromisoformat(a.date) if a.date else today_kst()
    r = run_day(day, source=a.source, store_kind=a.store, price_only=True, graph=True, graph_dry_run=a.dry_run,
                use_llm=False)
    print(r.get("graph"))


if __name__ == "__main__":
    main()
