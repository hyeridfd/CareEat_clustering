# -*- coding: utf-8 -*-
"""하루치 실행 (크롤러 직후).

    python -m mapping.run                         # 오늘 (KST), Supabase
    python -m mapping.run --date 2026-11-27
    python -m mapping.run --full                  # 첫 실행: 전체 상품 판단 (이후에는 새 상품만)
    python -m mapping.run --source csv --store local --date 2026-11-26   # 오프라인 시험 (크롤러 CSV)
    python -m mapping.run --source csv --backfill  # 크롤러 CSV 스냅샷 날짜마다 가격 이력 채우기
    python -m mapping.run --no-llm                # LLM 끄기
    python -m mapping.run --price-only            # 검수 후 오늘 가격만 다시 계산

순서: ① 새 상품 감지 → ②~⑤ 판정·자동 승인/검수 대기열 → ⑥ 오늘 가격 → ⑦ 그래프(--graph) · 리포트
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import config as C
from . import matching, pricing, sources
from .judge import load_model
from .store import open_store
from .units import Converter

REPORT_DIR = os.path.join(C.HERE, "_reports")


def today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def load_products(source: str, day: date | None, store):
    if source == "csv":
        try:
            return sources.load_products_csv(day)
        except FileNotFoundError:
            return sources.load_products_csv(None)          # 그날 스냅샷이 없으면 최신본 (→ 오늘 가격은 건너뜀)
    return sources.load_products_supabase(store.sb)


def run_day(day: date, *, source="supabase", store_kind="supabase", full=False, use_llm=True,
            graph=False, targets=C.TARGETS_XLSX, quiet=False, price_only=False, graph_dry_run=False) -> dict:
    t0 = time.time()
    log = (lambda *a: None) if quiet else (lambda *a: print("[mapping]", *a, flush=True))
    store = open_store(store_kind)
    ings = sources.load_ingredients(targets)
    store.upsert_ingredients(sources.ingredient_rows(ings))

    products = load_products(source, day if source == "csv" else None, store)
    latest = sources.latest_day(products)
    log(f"상품 {len(products):,}개, 공급사별 최신일 {latest}")
    has_today = any(v is not None and v <= day and (day - v).days < C.STALE_DAYS for v in latest.values())
    stale = [s for s, v in latest.items() if v != day]
    if has_today and stale:
        log(f"⚠ {', '.join(stale)} 단가표가 {day} 것이 아닙니다 → 그 공급사는 최신 단가표({', '.join(str(latest[s]) for s in stale)})로 가격 계산")
    if not has_today:
        log(f"⚠ {day} 단가표가 아직 없습니다 (크롤러 실행 확인). 새 상품 판정만 하고 오늘 가격은 쓰지 않습니다.")

    # ① 새 상품
    seen = set() if full else store.seen_keys()
    if price_only:                                   # 검수 직후 가격만 다시 계산
        seen = set(zip(products["supplier"], products["item_cd"].astype(str)))
    keys = list(zip(products["supplier"], products["item_cd"].astype(str)))
    is_new = [k not in seen for k in keys]
    new = products[is_new].reset_index(drop=True)
    log(f"① 새 상품 {len(new):,}개 (이미 판단 {len(products) - len(new):,}개)")

    # ②~⑤ 판정
    model = load_model()
    catmap = matching.CategoryMap(store.load_category_map())
    conv = Converter(store.load_conversions())
    hist = store.load_daily(since=day - timedelta(days=C.MEDIAN_WINDOW_DAYS))
    ref = {}
    if len(hist):
        last = hist.sort_values("price_date").dropna(subset=["price_per_g_28d"]).groupby("ingredient_id").tail(1)
        ref = dict(zip(last["ingredient_id"], last["price_per_g_28d"]))
    llm = None
    if use_llm and len(new):
        from .llm import LLMJudge, examples_from_reviews
        llm = LLMJudge(examples_from_reviews(store.load_map(statuses=["approved", "rejected"])))
        if not llm.ready:
            llm = None
    if len(new):
        log(f"②~⑤ 판정 중 (상품 {len(new):,}개)" + (" — 이어서 애매한 쌍은 LLM 판정" if llm else ""))
    rows = matching.judge(new, ings, model=model, catmap=catmap, conv=conv, llm=llm, ref_prices=ref) if len(new) else []
    rows = store.protect_human(rows, keep_llm=llm is None)       # LLM 없이 다시 돌려도 이전 LLM 판정은 유지
    if rows:
        log(f"저장 중 ({len(rows):,}행)")
    store.upsert_map(rows)
    store.add_seen([{"supplier": s, "item_cd": i, "first_seen": str(day),
                     "n_pairs": 0} for s, i in zip(new["supplier"], new["item_cd"].astype(str))])
    st = Counter(r["status"] for r in rows)
    log(f"④⑤ 후보 쌍 {len(rows):,}개 → {dict(st)}" + (f", LLM {llm.calls}회" if llm else ""))

    # ⑥ 오늘 가격 (오늘 단가표가 없으면 건너뜀 — 빈 가격으로 덮어쓰지 않게)
    if not has_today:
        report = {"date": str(day), "status": "no_price_data", "new_products": len(new), "pairs": len(rows),
                  "judged": dict(st), "latest": {k: str(v) for k, v in latest.items()}}
        os.makedirs(REPORT_DIR, exist_ok=True)
        json.dump(report, open(os.path.join(REPORT_DIR, f"{day}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return report
    mapping = store.load_map(columns=["ingredient_id", "supplier", "item_cd", "status"],
                             statuses=["auto_approved", "approved"])
    daily, outliers, offers = pricing.decide(day, mapping, products, ings, history=hist, conv=conv)
    auto_out = [(o["supplier"], o["item_cd"], o["ingredient_id"]) for o in outliers if o["status"] == "auto_approved"]
    if auto_out:
        store.set_status(auto_out, "pending", "g당 가격 이상값 (규격 해석 확인)")
    store.upsert_daily(daily)
    cov = pricing.coverage(daily, ings)
    log(f"⑥ 가격 {cov['n_priced']}/{cov['n_ingredients']} 식재료, 사용 중량 기준 {cov['weight_pct']}% "
        f"(상위 300: {cov['top300_weight_pct']}%), 이상값 {len(outliers)}건")

    # ⑦ 그래프
    graph_res = None
    if graph:
        from .graph_export import export
        approved = store.load_map(statuses=["auto_approved", "approved"])
        try:
            graph_res = export(day, daily, offers, approved.to_dict("records"), ings, dry_run=graph_dry_run)
            log(f"⑦ 그래프 {graph_res}")
        except Exception as e:                                    # noqa: BLE001  그래프 실패가 가격 저장을 막지 않게
            graph_res = {"error": str(e)[:300]}
            log(f"⑦ 그래프 반영 실패: {e}")

    pending = store.load_map(columns=["ingredient_id", "status"], statuses=["pending"])
    report = {"date": str(day), "source": source, "store": store_kind, "products": len(products),
              "new_products": len(new), "pairs": len(rows), "status": dict(st), "outliers": len(outliers),
              "queue": int(len(pending)), "queue_ingredients": int(pending["ingredient_id"].nunique()) if len(pending) else 0,
              "coverage": cov, "llm_calls": llm.calls if llm else 0,
              "model": model.version if model else C.RULE_VERSION, "seconds": round(time.time() - t0, 1),
              "graph": graph_res}
    os.makedirs(REPORT_DIR, exist_ok=True)
    json.dump(report, open(os.path.join(REPORT_DIR, f"{day}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="공급사 식자재 가격 매핑 (하루치)")
    ap.add_argument("--date", help="기준일 YYYY-MM-DD (기본: 오늘 KST)")
    ap.add_argument("--source", choices=["supabase", "csv"], default="supabase")
    ap.add_argument("--store", choices=["supabase", "local"], default="supabase")
    ap.add_argument("--full", action="store_true", help="본 상품도 다시 판단 (사람 판정은 유지)")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--graph", action="store_true", help="Neo4j Recipe 노드에 공급사별 kg당 가격, Product·MAPPED_TO 반영")
    ap.add_argument("--graph-dry-run", action="store_true", help="그래프에 쓸 내용만 확인")
    ap.add_argument("--backfill", action="store_true", help="크롤러 CSV 스냅샷 날짜마다 실행 (--source csv)")
    ap.add_argument("--price-only", action="store_true", help="판정은 건너뛰고 오늘 가격만 다시 계산 (검수 반영)")
    ap.add_argument("--targets", default=C.TARGETS_XLSX)
    a = ap.parse_args(argv)

    if a.backfill:
        days = sorted(set(sources.csv_snapshot_days("hgreenfood")) | set(sources.csv_snapshot_days("sajo")))
        for d in days:
            r = run_day(d, source="csv", store_kind=a.store, use_llm=not a.no_llm, targets=a.targets)
            print(json.dumps({k: r.get(k) for k in ("date", "new_products", "coverage")}, ensure_ascii=False))
        return 0
    day = date.fromisoformat(a.date) if a.date else today_kst()
    r = run_day(day, source=a.source, store_kind=a.store, full=a.full, use_llm=not a.no_llm,
                graph=a.graph or a.graph_dry_run, graph_dry_run=a.graph_dry_run, targets=a.targets,
                price_only=a.price_only)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 3 if r.get("status") == "no_price_data" else 0     # 3 = 크롤러가 아직 안 끝남 (스케줄러가 다시 시도)


if __name__ == "__main__":
    sys.exit(main())
