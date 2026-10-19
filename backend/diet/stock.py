# -*- coding: utf-8 -*-
"""식재료 재고 추적 — 승인 식단의 예상 사용량 + 입고·실사·폐기 기록으로 날짜별 재고를 추정

  하루 처리 순서:  실사(아침 기준 실제 재고로 맞춤) → 입고 → 그날 식단 예상 사용 → 폐기
  로트(유통기한별 묶음) 단위로 관리하며, 사용·폐기·실사 차감은 유통기한이 빠른 로트부터(FIFO).
  예상 사용량은 승인된 식단 중 그 날짜를 포함하는 가장 최근 승인본을 쓴다.
  재고에 등록된(입고·실사 기록이 있는) 식재료만 추적한다.
  레시피 재료명 '마늘(다진것)' 사용분은 재고 '마늘'에서 차감한다.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

EXPIRY_SOON = 3          # 유통기한 D-3 이내 → 임박
LOOKAHEAD = 7            # 앞으로 7일 사용량으로 부족 판단
RECOUNT_DAYS = 7         # 마지막 실사 후 7일 넘으면 보정 권장
KIND_ORDER = {"실사": 0, "입고": 1, "폐기": 3}


def _d(x) -> dt.date | None:
    if not x:
        return None
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def _match(stock_name: str, recipe_name: str) -> bool:
    return recipe_name == stock_name or recipe_name.startswith(stock_name + "(")


class Plans:
    """승인 식단들 → 날짜별 예상 사용량"""

    def __init__(self, runs: list):
        self.runs = []
        for r in runs or []:
            s = _d(r.get("start_date"))
            du = (r.get("result") or {}).get("daily_usage") if isinstance(r.get("result"), dict) else r.get("daily_usage")
            if s and du:
                self.runs.append({"id": r["id"], "start": s, "approved_at": str(r.get("approved_at") or ""),
                                  "usage": du, "menu": r.get("menu") or [], "n_days": max(int(k) for k in du)})
        self.runs.sort(key=lambda r: r["approved_at"])          # 나중 승인이 우선

    def run_for(self, date: dt.date):
        for r in reversed(self.runs):
            n = (date - r["start"]).days + 1
            if 1 <= n <= r["n_days"]:
                return r, n
        return None, None

    def usage(self, date: dt.date) -> dict:
        r, n = self.run_for(date)
        return (r["usage"].get(str(n)) or {}) if r else {}


def _take(lots: list, qty: float, day: dt.date | None = None) -> float:
    """유통기한 빠른 로트부터 qty 만큼 뺌 → 실제로 뺀 양 (day 가 있으면 유통기한 지난 로트는 쓰지 않음)"""
    lots.sort(key=lambda l: (l["expiry"] or dt.date.max))
    got = 0.0
    for l in lots:
        if got >= qty:
            break
        if day and l["expiry"] and l["expiry"] < day:
            continue
        u = min(l["qty"], qty - got)
        l["qty"] -= u; got += u
    lots[:] = [l for l in lots if l["qty"] > 0.05]
    return got


def simulate(events: list, plans: Plans, until: dt.date) -> dict:
    """events [{event_date, kind, ingredient, qty_g, expiry}] → until 날짜 '아침'(그날 사용 전) 재고 상태"""
    ev = sorted([e for e in events if _d(e.get("event_date"))],
                key=lambda e: (_d(e["event_date"]), KIND_ORDER.get(e["kind"], 9)))
    if not ev:
        return {"lots": {}, "last_count": {}, "shortfall": {}, "used": {}}
    names = sorted({e["ingredient"] for e in ev}, key=len, reverse=True)   # 긴 이름 먼저 매칭
    lots = defaultdict(list)
    last_count, shortfall, used = {}, defaultdict(float), defaultdict(float)
    by_day = defaultdict(list)
    for e in ev:
        by_day[_d(e["event_date"])].append(e)
    day = _d(ev[0]["event_date"])
    while day <= until:
        todays = by_day.get(day, [])
        for e in todays:                                  # 실사 → 입고 (아침)
            if e["kind"] not in ("실사", "입고"):
                continue
            nm, q, ex = e["ingredient"], float(e.get("qty_g") or 0), _d(e.get("expiry"))
            if e["kind"] == "입고":
                if q > 0:
                    lots[nm].append({"qty": q, "expiry": ex, "since": day})
            else:
                cur = sum(l["qty"] for l in lots[nm])
                if ex:                                    # 유통기한까지 적었으면 그대로 교체
                    lots[nm] = [{"qty": q, "expiry": ex, "since": day}] if q > 0 else []
                elif q < cur:
                    _take(lots[nm], cur - q)
                elif q > cur:
                    lots[nm].append({"qty": q - cur, "expiry": None, "since": day})
                last_count[nm] = day
        if day == until:
            break
        for rn, g in plans.usage(day).items():            # 그날 식단 사용
            nm = next((n for n in names if _match(n, rn)), None)
            if not nm:
                continue
            got = _take(lots[nm], g, day)
            used[nm] += got
            if got + 0.5 < g:
                shortfall[nm] += g - got
        for e in todays:                                  # 폐기 (저녁)
            if e["kind"] == "폐기":
                _take(lots[e["ingredient"]], float(e.get("qty_g") or 0))
        day += dt.timedelta(days=1)
    return {"lots": {k: v for k, v in lots.items()}, "names": names, "last_count": last_count,
            "shortfall": dict(shortfall), "used": dict(used)}


def report(events: list, runs: list, date: dt.date) -> dict:
    plans = Plans(runs)
    sim = simulate(events, plans, date)
    names = sim.get("names") or []

    # 앞으로 사용 예정 (오늘 포함 7일)
    ahead = defaultdict(lambda: [0.0] * LOOKAHEAD)
    untracked = defaultdict(float)
    for i in range(LOOKAHEAD):
        for rn, g in plans.usage(date + dt.timedelta(days=i)).items():
            nm = next((n for n in names if _match(n, rn)), None)
            if nm:
                ahead[nm][i] += g
            else:
                untracked[rn] += g

    items, expiring = [], []
    for nm in sorted(set(sim["lots"]) | set(ahead) | set(sim["last_count"])):
        lots = [l for l in sim["lots"].get(nm, []) if l["qty"] > 0.05]
        total = sum(l["qty"] for l in lots)
        use = ahead.get(nm, [0.0] * LOOKAHEAD)
        # 소진 예상일: 누적 사용이 재고를 넘는 첫날
        run_out, acc = None, 0.0
        for i, g in enumerate(use):
            acc += g
            if acc > total + 0.5:
                run_out = i; break
        exp_lots = sorted([l for l in lots if l["expiry"]], key=lambda l: l["expiry"])
        first = exp_lots[0] if exp_lots else None
        d_left = (first["expiry"] - date).days if first else None
        # 유통기한까지 다 못 쓰고 남을 양 (FIFO 가정)
        waste_risk = 0.0
        if exp_lots:
            rest = list(use)
            for l in exp_lots:
                days = max(0, min(LOOKAHEAD, (l["expiry"] - date).days + 1))
                can = sum(rest[:days]); u = min(l["qty"], can)
                # rest 에서 u 만큼 앞에서부터 차감
                k = u
                for j in range(days):
                    t = min(rest[j], k); rest[j] -= t; k -= t
                if (l["expiry"] - date).days < LOOKAHEAD:
                    waste_risk += l["qty"] - u
        lc = sim["last_count"].get(nm)
        status = []
        if first and d_left is not None and d_left < 0:
            status.append("유통기한 지남")
        elif d_left is not None and d_left <= EXPIRY_SOON:
            status.append("유통기한 임박")
        if run_out is not None:
            status.append("부족 예상")
        if waste_risk > 50:
            status.append("남을 위험")
        if not lc or (date - lc).days > RECOUNT_DAYS:
            status.append("실사 필요")
        items.append({
            "식재료명": nm, "추정재고(g)": round(total), "오늘사용(g)": round(use[0]), "7일사용(g)": round(sum(use)),
            "남는일수": (round(total / (sum(use) / LOOKAHEAD), 1) if sum(use) > 0 else None),
            "소진예상": (f"{(date + dt.timedelta(days=run_out)):%m.%d}" if run_out is not None else None),
            "부족량(g)": round(max(0.0, sum(use) - total)),
            "가장빠른유통기한": first["expiry"].isoformat() if first else None, "D": d_left,
            "임박량(g)": round(sum(l["qty"] for l in exp_lots if (l["expiry"] - date).days <= EXPIRY_SOON)),
            "남을위험(g)": round(waste_risk), "마지막실사": lc.isoformat() if lc else None,
            "실사경과일": (date - lc).days if lc else None, "상태": status,
            "로트": [{"양(g)": round(l["qty"]), "유통기한": l["expiry"].isoformat() if l["expiry"] else None,
                     "입고": l["since"].isoformat()} for l in sorted(lots, key=lambda l: (l["expiry"] or dt.date.max))],
        })
        for l in exp_lots:
            dl = (l["expiry"] - date).days
            if dl <= EXPIRY_SOON:
                expiring.append({"식재료명": nm, "양(g)": round(l["qty"]), "유통기한": l["expiry"].isoformat(), "D": dl,
                                 "7일사용(g)": round(sum(use))})
    expiring.sort(key=lambda x: x["D"])
    items.sort(key=lambda x: (-len([s for s in x["상태"] if s != "실사 필요"]), x["D"] if x["D"] is not None else 99, x["식재료명"]))

    r, n = plans.run_for(date)
    today_menu = [m for m in (r["menu"] if r else []) if str(m.get("일차")) == f"{n}일"] if r else []
    count = lambda k: sum(1 for x in items if k in x["상태"])
    return {
        "date": date.isoformat(),
        "plan": ({"run_id": r["id"], "day": n, "start_date": r["start"].isoformat(), "n_days": r["n_days"],
                  "end_date": (r["start"] + dt.timedelta(days=r["n_days"] - 1)).isoformat()} if r else None),
        "next_plan": (None if r else next(({"start_date": x["start"].isoformat(), "days_until": (x["start"] - date).days,
                                             "end_date": (x["start"] + dt.timedelta(days=x["n_days"] - 1)).isoformat()}
                                            for x in sorted(plans.runs, key=lambda x: x["start"]) if x["start"] > date), None)),
        "today_menu": [{k: m.get(k) for k in ("끼니", "밥", "국", "주찬", "부찬1", "부찬2", "김치")} for m in today_menu],
        "summary": {"품목": len(items), "유통기한임박": count("유통기한 임박"), "유통기한지남": count("유통기한 지남"),
                    "부족예상": count("부족 예상"), "남을위험": count("남을 위험"), "실사필요": count("실사 필요"),
                    "추정재고(kg)": round(sum(x["추정재고(g)"] for x in items) / 1000, 1)},
        "items": items, "expiring": expiring,
        "untracked": [{"식재료명": k, "7일사용(g)": round(v)} for k, v in sorted(untracked.items(), key=lambda t: -t[1])[:30]],
        "shortfall_past": {k: round(v) for k, v in sim["shortfall"].items() if v >= 1},
    }


def snapshot(events: list, runs: list, date: dt.date) -> list:
    """date 아침 기준 추정 재고 → 식단 설계용 재고 표 [{식재료명, 재고량(g), 유통기한}]"""
    sim = simulate(events, Plans(runs), date)
    rows = []
    for nm, lots in sim["lots"].items():
        for l in lots:
            if l["qty"] > 0.5 and (not l["expiry"] or l["expiry"] >= date):
                rows.append({"식재료명": nm, "재고량(g)": round(l["qty"]),
                             "유통기한": l["expiry"].isoformat() if l["expiry"] else "", "비고": "재고 추적"})
    return sorted(rows, key=lambda r: (r["유통기한"] or "9999", r["식재료명"]))
