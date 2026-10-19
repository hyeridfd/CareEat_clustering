"""
extra_recipes.py  ─  죽·백김치 (서버판)
data/extra_menus.json: 에이전트(extra_recipes.py)가 원재료·식약처 영양값으로 계산한 결과를 그대로 저장한 것
"""
import os
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
EXTRA_JSON = os.path.join(DATA_DIR, "extra_menus.json")
WHITE_PORRIDGE = "흰죽"
WHITE_KIMCHI = "백김치"
_CACHE = None


def load_extra_recipes(path: str = EXTRA_JSON) -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"죽": [], "김치": []}
    return _CACHE
