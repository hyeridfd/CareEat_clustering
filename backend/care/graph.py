"""Care-Eat 식품·메뉴 그래프 커넥터 (Neo4j 스냅샷 기반).

원본 Neo4j 스키마 (노드 이름이 직관과 반대이므로 주의)
--------------------------------------------------------------
  Food(859)         = 요리·메뉴      title   예) 고등어조림, 간장닭볶음탕
  Recipe(415)       = 식재료         title   예) 고등어, 두부, 백미, 소금
  Meal_Category(6)  = 밥·국·주찬·부찬·김치·간식   name
  Disease(6)        = 근감소증·고혈압·당뇨병·신장질환·연하장애·치매

  Food   -HAS_INGREDIENT->           Recipe        (7,532)  ※ 분량(g) 없음
  Food   -CATEGORY_IS->              Meal_Category (859)
  Recipe -BELONGS_TO->               Category      (414, 식품공전 40종)
  Recipe -CONTAINS->                 Nutrition     (414, 가식부 100 g 기준)
  Disease-RECOMMENDED_INGREDIENT->   Recipe        (4,688)
  Disease-FORBIDDEN_INGREDIENT->     Recipe        (1,143)

자료는 Neo4j Aura에서 직접 읽는다 (식품·메뉴 DB는 주 단위로 갱신된다).
다만 개선안 하나에 집계 쿼리가 10번 넘게 돌고 Aura는 쉬었다 깨어나므로,
**읽어서 메모리에 얹어 두고 쓴다**:

    Aura 연결됨  →  서브그래프(약 1,865 노드)를 한 번에 읽어 캐시 (TTL 6시간)
    Aura 안 됨   →  care/graph_data/*.json 스냅샷으로 폴백 (앱은 계속 돈다)

강제 갱신은 reload(force=True) 또는 GET /care/facility/graph-status?refresh=true.
스냅샷 파일 자체의 갱신은 scripts/export_graph.py 참고.

반드시 지켜야 하는 네 가지 안전장치
--------------------------------------------------------------
Disease -RECOMMENDED_INGREDIENT-> Recipe 관계는 **영양소를 매개로** 만들어졌다.
그래서 '소금'이 고혈압 권장 재료로 들어와 있다(마그네슘·칼슘을 함유한다는
이유로). 논문 근거 자체는 진짜지만 재료 단위로 그대로 쓰면 위험하다.

  ① 영양소가 1급 근거, 재료는 그 급원일 뿐
     standard_key 가 ``NUT:`` 인 관계만 랭킹에 쓴다.
     ``GPT:``(LLM 추출 자유문구) · ``CAT:``(식품군 용어)는 참고 정보로만 둔다.
     Nutrition 노드에 없는 영양소(마그네슘·오메가3 등)는 검증이 불가능하므로
     랭킹에서 제외한다. — '소금 = 고혈압 권장'이 걸러지는 지점이 바로 여기다.
  ② 1인분 실측 함량으로 줄 세운다
     rel.weight(g)를 곱해 요리 1인분 영양량을 실제로 계산한다.
     "이 메뉴는 단백질 급원이다"가 아니라 "이 메뉴 한 그릇에 단백질 21 g"이다.
  ③ 금기가 권장을 이긴다
     같은 재료가 FORBIDDEN에도 있으면 무조건 제외한다.
  ④ 조미료 분류는 통째로 제외
     조미료류·조미식품·장류·당류·주류, 그리고 100 g당 나트륨 1,200 mg 이상인
     재료는 '급원'이 될 수 없다(대신 메뉴의 염도 부담으로 카운트한다).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from functools import lru_cache

log = logging.getLogger("care.graph")

DATA_DIR = os.path.join(os.path.dirname(__file__), "graph_data")

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
    return {"ing": ing, "foods": foods, "evidence": {"papers": papers, "ev": ev}}

# ── ④ 조미료·염장 재료 ──────────────────────────────────────────────
SEASONING_CAT = {"조미료류", "조미식품", "장류", "당류", "주류", "유지류", "식용유지류"}
# 분류가 '어패류'·'해조류'로 잡혀 있지만 실제로는 조미·육수 재료인 것들.
# (멸치액젓·참치액은 Nutrition의 나트륨이 0으로 비어 있어 함량 기준 필터에
#  걸리지 않는다. 이름으로 한 번 더 막는다.)
SEASONING_NAME = re.compile(
    r"액젓|젓갈|새우젓|참치액|굴소스|혼다시|스톡|부이용|다시팩|"
    r"소금|간장|된장|고추장|쌈장|춘장|설탕|물엿|올리고당|시럽|"
    r"맛술|미림|청주|조미료|식초|후추|케첩|마요네즈|카레가루|기름|버터|마가린|쇼트닝|"
    r"명란|창란|가쓰오부시|가다랑어(포)?")
# 가공·염장 식품군: Nutrition의 나트륨이 0으로 비어 있는 경우가 많아
# '나트륨이 없다'가 아니라 '모른다'로 다뤄야 한다(저염 후보 랭킹에서 뒤로 보낸다).
SALTY_CAT = {"김치류", "장아찌·절임류", "수산가공식품류", "식육가공품 및 포장육",
             "유가공품류", "젓갈류", "즉석식품류"}
# 이름의 괄호가 '어디에 쓰는 재료인지'를 알려 준다 — 미량 사용 재료는 급원에서 뺀다.
USE_HINT = re.compile(r"육수용|국물용|세척용|절임용|데침용|밑간|양념|소스용|드레싱|튀김옷|고명")
SALT_MG_100G = 1200.0          # 이 이상이면 급원이 아니라 염도 부담으로 본다
KCAL_FLOOR = 30.0              # 재료 랭킹에서 100 kcal당 환산 시 분모 하한

# 나트륨 값이 비어 있는데 실제로는 짠 재료 — 1인분 나트륨이 과소 계산된다.
# 값을 임의로 채우지 않고, 이 재료가 든 요리에 '과소 추정' 표시를 단다.
NA_MISSING = {"멸치액젓", "참치액", "명란(명태알)", "명란젓(저염)",
              "가쓰오부시", "다시마(말린것)", "새우(말린것)", "까나리액젓"}

# 이름은 염장·절임인데 재료에 그 염장품이 없는 요리 — 레시피 매핑 오류로
# 나트륨이 통째로 빠진다. (짜사이무침: 재료가 '짜사이'가 아니라 생'무' 60 g,
# 1인분 나트륨 6 mg.) 저염 후보로 올라오면 위험하므로 이름으로 걸러 낸다.
BRINED_NAME = re.compile(r"짜사이|장아찌|짠지|단무지|오이지|절임|피클|젓무침|"
                         r"자반|젓갈|명란|창란|깻잎지|양무침")
BRINED_MIN_NA = 100.0     # 염장 이름인데 1인분 나트륨이 이보다 낮으면 자료를 의심한다

# ② 역방향 지표 상한 — 요리 한 개당. KDRI 2025 노인 나트륨 목표(1,800~1,900 mg/일)를
#    끼니·구성별로 나눈 값이다. 단백질만 보고 고르면 돼지갈비김치찜(단백질 40 g,
#    나트륨 3,320 mg)이 1등이 되므로 반드시 함께 건다.
# 이름은 염장·절임인데 재료에 그 염장품이 없는 요리 — 레시피 매핑 오류로
# 나트륨이 통째로 빠진다. (짜사이무침: 재료가 '짜사이'가 아니라 생'무' 60 g,
# 1인분 나트륨 6 mg.) 저염 후보로 올라오면 위험하므로 이름으로 걸러 낸다.
BRINED_NAME = re.compile(r"짜사이|장아찌|짠지|단무지|오이지|절임|피클|젓무침|"
                         r"자반|젓갈|명란|창란|깻잎지")
BRINED_MIN_NA = 100.0     # 염장 이름인데 1인분 나트륨이 이보다 낮으면 자료를 의심한다

MAX_SODIUM = {"국": 400, "주찬": 600, "부찬": 300, "밥": 200, "간식": 200, "김치": 400}
MAX_SAT_FAT = {"국": 3.0, "주찬": 7.0, "부찬": 3.0, "밥": 2.0, "간식": 3.0, "김치": 2.0}

# 요리 하나가 하루 기준치를 통째로 넘으면 레시피 분량을 의심해야 한다.
# (해물버섯누룽지탕: 건새우 40 g → 칼슘 1,629 mg. 건새우를 국에 40 g 쓰지는 않는다.)
# 값은 KDRI 2025 노인 기준의 대략치 — 제외가 아니라 '확인 필요' 표시용이다.
DAILY_REF = {"protein_g": 55, "calcium_mg": 775, "iron_mg": 7, "fiber_g": 27,
             "potassium_mg": 3500, "vitC_mg": 100, "vitD_ug": 15,
             "energy_kcal": 1750, "phosphorus_mg": 700}

# ── ① Nutrition 노드에 실제로 존재하는 영양소만 매핑 ─────────────────
NUT_KEY = {
    "NUT:에너지(kcal)": "energy_kcal",
    "NUT:단백질(g)": "protein_g",
    "NUT:지방(g)": "fat_g",
    "NUT:식이섬유(g)": "fiber_g",
    "NUT:당류(g)": "sugar_g",
    "NUT:나트륨(mg)": "sodium_mg",
    "NUT:칼륨(mg)": "potassium_mg",
    "NUT:칼슘(mg)": "calcium_mg",
    "NUT:철(mg)": "iron_mg",
    "NUT:인(mg)": "phosphorus_mg",
    "NUT:포화지방산(g)": "saturated_fat_g",
    "NUT:트랜스지방산(g)": "trans_fat_g",
    "NUT:콜레스테롤(mg)": "cholesterol_mg",
    "NUT:비타민 D(μg)": "vitD_ug",
    "NUT:비타민 C(mg)": "vitC_mg",
    "NUT:티아민(mg)": "thiamin_mg",
}
# 검증 불가(Nutrition 노드에 항목이 없음): 마그네슘·비타민B6·오메가3/6·총불포화지방산
UNVERIFIABLE = {
    "NUT:마그네슘(mg)", "NUT:비타민B6(mg)", "NUT:오메가3지방산(g)",
    "NUT:오메가6지방산(g)", "NUT:총불포화지방산(g)",
    "NUT:오메가3지방산(g)+오메가6지방산(g)",
    "NUT:티아민(mg)+리보플라빈(mg)+니아신(mg)",
}

# Care-Eat 내부 영양소 코드 → Nutrition 필드
CARE_NUT = {
    "energy": "energy_kcal", "protein": "protein_g", "fat": "fat_g",
    "carb": "carbo_g", "fiber": "fiber_g", "na": "sodium_mg",
    "k": "potassium_mg", "ca": "calcium_mg", "fe": "iron_mg",
    "p": "phosphorus_mg", "vitd": "vitD_ug", "vitc": "vitC_mg",
}
# 낮을수록 좋은 지표 (역방향)
REVERSE = {"sodium_mg", "saturated_fat_g", "trans_fat_g", "cholesterol_mg", "sugar_g"}

MEAL_CATS = ["밥", "국", "주찬", "부찬", "김치", "간식"]


# ══════════════════════════════════════════════════════════════════
# 스냅샷 로딩
# ══════════════════════════════════════════════════════════════════
_CACHE: dict = {"data": None, "at": 0.0, "source": None, "error": None}


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


def available() -> bool:
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


# ══════════════════════════════════════════════════════════════════
# 메뉴 이름 매칭
# ══════════════════════════════════════════════════════════════════
_PAREN = re.compile(r"\([^)]*\)")
_NONWORD = re.compile(r"[^0-9A-Za-z가-힣]+")


def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = _PAREN.sub("", s)
    return _NONWORD.sub("", s)


def match_menu(name: str, limit: int = 5) -> list[dict]:
    """식단표 메뉴명을 Food(요리) 노드에 맞춘다.

    완전일치 → 포함관계 → 어간(뒤 2~3글자 조리법) 순으로 넓혀 간다.
    '잡곡밥'처럼 DB에 없는 메뉴는 빈 리스트를 돌려준다.
    """
    g = _load()
    key = _norm(name)
    if not key:
        return []
    out, seen = [], set()

    def push(fid, how):
        if fid in seen:
            return
        seen.add(fid)
        v = g["foods"][fid]
        out.append({"id": fid, "title": v["t"], "meal_cat": v["m"], "match": how})

    for fid in g["title_idx"].get(key, []):
        push(fid, "exact")
    if len(out) < limit:
        for k, ids in g["title_idx"].items():
            if k != key and (key in k or k in key):
                for fid in ids:
                    push(fid, "partial")
            if len(out) >= limit * 3:
                break
    return out[:limit]


# ══════════════════════════════════════════════════════════════════
# ① 영양소 근거 조회
# ══════════════════════════════════════════════════════════════════
def nutrient_evidence(nutrient_key: str, disease: str | None = None,
                      forbidden: bool = False) -> list[dict]:
    """특정 영양소에 대한 Disease-재료 관계를 그대로 돌려준다(검증 전 원자료)."""
    g = _load()
    rows = []
    for r in g["ev"]:
        if r["n"] != nutrient_key:
            continue
        if disease and r["d"] != disease:
            continue
        if bool(r["f"]) != forbidden:
            continue
        rows.append(r)
    return rows


def nutrient_sources(nutrient: str, disease: str | None = None,
                     limit: int = 12, min_kcal: float = 5.0) -> list[dict]:
    """목표 영양소의 '급원 식재료'를 100 kcal당 함량 순으로 돌려준다.

    nutrient : Care-Eat 코드(protein, ca, fiber …) 또는 Nutrition 필드명.
    안전장치 ①②③④를 모두 적용한다.
    """
    g = _load()
    field = CARE_NUT.get(nutrient, nutrient)
    if field in REVERSE:
        raise ValueError(f"{nutrient}은 낮출 대상이라 급원 조회 대상이 아닙니다")

    # ① NUT: 이면서 Nutrition에 실제로 있는 영양소만 근거로 인정
    nut_keys = [k for k, v in NUT_KEY.items() if v == field]
    cand: dict[str, list] = {}
    for r in g["ev"]:
        if r["f"] or r["n"] not in nut_keys:
            continue
        if disease and r["d"] != disease:
            continue
        cand.setdefault(r["i"], []).append(r)

    forb = g["forbidden"].get(disease, {}) if disease else {}
    out = []
    for name, rows in cand.items():
        rid = g["by_name"].get(name)
        if not rid:
            continue
        v = g["ing"][rid]
        if v["seasoning"]:            # ④
            continue
        if name in forb:              # ③
            continue
        n = v["n"]
        kcal = n.get("energy_kcal") or 0
        if kcal < min_kcal:
            continue
        amount = n.get(field) or 0
        if amount <= 0:
            continue
        dens = amount * 100.0 / max(kcal, KCAL_FLOOR)   # ② 100 kcal당 함량
        out.append({
            "ingredient": name, "recipe_id": rid, "category": v["c"],
            "per_100g": amount, "per_100kcal": round(dens, 2),
            "energy_kcal": kcal, "sodium_mg": n.get("sodium_mg", 0),
            "diseases": sorted({r["d"] for r in rows}),
            "papers": [g["papers"][p] for p in rows[0]["p"][:2]],
            "dois": rows[0].get("doi", [])[:2],
        })
    out.sort(key=lambda x: -x["per_100kcal"])
    return out[:limit]


# ══════════════════════════════════════════════════════════════════
# 메뉴(요리) 후보 추천
# ══════════════════════════════════════════════════════════════════
def _food_profile(fid: str, field: str) -> dict:
    """요리 한 그릇에서 그 영양소를 실제로 얼마나 내는 재료인지 (1인분 기여량 g/mg)."""
    g = _load()
    v = g["foods"][fid]
    tops, salt = [], 0
    for rid, w, nw in v.get("i") or []:
        iv = g["ing"].get(rid)
        if not iv or not nw:
            continue
        if iv["seasoning"]:
            salt += 1
            continue
        amt = (iv["n"].get(field) or 0) * nw / 100.0    # ② 가식부 분량을 곱한 실제 기여량
        if amt <= 0:
            continue
        tops.append((round(amt, 2), iv["t"], w))
    tops.sort(reverse=True)
    return {"tops": tops[:3], "salt_load": salt}


def food_candidates(nutrient: str, meal_cat: str | None = None,
                    disease: str | None = None, avoid: list[str] | None = None,
                    limit: int = 10, exclude: list[str] | None = None,
                    min_serving_g: float = 0,
                    max_sodium_mg: float | None = None) -> list[dict]:
    """그 영양소를 **한 그릇에 실제로 많이 담는** 요리를 돌려준다.

    meal_cat : 밥·국·주찬·부찬·김치·간식 중 하나로 제한(같은 자리 교체용).
    avoid    : 피해야 할 질환 목록.
    """
    g = _load()
    field = CARE_NUT.get(nutrient, nutrient)
    if field in REVERSE:
        raise ValueError(f"{nutrient}은 낮출 대상이라 급원 조회 대상이 아닙니다")

    # ③ 금기가 권장을 이긴다 — 금기 재료가 그 메뉴의 급원 상위 3개에 들면 제외,
    #    나머지는 caution_ingredients로 남겨 담당자가 판단하게 한다.
    ban = set()
    for d in (avoid or ([disease] if disease else [])):
        ban |= set(g["forbidden"].get(d, {}))
    skip = {_norm(x) for x in (exclude or [])}

    def collect(na_cap_mult):
        out = []
        for fid, v in g["foods"].items():
            if meal_cat and v["m"] != meal_cat:
                continue
            if _norm(v["t"]) in skip or (v.get("g") or 0) < min_serving_g:
                continue
            n = v.get("n") or {}
            amount = n.get(field) or 0
            if amount <= 0:
                continue
            # ② 역방향 지표 상한 — 목표 영양소가 아무리 높아도 짜면 후보가 아니다
            cap_na = (max_sodium_mg if max_sodium_mg is not None
                      else MAX_SODIUM.get(v["m"], 500)) * na_cap_mult
            if (n.get("sodium_mg") or 0) > cap_na:
                continue
            if field != "saturated_fat_g":
                cap_sf = MAX_SAT_FAT.get(v["m"], 5.0) * na_cap_mult
                if (n.get("saturated_fat_g") or 0) > cap_sf:
                    continue
            pf = _food_profile(fid, field)
            if not pf["tops"]:
                continue
            if {t for _, t, _ in pf["tops"]} & ban:
                continue
            names = {g["ing"][r]["t"] for r in v["ing_ids"] if r in g["ing"]}
            kcal = n.get("energy_kcal") or 0
            out.append({
                "id": fid, "title": v["t"], "meal_cat": v["m"],
                "serving_g": v.get("g"),
                "amount": round(amount, 1),                 # 1인분 실측 함량
                "unit": _unit(field),
                "energy_kcal": round(kcal, 0),
                "sodium_mg": round(n.get("sodium_mg") or 0, 0),
                "saturated_fat_g": round(n.get("saturated_fat_g") or 0, 1),
                "per_100kcal": round(amount * 100.0 / kcal, 1) if kcal > 0 else None,
                "key_ingredients": [f"{t} {w:g}g" for _, t, w in pf["tops"]],
                "sodium_underestimated": v.get("na_missing") or None,
                "broth_missing": (v["m"] == "국" and not (v.get("broth_g") or 0)) or None,
                "amount_outlier": (amount > DAILY_REF[field]) if field in DAILY_REF else None,
                "caution_ingredients": sorted(names & ban),
            })
        return out

    rows = collect(1.0)
    relaxed = False
    if len(rows) < max(3, limit // 2):     # 상한이 너무 빡빡하면 완화하고 그 사실을 알린다
        rows, relaxed = collect(1.5), True
    for r in rows:
        r["cap_relaxed"] = relaxed or None
    rows.sort(key=lambda x: -x["amount"])
    return rows[:limit]


def _unit(field: str) -> str:
    return "mg" if field.endswith("_mg") else "μg" if field.endswith("_ug") \
        else "kcal" if field == "energy_kcal" else "g"


def menu_nutrition(menu: str) -> dict | None:
    """메뉴 한 그릇의 영양량. 못 찾으면 None."""
    m = match_menu(menu, limit=1)
    if not m:
        return None
    g = _load()
    v = g["foods"][m[0]["id"]]
    return {"menu": menu, "matched": v["t"], "meal_cat": v["m"],
            "serving_g": v.get("g"), "broth_g": v.get("broth_g"),
            "nutrition": v.get("n"),
            "sodium_underestimated": v.get("na_missing") or None,
            "ingredients": [{"name": g["ing"][r]["t"], "g": w, "edible_g": nw}
                            for r, w, nw in (v.get("i") or []) if r in g["ing"]]}


def check_menu(name: str, diseases: list[str]) -> dict:
    """식단표의 메뉴 하나를 질환 금기 재료 기준으로 점검한다."""
    g = _load()
    m = match_menu(name, limit=1)
    if not m:
        return {"menu": name, "matched": None, "warnings": [], "unknown": True}
    fid = m[0]["id"]
    v = g["foods"][fid]
    warn = []
    for d in diseases:
        forb = g["forbidden"].get(d, {})
        for rid in v["i"]:
            iv = g["ing"].get(rid)
            if not iv or iv["t"] not in forb:
                continue
            rows = forb[iv["t"]]
            nuts = sorted({r["n"] for r in rows if r["n"].startswith("NUT:")})
            if not nuts:            # ① NUT 근거가 없으면 경고하지 않는다
                continue
            warn.append({
                "disease": d, "ingredient": iv["t"],
                "nutrients": nuts, "category": iv["c"],
                "papers": [g["papers"][p] for p in rows[0]["p"][:1]],
            })
    return {"menu": name, "matched": m[0]["title"], "food_id": fid,
            "meal_cat": v["m"], "warnings": warn, "unknown": False}


def low_salt_candidates(meal_cat: str | None = None, limit: int = 10,
                        exclude: list[str] | None = None,
                        skip_underestimated: bool = True) -> list[dict]:
    """1인분 나트륨(mg)이 낮은 요리 — 나트륨 저감 우선순위의 대체 메뉴용.

    멸치액젓·명란처럼 나트륨 값이 비어 있는 재료가 든 요리는 실제보다 낮게
    계산된다. 기본값은 그런 요리를 저염 후보에서 **빼는 것**이다 — 틀릴 거면
    짜게 틀리는 편이 안전하다.
    """
    g = _load()
    skip = {_norm(x) for x in (exclude or [])}
    rows = []
    for fid, v in g["foods"].items():
        if meal_cat and v["m"] != meal_cat:
            continue
        if _norm(v["t"]) in skip:
            continue
        if skip_underestimated and v.get("na_missing"):
            continue
        n = v.get("n") or {}
        na = n.get("sodium_mg") or 0
        if skip_underestimated and na < BRINED_MIN_NA and BRINED_NAME.search(v["t"] or ""):
            continue
        salty = []
        for rid, w, nw in v.get("i") or []:
            iv = g["ing"].get(rid)
            if not iv or not nw:
                continue
            if (iv["n"].get("sodium_mg") or 0) * nw / 100.0 >= 150:
                salty.append(f"{iv['t']} {w:g}g")
        rows.append({
            "id": fid, "title": v["t"], "meal_cat": v["m"],
            "serving_g": v.get("g"), "broth_g": v.get("broth_g"),
            "sodium_mg": round(na, 0),
            "energy_kcal": round(n.get("energy_kcal") or 0, 0),
            "salty_ingredients": salty[:3],
            "sodium_underestimated": v.get("na_missing") or None,
            # 국 198개 중 125개는 육수가 재료로 등록돼 있지 않다 → 중량이 건더기뿐이다
            "broth_missing": (v["m"] == "국" and not (v.get("broth_g") or 0)) or None,
        })
    rows.sort(key=lambda x: x["sodium_mg"])
    return rows[:limit]


def alternatives_for(menu: str, nutrient: str | None = None, limit: int = 6,
                     avoid: list[str] | None = None) -> dict:
    """특정 메뉴의 '같은 자리' 대체 후보 — 바꾸면 무엇이 얼마나 달라지는지까지.

    잔반이 많은 메뉴를 바꿀 때 밥은 밥, 국은 국으로 갈아야 식단이 성립한다.
    nutrient를 주면 그 영양소를 올리는 쪽으로, 주지 않으면 나트륨이 낮은 쪽으로 고른다.
    """
    g = _load()
    m = match_menu(menu, limit=1)
    if not m:
        return {"menu": menu, "matched": None, "meal_cat": None, "candidates": []}
    fid = m[0]["id"]
    cur = g["foods"][fid]
    cn = cur.get("n") or {}
    cat = cur["m"]
    field = CARE_NUT.get(nutrient, nutrient) if nutrient else None

    if nutrient:
        cands = food_candidates(nutrient, meal_cat=cat, avoid=avoid,
                                limit=limit, exclude=[menu, cur["t"]])
    else:
        cands = low_salt_candidates(meal_cat=cat, limit=limit,
                                    exclude=[menu, cur["t"]])

    # 교체 효과 — 담당자가 보는 건 순위가 아니라 "바꾸면 얼마나 달라지나"다
    for c in cands:
        cand_n = (g["foods"][c["id"]].get("n") or {})
        c["delta"] = {
            "sodium_mg": round((cand_n.get("sodium_mg") or 0) - (cn.get("sodium_mg") or 0), 0),
            "energy_kcal": round((cand_n.get("energy_kcal") or 0) - (cn.get("energy_kcal") or 0), 0),
            "protein_g": round((cand_n.get("protein_g") or 0) - (cn.get("protein_g") or 0), 1),
        }
        if field:
            c["delta"]["target"] = round((cand_n.get(field) or 0) - (cn.get(field) or 0), 1)

    return {
        "menu": menu, "matched": cur["t"], "meal_cat": cat,
        "current": {"serving_g": cur.get("g"),
                    "energy_kcal": round(cn.get("energy_kcal") or 0, 0),
                    "protein_g": round(cn.get("protein_g") or 0, 1),
                    "sodium_mg": round(cn.get("sodium_mg") or 0, 0),
                    "target": round(cn.get(field) or 0, 1) if field else None,
                    "sodium_underestimated": cur.get("na_missing") or None},
        "basis": "1인분 실측 함량" if nutrient else "1인분 나트륨",
        "candidates": cands,
    }
