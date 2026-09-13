# -*- coding: utf-8 -*-
"""Supabase 조회 헬퍼"""
from __future__ import annotations


def fetch_all(sb, table: str, columns: str = "*", eq: dict | None = None, in_: dict | None = None,
              order: str | None = None, desc: bool = False, page: int = 1000):
    rows, start = [], 0
    while True:
        q = sb.table(table).select(columns)
        for k, v in (eq or {}).items():
            q = q.eq(k, v)
        for k, v in (in_ or {}).items():
            q = q.in_(k, list(v))
        if order:
            q = q.order(order, desc=desc)
        res = q.range(start, start + page - 1).execute()
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        start += page


def fetch_surveys(sb, nursing_home_id: str | None = None, elderly_ids=None):
    eq = {"nursing_home_id": nursing_home_id} if nursing_home_id else None
    in_ = {"elderly_id": elderly_ids} if elderly_ids else None
    return (fetch_all(sb, "basic_survey", eq=eq, in_=in_),
            fetch_all(sb, "nutrition_survey", eq=eq, in_=in_),
            fetch_all(sb, "satisfaction_survey", eq=eq, in_=in_))
