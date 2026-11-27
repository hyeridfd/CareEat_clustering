# -*- coding: utf-8 -*-
"""식품 지식그래프 다시 적재 — 새 레시피 DB(recipes_v1.csv) 기준으로 Neo4j 를 처음부터 만든다.

    python scripts/load_graph.py --dry-run              # 그래프만 만들어 개수 확인 (Neo4j 안 씀)
    python scripts/load_graph.py --dry-run --snapshot   # + 앱 스냅샷 형식으로 저장 (scripts/graph_build/)
    python scripts/load_graph.py --wipe                 # Neo4j 비우고 적재 (.env 의 NEO4J_* 사용)
    python scripts/check_graph.py                       # 적재 뒤 확인

[그래프 구조] care/graph.py 가 읽는 형식 그대로 (돌봄 화면 코드 수정 없음)
  (:Food {id:"Food_<음식코드>", title, code, in_pool, method, mid})
      -[:CATEGORY_IS]->(:Meal_Category {name: 밥|국|주찬|부찬|김치|간식})
      -[:HAS_INGREDIENT {weight: 실사용량 g, nutri_weight: 영양 계산용 g, names: [레시피 원재료명]}]->
  (:Recipe {id:"Recipe_<식품코드>", title: 대표 원재료명, food_code, names: [같은 코드의 원재료명들]})
      -[:BELONGS_TO]->(:Category {name: 식약처 식품대분류명})
      -[:CONTAINS]->(:Nutrition {food_code, energy_kcal, protein_g, … (100 g 당), discard_pct})
  (:Disease {name})-[:RECOMMENDED_INGREDIENT|FORBIDDEN_INGREDIENT {standard_key, paper_titles, paper_dois}]->(:Recipe)

  · 식재료(Recipe)는 식품코드 단위 — 원재료명 7천여 개가 식품코드 1천여 개로 묶인다 (공급사 상품 매핑도 이 단위).
    식품코드가 없는 재료('DB 없음')는 원재료명 단위: id "Recipe_NAME:<원재료명>", 영양 노드 없음.
  · 같은 요리에 같은 식품코드가 두 번 나오면(소금 + 소금(절임용)) 중량을 더해 관계 하나로 만든다.
    절임용 재료는 영양 계산 중량 0 (diet/build_pool.py 와 같은 규칙), 물은 뺀다.
  · 끼니 구분은 식단 후보 풀(pool.json)에 있으면 그 구분, 없으면 레시피 DB '구분'.
  · 질환별 권장·제한 재료와 논문 근거는 지금 스냅샷(care/graph_data/evidence.json)에서 가져와
    재료 이름 → 식품코드로 이어 붙인다.
  · [다음 단계] 공급사 상품: (:Recipe)-[:MAPPED_TO {score, approved}]->(:Product {supplier, item_cd, …, price_per_g})
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

import pandas as pd  # noqa: E402

from diet import build_pool as BP  # noqa: E402

GRAPH_DATA = os.path.join(BACKEND, "care", "graph_data")
OUT_DIR = os.path.join(HERE, "graph_build")
BATCH = 2000

# care/graph.py NUT_FIELDS ← 식약처 영양 DB 열 (100 g 당)
NUT_COLS = {
    "energy_kcal": "에너지(kcal)", "protein_g": "단백질(g)", "fat_g": "지방(g)", "carbo_g": "탄수화물(g)",
    "fiber_g": "식이섬유(g)", "sugar_g": "당류(g)", "sodium_mg": "나트륨(mg)", "potassium_mg": "칼륨(mg)",
    "calcium_mg": "칼슘(mg)", "iron_mg": "철(mg)", "phosphorus_mg": "인(mg)", "saturated_fat_g": "포화지방산(g)",
    "trans_fat_g": "트랜스지방산(g)", "cholesterol_mg": "콜레스테롤(mg)", "vitD_ug": "비타민 D(μg)",
    "vitC_mg": "비타민 C(mg)", "vitA_rae_ug": "비타민 A(μg RAE)", "thiamin_mg": "티아민(mg)",
    "riboflavin_mg": "리보플라빈(mg)", "niacin_mg": "니아신(mg)", "beta_carotene_ug": "베타카로틴(μg)",
}
R = BP.R_COL

# 식품대분류가 없는 영양 DB(통합식품영양성분_PD: 가공식품 P·음식 D)는 식품코드 앞자리로 분류한다
#   P1NN = 식품공전 가공식품 대분류 번호 (예전 그래프의 분류와 대조: P112 장류, P113 조미식품 …)
P_CATS = {
    "01": "과자류·빵류 또는 떡류", "02": "빙과류", "03": "코코아가공품류 또는 초콜릿류", "04": "당류", "05": "잼류",
    "06": "두부류 또는 묵류", "07": "식용유지류", "08": "면류", "09": "음료류", "10": "특수영양식품",
    "11": "특수의료용도식품", "12": "장류", "13": "조미식품", "14": "절임류 또는 조림류", "15": "주류",
    "16": "농산가공식품류", "17": "식육가공품 및 포장육", "18": "알가공품류", "19": "유가공품류",
    "20": "수산가공식품류", "21": "동물성가공식품류", "22": "벌꿀 및 화분가공품류", "23": "즉석식품류", "24": "기타식품류",
}
#   DxNN = 음식 분류 번호 (예전 그래프와 대조: 03 면 및 만두류, 05 국 및 탕류, 15 김치류 …)
D_CATS = {
    "01": "밥류", "02": "빵 및 과자류", "03": "면 및 만두류", "04": "죽 및 스프류", "05": "국 및 탕류",
    "06": "찌개 및 전골류", "07": "찜류", "08": "구이류", "09": "전·적 및 부침류", "10": "볶음류", "11": "조림류",
    "12": "튀김류", "13": "나물·숙채류", "14": "생채·무침류", "15": "김치류", "16": "젓갈류", "17": "장아찌·절임류",
}
BROTH = ("육수", "국물", "스톡", "다시", "쌀뜨물")


def category_of(code, db_cat, name):
    if isinstance(db_cat, str) and db_cat.strip() and db_cat != "nan":
        return db_cat.strip()
    if code and code[:1] == "P" and code[2:4] in P_CATS:
        return P_CATS[code[2:4]]
    if code and code[:1] == "D":
        return D_CATS.get(code[2:4], "조리식품(기타)")
    if any(k in name for k in BROTH):
        return "육수·국물 (식품코드 없음)"
    return "식품코드 없음"


# ══════════════════════════════════════════════════════════════════
# ① 원자료 → 그래프 (메모리)
# ══════════════════════════════════════════════════════════════════
def load_nutrients(paths):
    frames = []
    want = {"식품코드", "식품명", "식품대분류명", "폐기율(%)", *NUT_COLS.values()}
    for p in paths:
        d = BP.read_csv_any(p, dtype={"식품코드": str}, usecols=lambda c: c in want, low_memory=False)
        frames.append(d)
    db = pd.concat(frames, ignore_index=True)
    db["식품코드"] = db["식품코드"].astype(str).str.strip()
    db = db.drop_duplicates("식품코드", keep="first").set_index("식품코드")
    for c in [*NUT_COLS.values(), "폐기율(%)"]:
        if c not in db.columns:
            db[c] = 0.0
        db[c] = pd.to_numeric(db[c], errors="coerce").fillna(0.0)
    return db


def pool_categories():
    path = os.path.join(BACKEND, "diet", "data", "pool.json")
    try:
        pool = json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {m["menu_name"]: cat for cat, ms in pool.items() for m in ms}


def build_graph():
    paths = BP.default_paths()
    print(f"레시피: {os.path.basename(paths['recipes'])} · 영양 DB: {', '.join(os.path.basename(p) for p in paths['nutrients'])}")
    r = BP.read_csv_any(paths["recipes"], dtype={R["fcode"]: str, R["code"]: str})
    r[R["fcode"]] = r[R["fcode"]].astype(str).str.strip().replace(BP.CODE_ALIAS)
    r[R["ing"]] = r[R["ing"]].astype(str).str.strip()
    for c in (R["w_use"], R["w_nut"]):
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(0.0)
    r = r[~r[R["ing"]].isin(BP.WATER)]
    db = load_nutrients(paths["nutrients"])
    in_pool = pool_categories()

    # 식재료 노드 id: 식품코드(영양 DB 에 있으면) · 없으면 원재료명
    def ing_id(code, name):
        if code in BP.NO_DB or code not in db.index:
            return f"Recipe_NAME:{name}"
        return f"Recipe_{code}"

    r["rid"] = [ing_id(c, n) for c, n in zip(r[R["fcode"]], r[R["ing"]])]
    names = r.groupby("rid")[R["ing"]].agg(lambda s: Counter(s).most_common())

    recipes = {}
    for rid, cnt in names.items():
        code = rid[len("Recipe_"):] if not rid.startswith("Recipe_NAME:") else None
        row = db.loc[code] if code else None
        recipes[rid] = {
            "id": rid, "title": cnt[0][0], "food_code": code,
            "names": [n for n, _ in cnt][:30], "db_name": (str(row["식품명"]) if row is not None else None),
            "category": category_of(code, (row["식품대분류명"] if row is not None else None), cnt[0][0]),
            "nutrition": ({k: round(float(row[c]), 4) for k, c in NUT_COLS.items()} | {"discard_pct": float(row["폐기율(%)"])}
                          if row is not None else None),
        }

    foods, edges = {}, []
    for code, g in r.groupby(R["code"], sort=False):
        first = g.iloc[0]
        name = str(first[R["name"]])
        fid = f"Food_{code}"
        foods[fid] = {"id": fid, "code": str(code), "title": name,
                      "meal_cat": in_pool.get(name, str(first[R["cat"]])), "in_pool": name in in_pool,
                      "method": str(first[R["method"]]), "mid": str(first[R["mid"]])}
        agg = defaultdict(lambda: {"weight": 0.0, "nutri_weight": 0.0, "names": []})
        for ing, rid, wu, wn in zip(g[R["ing"]], g["rid"], g[R["w_use"]], g[R["w_nut"]]):
            e = agg[rid]
            e["weight"] += float(wu)
            e["nutri_weight"] += 0.0 if "절임용" in ing else float(wn)
            if ing not in e["names"]:
                e["names"].append(ing)
        for rid, e in agg.items():
            edges.append({"food": fid, "recipe": rid, "weight": round(e["weight"], 2),
                          "nutri_weight": round(e["nutri_weight"], 2), "names": e["names"]})

    # 질환별 근거 — 재료 이름 → 식재료 노드 (그 이름이 가장 많이 쓰인 식품코드)
    ev = json.load(open(os.path.join(GRAPH_DATA, "evidence.json"), encoding="utf-8"))
    by_name = r.groupby(R["ing"])["rid"].agg(lambda s: s.value_counts().index[0]).to_dict()
    disease, lost = [], Counter()
    for e in ev["ev"]:
        rid = by_name.get(e["i"])
        if rid is None:
            lost[e["i"]] += 1
            continue
        disease.append({"disease": e["d"], "rel": "FORBIDDEN_INGREDIENT" if e["f"] else "RECOMMENDED_INGREDIENT",
                        "recipe": rid, "ingredient": e["i"], "standard_key": e.get("n"),
                        "paper_titles": [ev["papers"][k] for k in e.get("p") or []][:4],
                        "paper_dois": (e.get("doi") or [])[:4]})
    return {"foods": foods, "recipes": recipes, "edges": edges, "disease": disease, "lost": lost}


def summary(G):
    f, rc = G["foods"], G["recipes"]
    print("\n[그래프]")
    print(f"  요리(Food)          {len(f):,}  (식단 후보 풀 {sum(v['in_pool'] for v in f.values()):,})")
    print(f"  끼니 구분           {dict(Counter(v['meal_cat'] for v in f.values()).most_common())}")
    print(f"  식재료(Recipe)      {len(rc):,}  (식품코드 {sum(1 for v in rc.values() if v['food_code']):,} · "
          f"코드 없음 {sum(1 for v in rc.values() if not v['food_code']):,})")
    print(f"  요리-재료 관계      {len(G['edges']):,}")
    print(f"  질환 근거 관계      {len(G['disease']):,}  (질환 {len({d['disease'] for d in G['disease']})} · "
          f"논문 {len({t for d in G['disease'] for t in d['paper_titles']}):,})")
    if G["lost"]:
        print(f"  ⚠ 재료를 못 찾은 근거 {sum(G['lost'].values())}건: {', '.join(list(G['lost'])[:10])}")
    nodes = len(f) + 2 * len(rc) + 10 + len({v['category'] for v in rc.values()})
    rels = len(G["edges"]) + len(f) + 2 * len(rc) + len(G["disease"])
    print(f"  노드 약 {nodes:,} · 관계 약 {rels:,}  (Aura Free 한도 노드 200,000 · 관계 400,000)")


# ══════════════════════════════════════════════════════════════════
# ② 앱 스냅샷 형식 (care/graph_data 와 같은 JSON) — Neo4j 가 없을 때 쓰는 폴백
# ══════════════════════════════════════════════════════════════════
def write_snapshot(G, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    ing = {rid: {"t": v["title"], "c": v["category"], "n": {k: round(float((v["nutrition"] or {}).get(k, 0)), 3)
                                                            for k in NUT_COLS}}
           for rid, v in G["recipes"].items()}
    foods = {fid: {"t": v["title"], "m": v["meal_cat"], "i": []} for fid, v in G["foods"].items()}
    for e in G["edges"]:
        foods[e["food"]]["i"].append([e["recipe"], e["weight"], e["nutri_weight"]])
    # 요리별 1인분 중량·영양 — care/graph.py _fetch_live() 와 같은 계산 (Neo4j 에서 읽을 때와 같은 값)
    from care.graph import NA_MISSING
    broth = {rid for rid, v in ing.items() if "육수" in (v["t"] or "") or "스톡" in (v["t"] or "")}
    for v in foods.values():
        v["i"].sort(key=lambda x: (-x[1], x[0]))
        tot, gram, bg, miss = {k: 0.0 for k in NUT_COLS}, 0.0, 0.0, []
        for rid, w, nw in v["i"]:
            iv = ing.get(rid)
            if not iv:
                continue
            gram += w
            bg += w if rid in broth else 0.0
            if nw <= 0:
                continue
            if (iv["t"] or "") in NA_MISSING:
                miss.append(iv["t"])
            for k in NUT_COLS:
                tot[k] += (iv["n"].get(k) or 0) * nw / 100.0
        v["g"], v["broth_g"] = round(gram, 1), round(bg, 1)
        v["n"] = {k: round(x, 2) for k, x in tot.items()}
        if miss:
            v["na_missing"] = sorted(set(miss))
    papers, pidx, ev = [], {}, []
    for d in G["disease"]:
        ps = []
        for t in d["paper_titles"]:
            if t not in pidx:
                pidx[t] = len(papers)
                papers.append(t)
            ps.append(pidx[t])
        ev.append({"d": d["disease"], "f": int(d["rel"] == "FORBIDDEN_INGREDIENT"), "n": d["standard_key"],
                   "i": d["ingredient"], "p": ps, "doi": d["paper_dois"]})
    for name, obj in (("ingredients.json", ing), ("foods.json", foods), ("evidence.json", {"papers": papers, "ev": ev})):
        json.dump(obj, open(os.path.join(out_dir, name), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\n스냅샷 저장: {out_dir}  (앱에 쓰려면 care/graph_data 의 같은 이름 파일과 바꾸면 됩니다)")


# ══════════════════════════════════════════════════════════════════
# ③ Neo4j 적재
# ══════════════════════════════════════════════════════════════════
CONSTRAINTS = [
    "CREATE CONSTRAINT food_id IF NOT EXISTS FOR (n:Food) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT recipe_id IF NOT EXISTS FOR (n:Recipe) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT nutrition_id IF NOT EXISTS FOR (n:Nutrition) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT mealcat_name IF NOT EXISTS FOR (n:Meal_Category) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (n:Category) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT disease_name IF NOT EXISTS FOR (n:Disease) REQUIRE n.name IS UNIQUE",
    "CREATE INDEX recipe_title IF NOT EXISTS FOR (n:Recipe) ON (n.title)",
    "CREATE INDEX food_title IF NOT EXISTS FOR (n:Food) ON (n.title)",
]
LABELS = ["Food", "Recipe", "Nutrition", "Meal_Category", "Category", "Disease"]

Q_RECIPE = """
UNWIND $rows AS row
MERGE (r:Recipe {id: row.id})
SET r.title = row.title, r.food_code = row.food_code, r.names = row.names, r.db_name = row.db_name
MERGE (c:Category {name: row.category})
MERGE (r)-[:BELONGS_TO]->(c)
WITH r, row WHERE row.nutrition IS NOT NULL
MERGE (n:Nutrition {id: 'Nutrition_' + row.food_code})
SET n += row.nutrition, n.food_code = row.food_code
MERGE (r)-[:CONTAINS]->(n)
"""
Q_FOOD = """
UNWIND $rows AS row
MERGE (f:Food {id: row.id})
SET f.title = row.title, f.code = row.code, f.in_pool = row.in_pool, f.method = row.method, f.mid = row.mid
MERGE (m:Meal_Category {name: row.meal_cat})
MERGE (f)-[:CATEGORY_IS]->(m)
"""
Q_EDGE = """
UNWIND $rows AS row
MATCH (f:Food {id: row.food}), (r:Recipe {id: row.recipe})
MERGE (f)-[h:HAS_INGREDIENT]->(r)
SET h.weight = row.weight, h.nutri_weight = row.nutri_weight, h.names = row.names
"""
Q_DISEASE = """
UNWIND $rows AS row
MERGE (d:Disease {name: row.disease})
WITH d, row
MATCH (r:Recipe {id: row.recipe})
CREATE (d)-[e:%s]->(r)
SET e.standard_key = row.standard_key, e.paper_titles = row.paper_titles, e.paper_dois = row.paper_dois
"""


def upload(G, wipe=False):
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    load_dotenv(os.path.join(BACKEND, ".env"))
    uri, user, pw = os.getenv("NEO4J_URI", ""), os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")
    dbname = os.getenv("NEO4J_DATABASE", "neo4j")
    if not (uri and pw):
        sys.exit("NEO4J_URI / NEO4J_PASSWORD 가 .env 에 없습니다.")
    print(f"\n[Neo4j] {uri} (DB {dbname}) 에 적재")
    from care.graph import driver_args          # 인증서를 certifi 목록으로 검증 (Windows 루트 인증서 누락 대비)
    curi, extra = driver_args(uri)
    drv = GraphDatabase.driver(curi, auth=(user, pw), connection_timeout=60, **extra)
    drv.verify_connectivity()
    try:
        with drv.session(database=dbname) as ses:
            if wipe:
                for lab in LABELS:
                    n = 0
                    while True:
                        c = ses.run(f"MATCH (n:{lab}) WITH n LIMIT 5000 DETACH DELETE n RETURN count(*) AS c").single()["c"]
                        n += c
                        if not c:
                            break
                    print(f"  비움 {lab}: {n:,}")
            for q in CONSTRAINTS:
                ses.run(q)

            def push(query, rows, label):
                t = time.time()
                for i in range(0, len(rows), BATCH):
                    ses.run(query, rows=rows[i:i + BATCH]).consume()
                    print(f"\r  {label} {min(i + BATCH, len(rows)):,}/{len(rows):,}", end="", flush=True)
                print(f"  ({time.time() - t:.0f}초)")

            push(Q_RECIPE, list(G["recipes"].values()), "식재료")
            push(Q_FOOD, list(G["foods"].values()), "요리")
            push(Q_EDGE, G["edges"], "요리-재료")
            if not wipe:     # 다시 적재할 때 근거 관계가 두 번 생기지 않게
                ses.run("MATCH (:Disease)-[e:RECOMMENDED_INGREDIENT|FORBIDDEN_INGREDIENT]->(:Recipe) DELETE e").consume()
            for rel in ("RECOMMENDED_INGREDIENT", "FORBIDDEN_INGREDIENT"):
                push(Q_DISEASE % rel, [d for d in G["disease"] if d["rel"] == rel], f"질환 근거 {rel}")
            cnt = {lab: ses.run(f"MATCH (n:{lab}) RETURN count(n) AS c").single()["c"] for lab in LABELS}
            rel = ses.run("MATCH ()-[e]->() RETURN count(e) AS c").single()["c"]
            print(f"  완료 — 노드 {cnt} · 관계 {rel:,}")
    finally:
        drv.close()


def main():
    ap = argparse.ArgumentParser(description="식품 지식그래프 적재 (recipes_v1.csv × 식약처 영양 DB × 질환 근거)")
    ap.add_argument("--dry-run", action="store_true", help="Neo4j 에 쓰지 않고 그래프만 만들어 확인")
    ap.add_argument("--snapshot", action="store_true", help=f"앱 스냅샷 형식으로도 저장 ({OUT_DIR})")
    ap.add_argument("--wipe", action="store_true", help="적재 전에 그래프 노드(Food·Recipe·Nutrition·…)를 모두 지움")
    a = ap.parse_args()
    t = time.time()
    G = build_graph()
    summary(G)
    if a.snapshot:
        write_snapshot(G, OUT_DIR)
    if not a.dry_run:
        upload(G, wipe=a.wipe)
    print(f"\n{time.time() - t:.0f}초")


if __name__ == "__main__":
    main()
