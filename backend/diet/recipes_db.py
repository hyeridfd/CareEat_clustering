# -*- coding: utf-8 -*-
"""
recipes_db.py  ─  레시피 DB 파일 위치·읽기 (한 곳에서 관리)
==========================================================
  · RECIPE_CSV  : data/recipes_v1.csv(새 레시피 DB, 14,482개 음식) 가 있으면 그것, 없으면 data/recipes.csv
  · LEGACY_CSV  : 기존 레시피 DB(data/recipes.csv, 859개) — 기존 '구분'을 유지할 때 참고
  · read_recipes(): cp949 / utf-8 자동 판별해서 읽는다 (recipes_v1.csv 는 cp949 로 저장되어 있음)
"""
from __future__ import annotations

import os

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_V1 = os.path.join(DATA_DIR, "recipes_v1.csv")
LEGACY_CSV = os.path.join(DATA_DIR, "recipes.csv")
RECIPE_CSV = _V1 if os.path.exists(_V1) else LEGACY_CSV


def read_recipes(path: str | None = None, **kw) -> pd.DataFrame:
    path = path or RECIPE_CSV
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, **kw)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"인코딩을 알 수 없음: {path}")
