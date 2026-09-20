"""Neo4j 식품·메뉴 DB에서 Care-Eat가 쓰는 부분만 스냅샷으로 뽑아낸다.

전체 DB는 578,462 노드 / 860,386 관계지만 Care-Eat가 실제로 참조하는 범위는
Food 859 + Recipe 415 + Meal_Category 6 + Disease 6 ≈ 1,865 노드,
관계 15,311개(0.3%)뿐이다. 그래서 운영 중 라이브 접속 대신 스냅샷을 쓴다.

사용법
    # 1) Neo4j Browser/Query에서 아래 네 쿼리를 한 번에 하나씩 실행해 JSON으로 내려받는다
    #    (신 Query UI는 세미콜론으로 여러 문장을 붙이면 실패한다)
    # 2) 내려받은 파일 네 개를 한 폴더에 두고
    python scripts/export_graph.py --raw <그 폴더> --out care/graph_data

내려받아야 하는 네 개
    foods.json      : Q_FOOD      (Food + Meal_Category)
    edges.json      : Q_EDGE      (Food -HAS_INGREDIENT-> Recipe)
    recipes.json    : Q_RECIPE    (Recipe + Category + Nutrition)
    disease.json    : Q_DISEASE   (Disease -[REC|FORB]-> Recipe)
"""

import argparse
import json
import os
import sys

Q_FOOD = """
MATCH (f:Food)
OPTIONAL MATCH (f)-[:CATEGORY_IS]->(m:Meal_Category)
RETURN f.id AS id, f.title AS title, m.name AS meal_cat
ORDER BY f.title
"""

Q_EDGE = """
MATCH (f:Food)-[rel:HAS_INGREDIENT]->(r:Recipe)
RETURN f.id AS food_id, f.title AS food,
       r.id AS recipe_id, r.title AS ingredient,
       rel.weight AS weight
"""

Q_RECIPE = """
MATCH (r:Recipe)
OPTIONAL MATCH (r)-[:BELONGS_TO]->(c:Category)
OPTIONAL MATCH (r)-[:CONTAINS]->(n:Nutrition)
RETURN r.id AS id, r.title AS title, c.name AS category,
       properties(n) AS nutrition
"""

Q_DISEASE = """
MATCH (d:Disease)-[rel:RECOMMENDED_INGREDIENT|FORBIDDEN_INGREDIENT]->(r:Recipe)
RETURN d.name AS disease, type(rel) AS direction, r.title AS ingredient,
       rel.standard_key AS nutrient, rel.source_terms AS terms,
       rel.paper_titles AS papers, rel.paper_dois AS dois
"""

KEEP = ["energy_kcal", "protein_g", "fat_g", "carbo_g", "fiber_g", "sugar_g",
        "sodium_mg", "potassium_mg", "calcium_mg", "iron_mg", "phosphorus_mg",
        "saturated_fat_g", "trans_fat_g", "cholesterol_mg", "vitD_ug",
        "vitC_mg", "vitA_rae_ug", "thiamin_mg", "riboflavin_mg", "niacin_mg",
        "beta_carotene_ug"]


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def build(raw_dir, out_dir):
    recipes = _load(os.path.join(raw_dir, "recipes.json"))
    foods = _load(os.path.join(raw_dir, "foods.json"))
    edges = _load(os.path.join(raw_dir, "edges.json"))
    disease = _load(os.path.join(raw_dir, "disease.json"))

    ing = {}
    for r in recipes:
        n = r.get("nutrition") or {}
        ing[r["id"]] = {
            "t": r.get("title"),
            "c": r.get("category"),
            "n": {k: round(float(n.get(k) or 0), 3) for k in KEEP},
        }

    # 요리 = (식재료, 분량 g) 목록. 분량을 곱해 1인분 영양량을 미리 계산해 둔다.
    fmap = {f["id"]: {"t": f["title"], "m": f.get("meal_cat"), "i": [], "miss": 0}
            for f in foods}
    for e in edges:
        v = fmap.get(e["food_id"])
        if v is None:
            continue
        w = e.get("weight")
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = None
        if w is None or w <= 0:
            v["miss"] += 1          # 분량을 모르는 재료 — 숨기지 않고 센다
        v["i"].append([e["recipe_id"], w])

    for v in fmap.values():
        v["i"].sort(key=lambda x: (-(x[1] or 0), x[0]))
        tot = {k: 0.0 for k in KEEP}
        gram = 0.0
        for rid, w in v["i"]:
            iv = ing.get(rid)
            if not iv or not w:
                continue
            gram += w
            for k in KEEP:
                tot[k] += (iv["n"].get(k) or 0) * w / 100.0
        v["g"] = round(gram, 1)                                   # 1인분 총중량
        v["n"] = {k: round(val, 2) for k, val in tot.items()}     # 1인분 영양량
        v["partial"] = v["miss"] > 0

    papers, pidx, ev = [], {}, []
    for r in disease:
        ps = []
        for t in (r.get("papers") or [])[:4]:
            if t not in pidx:
                pidx[t] = len(papers)
                papers.append(t)
            ps.append(pidx[t])
        ev.append({
            "d": r["disease"],
            "f": 1 if r["direction"] == "FORBIDDEN_INGREDIENT" else 0,
            "n": r["nutrient"],
            "i": r["ingredient"],
            "p": ps,
            "doi": (r.get("dois") or [])[:4],
        })

    os.makedirs(out_dir, exist_ok=True)
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    for name, obj in (("ingredients.json", ing), ("foods.json", fmap),
                      ("evidence.json", {"papers": papers, "ev": ev})):
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump(obj))
        print(f"  {name:<18} {os.path.getsize(path)/1024:8.1f} KB")
    print(f"완료: 요리 {len(fmap)} · 식재료 {len(ing)} · 근거 {len(ev)} · 논문 {len(papers)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", help="Neo4j에서 내려받은 JSON 네 개가 있는 폴더")
    ap.add_argument("--out", default="care/graph_data")
    ap.add_argument("--cypher", action="store_true", help="실행할 Cypher만 출력")
    a = ap.parse_args()

    if a.cypher or not a.raw:
        for name, q in (("foods.json", Q_FOOD), ("edges.json", Q_EDGE),
                        ("recipes.json", Q_RECIPE), ("disease.json", Q_DISEASE)):
            print(f"\n-- {name} ------------------------------")
            print(q.strip())
        if not a.raw:
            print("\n네 개를 내려받은 뒤 --raw <폴더> 로 다시 실행하세요.")
        return
    build(a.raw, a.out)


if __name__ == "__main__":
    sys.exit(main())
