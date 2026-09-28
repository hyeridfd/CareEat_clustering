# -*- coding: utf-8 -*-
"""graph.py 에 Neo4j Aura 라이브 연결 + 캐시 계층을 붙인다."""
import io, sys

p = 'care/graph.py'
s = io.open(p, encoding='utf-8').read()
assert 'NEO4J_URI' not in s, '이미 적용됨'

# ── 1) 헤더에 자료 출처 설명 ────────────────────────────────────
old_head = """전체 DB는 578,462 노드 / 860,386 관계지만 Care-Eat가 쓰는 부분은
약 1,865 노드 / 15,311 관계(0.3%)뿐이라 라이브 접속 대신 스냅샷을 쓴다.
스냅샷 갱신은 scripts/export_graph.py 참고."""
new_head = """자료는 Neo4j Aura에서 직접 읽는다 (식품·메뉴 DB는 주 단위로 갱신된다).
다만 개선안 하나에 집계 쿼리가 10번 넘게 돌고 Aura는 쉬었다 깨어나므로,
**읽어서 메모리에 얹어 두고 쓴다**:

    Aura 연결됨  →  서브그래프(약 1,865 노드)를 한 번에 읽어 캐시 (TTL 6시간)
    Aura 안 됨   →  care/graph_data/*.json 스냅샷으로 폴백 (앱은 계속 돈다)

강제 갱신은 reload(force=True) 또는 GET /care/facility/graph-status?refresh=true.
스냅샷 파일 자체의 갱신은 scripts/export_graph.py 참고."""
assert old_head in s
s = s.replace(old_head, new_head)

# ── 2) 연결 설정 + 적재 쿼리 ───────────────────────────────────
anchor = 'DATA_DIR = os.path.join(os.path.dirname(__file__), "graph_data")'
assert anchor in s
s = s.replace(anchor, anchor + '''

# ── Neo4j Aura 연결 ────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "")            # neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
CACHE_TTL = int(os.getenv("GRAPH_TTL", "21600"))   # 6시간
NEO4J_TIMEOUT = float(os.getenv("NEO4J_TIMEOUT", "45"))

Q_FOOD = """
MATCH (f:Food)
OPTIONAL MATCH (f)-[:CATEGORY_IS]->(m:Meal_Category)
RETURN f.id AS id, f.title AS title, m.name AS meal_cat
"""
Q_EDGE = """
MATCH (f:Food)-[rel:HAS_INGREDIENT]->(r:Recipe)
RETURN f.id AS food_id, r.id AS recipe_id,
       rel.weight AS weight, rel.nutri_weight AS nutri_weight
"""
Q_RECIPE = """
MATCH (r:Recipe)
OPTIONAL MATCH (r)-[:BELONGS_TO]->(c:Category)
OPTIONAL MATCH (r)-[:CONTAINS]->(n:Nutrition)
RETURN r.id AS id, r.title AS title, c.name AS category, properties(n) AS nutrition
"""
Q_DISEASE = """
MATCH (d:Disease)-[rel:RECOMMENDED_INGREDIENT|FORBIDDEN_INGREDIENT]->(r:Recipe)
RETURN d.name AS disease, type(rel) AS direction, r.title AS ingredient,
       rel.standard_key AS nutrient, rel.paper_titles AS papers, rel.paper_dois AS dois
"""

# 스냅샷·라이브 양쪽에서 쓰는 영양 항목
NUT_FIELDS = ["energy_kcal", "protein_g", "fat_g", "carbo_g", "fiber_g", "sugar_g",
              "sodium_mg", "potassium_mg", "calcium_mg", "iron_mg", "phosphorus_mg",
              "saturated_fat_g", "trans_fat_g", "cholesterol_mg", "vitD_ug",
              "vitC_mg", "vitA_rae_ug", "thiamin_mg", "riboflavin_mg",
              "niacin_mg", "beta_carotene_ug"]


def neo4j_configured() -> bool:
    return bool(NEO4J_URI and NEO4J_PASSWORD)


def _fetch_live() -> dict | None:
    """Aura에서 Care-Eat 서브그래프를 읽어 스냅샷과 같은 형태로 만든다.

    실패하면 None — 호출부가 스냅샷으로 넘어간다. 여기서 예외를 밖으로 던지면
    Aura가 쉬는 동안 개선안 탭 전체가 죽는다.
    """
    if not neo4j_configured():
        return None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        log.warning("[care] neo4j 드라이버가 없습니다 — 스냅샷을 씁니다")
        return None

    try:
        drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                                   connection_timeout=NEO4J_TIMEOUT)
        with drv.session(database=NEO4J_DATABASE) as ses:
            run = lambda q: [r.data() for r in ses.run(q)]
            foods_raw = run(Q_FOOD)
            recipes = run(Q_RECIPE)
            edges = run(Q_EDGE)
            disease = run(Q_DISEASE)
        drv.close()
    except Exception as e:
        log.warning("[care] Neo4j 읽기 실패 — 스냅샷으로 대체합니다: %r", e)
        return None

    if not foods_raw or not recipes:
        log.warning("[care] Neo4j 결과가 비었습니다 — 스냅샷으로 대체합니다")
        return None

    ing = {}
    for r in recipes:
        n = r.get("nutrition") or {}
        ing[r["id"]] = {
            "t": r.get("title"), "c": r.get("category"),
            "n": {k: round(float(n.get(k) or 0), 3) for k in NUT_FIELDS},
        }

    foods = {f["id"]: {"t": f["title"], "m": f.get("meal_cat"), "i": []}
             for f in foods_raw}
    for e in edges:
        v = foods.get(e["food_id"])
        if v is None:
            continue
        num = lambda x: float(x) if isinstance(x, (int, float)) else 0.0
        v["i"].append([e["recipe_id"], round(num(e.get("weight")), 2),
                       round(num(e.get("nutri_weight")), 2)])

    broth = {rid for rid, v in ing.items()
             if "육수" in (v["t"] or "") or "스톡" in (v["t"] or "")}
    for v in foods.values():
        v["i"].sort(key=lambda x: (-x[1], x[0]))
        tot = {k: 0.0 for k in NUT_FIELDS}
        gram = bg = 0.0
        miss = []
        for rid, w, nw in v["i"]:
            iv = ing.get(rid)
            if not iv:
                continue
            gram += w
            if rid in broth:
                bg += w
            if nw <= 0:
                continue
            if (iv["t"] or "") in NA_MISSING:
                miss.append(iv["t"])
            for k in NUT_FIELDS:
                tot[k] += (iv["n"].get(k) or 0) * nw / 100.0
        v["g"] = round(gram, 1)
        v["broth_g"] = round(bg, 1)
        v["n"] = {k: round(x, 2) for k, x in tot.items()}
        if miss:
            v["na_missing"] = sorted(set(miss))

    papers, pidx, ev = [], {}, []
    for r in disease:
        ps = []
        for t in (r.get("papers") or [])[:4]:
            if t not in pidx:
                pidx[t] = len(papers)
                papers.append(t)
            ps.append(pidx[t])
        ev.append({"d": r["disease"],
                   "f": 1 if r["direction"] == "FORBIDDEN_INGREDIENT" else 0,
                   "n": r.get("nutrient"), "i": r["ingredient"],
                   "p": ps, "doi": (r.get("dois") or [])[:4]})

    log.info("[care] Neo4j 적재 완료 — 요리 %d · 식재료 %d · 근거 %d",
             len(foods), len(ing), len(ev))
    return {"ing": ing, "foods": foods, "evidence": {"papers": papers, "ev": ev}}''')

# ── 3) _load 를 캐시 + 폴백 구조로 ──────────────────────────────
old = s[s.index('@lru_cache(maxsize=1)\ndef _load():'):s.index('def available() -> bool:')]
new = '''_CACHE: dict = {"data": None, "at": 0.0, "source": None, "error": None}


def _read_snapshot() -> dict:
    def j(name):
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    return {"ing": j("ingredients.json"), "foods": j("foods.json"),
            "evidence": j("evidence.json")}


def _index(raw: dict) -> dict:
    """원자료(라이브든 스냅샷이든) → 조회용 색인."""
    ing, foods, evd = raw["ing"], raw["foods"], raw["evidence"]

    by_name = {}
    for rid, v in ing.items():
        t = v.get("t")
        if t and t != "nan":
            by_name.setdefault(t, rid)

    for rid, v in ing.items():
        n = v["n"]
        t = v.get("t") or ""
        v["seasoning"] = (
            v.get("c") in SEASONING_CAT
            or n.get("sodium_mg", 0) >= SALT_MG_100G
            or bool(SEASONING_NAME.search(t))
            or bool(USE_HINT.search(t))
        )

    forbidden, recommended = {}, {}
    for r in evd["ev"]:
        tgt = forbidden if r["f"] else recommended
        tgt.setdefault(r["d"], {}).setdefault(r["i"], []).append(r)

    title_idx = {}
    for fid, v in foods.items():
        title_idx.setdefault(_norm(v["t"]), []).append(fid)
        v.setdefault("n", {})
        v.setdefault("g", 0)
        v["ing_ids"] = [x[0] for x in v.get("i") or []]   # [recipe_id, 제공g, 가식부g]

    return {"ing": ing, "foods": foods, "ev": evd["ev"], "papers": evd["papers"],
            "by_name": by_name, "forbidden": forbidden, "recommended": recommended,
            "title_idx": title_idx}


def reload(force: bool = False) -> dict:
    """Aura에서 다시 읽어 캐시를 갱신한다. 실패하면 스냅샷."""
    if force:
        _CACHE["at"] = 0.0
    return _load()


def _load():
    now = time.time()
    if _CACHE["data"] is not None and now - _CACHE["at"] < CACHE_TTL:
        return _CACHE["data"]

    raw, source, err = None, None, None
    if neo4j_configured():
        raw = _fetch_live()
        if raw:
            source = "neo4j"
        else:
            err = "Neo4j를 읽지 못해 스냅샷을 사용합니다"
    if raw is None:
        raw = _read_snapshot()
        source = "snapshot"

    data = _index(raw)
    _CACHE.update({"data": data, "at": now, "source": source, "error": err})
    return data


'''
s = s.replace(old, new)

# time import
s = s.replace('import os\nimport re\nimport unicodedata', 'import os\nimport re\nimport time\nimport unicodedata')
if 'import logging' not in s:
    s = s.replace('import json\nimport os', 'import json\nimport logging\nimport os')
if 'log = logging.getLogger' not in s:
    s = s.replace('DATA_DIR = os.path.join', 'log = logging.getLogger("care.graph")\n\nDATA_DIR = os.path.join')

# ── 4) available / stats 에 출처 표시 ──────────────────────────
old = s[s.index('def available() -> bool:'):s.index('# ═════', s.index('def available() -> bool:'))]
new = '''def available() -> bool:
    """자료를 읽을 수 있는가 — Aura든 스냅샷이든."""
    if neo4j_configured():
        return True
    return all(os.path.exists(os.path.join(DATA_DIR, f))
               for f in ("ingredients.json", "foods.json", "evidence.json"))


def stats() -> dict:
    g = _load()
    return {
        "source": _CACHE["source"],          # neo4j | snapshot
        "loaded_at": _CACHE["at"],
        "age_sec": round(time.time() - _CACHE["at"]) if _CACHE["at"] else None,
        "ttl_sec": CACHE_TTL,
        "neo4j_configured": neo4j_configured(),
        "note": _CACHE["error"],
        "foods": len(g["foods"]),
        "ingredients": len(g["ing"]),
        "evidence": len(g["ev"]),
        "papers": len(g["papers"]),
        "diseases": sorted({r["d"] for r in g["ev"]}),
        "meal_categories": {c: sum(1 for v in g["foods"].values() if v["m"] == c)
                            for c in MEAL_CATS},
    }


'''
s = s.replace(old, new)

io.open(p, 'w', encoding='utf-8').write(s)
print('graph.py Neo4j 라이브 연결 추가 완료')
